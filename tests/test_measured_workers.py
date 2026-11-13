"""Admission fairness, killable worker recovery and independent model thresholds."""

import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from fastapi import HTTPException

from dethrottled import corpus, fetch, workers
from dethrottled.admission import AdmissionError, FairQueue


def test_local_admission_has_no_forty_attempt_ceiling(monkeypatch):
    monkeypatch.setattr(fetch, "CRAWL4AI_URL", "http://renderer")
    monkeypatch.setattr(fetch, "CRAWL4AI_BUDGET", -1)
    monkeypatch.setattr(fetch, "_crawl4ai_admitted", lambda u: ({"text": "read"}, "", u))
    monkeypatch.setattr(fetch, "_RENDER_QUEUE", FairQueue())
    assert all(fetch._tier_crawl4ai("https://fixture.example")[0] for _ in range(48))
    assert fetch._RENDER_QUEUE.stats()["completed"] == 48


def test_fair_queue_rotates_clients_and_rejects_overfull():
    queue = FairQueue(capacity=1, max_waiting=3, per_client=2)
    order = []

    def run(key, label):
        with queue.slot(key, timeout=3):
            order.append(label)

    with ThreadPoolExecutor(3) as pool:
        with queue.slot("holder"):
            futures = []
            for key, label in [("a", "a1"), ("a", "a2"), ("b", "b1")]:
                futures.append(pool.submit(run, key, label))
                deadline = time.monotonic() + 2
                while queue.stats()["waiting"] < len(futures) and time.monotonic() < deadline:
                    time.sleep(0.001)
            with pytest.raises(AdmissionError, match="full"), queue.slot("c"):
                pass
        for future in futures:
            future.result()
    assert order == ["a1", "b1", "a2"]
    assert queue.stats()["active"] == queue.stats()["waiting"] == 0


def test_queue_timeout_removes_ticket():
    queue = FairQueue(capacity=1)
    with queue.slot("first"):
        with pytest.raises(AdmissionError, match="timeout"), queue.slot("second", timeout=0.01):
            pass
    assert queue.stats()["waiting"] == 0
    assert queue.stats()["timed_out"] == 1


def test_concurrent_queue_capacity_is_respected():
    queue = FairQueue(capacity=2, max_waiting=30)
    maximum = 0
    lock = threading.Lock()

    def run(key):
        nonlocal maximum
        with queue.slot(str(key), timeout=3):
            with lock:
                maximum = max(maximum, queue.stats()["active"])
            time.sleep(0.005)

    with ThreadPoolExecutor(12) as pool:
        list(pool.map(run, range(30)))
    assert maximum == 2 and queue.stats()["completed"] == 30


@pytest.fixture
def runtime():
    path = Path(__file__).resolve().parents[1] / "workers/runtime.py"
    spec = spec_from_file_location("measured_worker_runtime", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Request:
    def __init__(self, disconnect_after=None, body=b"source"):
        self.started = time.monotonic()
        self.disconnect_after = disconnect_after
        self.body = body

    async def stream(self):
        yield self.body

    async def is_disconnected(self):
        return self.disconnect_after is not None and (
            time.monotonic() - self.started > self.disconnect_after
        )


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="Linux worker process-group lifecycle")
@pytest.mark.parametrize("failure", ["timeout", "disconnect", "cancel"])
def test_child_is_killed_before_worker_slot_is_released(runtime, tmp_path, failure):
    pidfile = tmp_path / "pid"
    child = tmp_path / "child.py"
    # Write the PID atomically: the test acts as soon as the file exists, and
    # a plain open() makes it exist, empty, before the PID is written.
    child.write_text(
        "import os,time\npath = "
        + repr(str(pidfile))
        + "\nopen(path + '.tmp', 'w').write(str(os.getpid()))\n"
        "os.replace(path + '.tmp', path)\ntime.sleep(10)\nprint('{}')\n"
    )
    runner = runtime.Runner(str(child), timeout=30)

    async def run():
        request = Request()
        task = asyncio.create_task(runner.execute(request))
        # Trigger the failure only once the child is running. A fixed 0.3 s
        # deadline raced interpreter startup on slow CI runners (macos-15-intel)
        # and killed the child before it wrote its PID.
        deadline = time.monotonic() + 10
        while not pidfile.exists() and not task.done() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        if task.done():
            await task  # Surface startup failures rather than waiting forever for a PID.
        assert pidfile.exists(), "worker child did not start within ten seconds"
        if failure == "timeout":
            runner.timeout = 0  # The runner rechecks its deadline while waiting.
        elif failure == "disconnect":
            request.disconnect_after = 0
        else:
            task.cancel()
        with pytest.raises((HTTPException, asyncio.CancelledError)):
            await task

    asyncio.run(run())
    assert not runner.busy and runner.pid is None
    assert pidfile.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)
    assert runner.counts["timed_out" if failure == "timeout" else "cancelled"] == 1
    runner.timeout = 30
    child.write_text('print(\'{"text":"recovered"}\')\n')
    assert asyncio.run(runner.execute(Request()))["text"] == "recovered"


def test_worker_bounds_input_and_output(runtime, tmp_path):
    child = tmp_path / "child.py"
    child.write_text("print('{}')")
    runner = runtime.Runner(str(child), max_bytes=2)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(runner.execute(Request(body=b"large")))
    assert exc.value.status_code == 413 and not runner.busy


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="Linux worker process-group lifecycle")
def test_worker_upload_deadline_releases_slot(runtime, tmp_path):
    class SlowRequest(Request):
        async def stream(self):
            await asyncio.sleep(1)
            yield b"late"

    child = tmp_path / "child.py"
    child.write_text('print(\'{"text":"recovered"}\')\n')
    runner = runtime.Runner(str(child), timeout=0.02)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(runner.execute(SlowRequest()))
    assert exc.value.status_code == 504
    assert not runner.busy and runner.pid is None
    assert runner.counts["timed_out"] == 1
    runner.timeout = 3
    assert asyncio.run(runner.execute(Request()))["text"] == "recovered"


def test_multilingual_model_never_reuses_minilm_vectors(tmp_path):
    primary = corpus.Corpus(tmp_path / "db")
    second = corpus.MultilingualCorpus(tmp_path / "db")
    assert primary.model_name != second.model_name
    assert primary.floor != second.floor


def test_readiness_exposes_unreachable_and_unconfigured(monkeypatch):
    workers._CACHED.clear()
    for name in ["BROWSER_SEARCH", "CRAWL4AI", "LAYOUT_WORKER", "MEDIA_WORKER", "FORMAT_WORKER"]:
        monkeypatch.delenv("DETHROTTLED_" + name + "_URL", raising=False)
    monkeypatch.setenv("DETHROTTLED_LAYOUT_WORKER_URL", "http://missing")

    def failed(*a, **kw):
        raise workers.requests.ConnectionError("not available")

    monkeypatch.setattr(workers.requests, "get", failed)
    result = workers.status()
    assert result["layout"]["status"] == "unreachable"
    assert result["speech"]["status"] == "not_configured"
    workers._CACHED.clear()


def test_backfill_preserves_original_index_and_resumes(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    monkeypatch.setenv("DETHROTTLED_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        corpus.Corpus, "_embed", lambda self, texts, **kw: [[1.0, 0.0]] * len(texts)
    )
    monkeypatch.setattr(
        corpus.MultilingualCorpus, "_embed", lambda self, texts, **kw: [[0.0, 1.0]] * len(texts)
    )
    primary = corpus.Corpus()
    primary.add("https://source.example/a", "source", "Factual source passage. " * 12)
    before = primary._db.execute("SELECT * FROM passages WHERE model='minilm'").fetchall()
    target = corpus.MultilingualCorpus()
    assert target.matrix()[0] is None
    assert corpus.backfill_multilingual(batch_urls=1) == len(before)
    assert corpus.backfill_multilingual(batch_urls=1) == 0
    assert primary._db.execute("SELECT * FROM passages WHERE model='minilm'").fetchall() == before
    assert len(target.matrix()[1]) == len(before)
    assert target.search("question", limit=1)[0]["url"] == "https://source.example/a"


def test_fallback_requires_matching_signature():
    from dethrottled.fallback import kind

    assert kind(b"<html>challenge</html>", "https://x/file.msg") == ""
    assert kind(b"PK\x03\x04", "https://x/file.xlsb?download=1") == "xlsb"
    assert kind(bytes.fromhex("d0cf11e0"), "https://x/file.msg") == "msg"


def test_scanned_layout_respects_ocr_disabled(monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")

    from dethrottled import layout

    pdf = pymupdf.open()
    pdf.new_page()
    data = pdf.tobytes()
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "success", "text": "source 291", "tables": []}

    def post(*a, **kw):
        calls.append(kw["params"])
        return Response()

    monkeypatch.setenv("DETHROTTLED_LAYOUT_WORKER_URL", "http://layout")
    monkeypatch.setattr(layout.requests, "post", post)
    meta = {"pages": [{"page": 1, "method": "ocr"}], "warnings": []}
    text, result = layout.read_pdf(data, "source 291", meta, 1000, {"allow_ocr": False})
    assert text == "source 291" and result["ocr_layout"]
    assert calls[0]["ocr"] is False


def test_dual_keeps_english_results_if_second_model_fails():
    class Index:
        def search(self, *a, **kw):
            return [{"url": "https://source.example", "text": "retained passage", "score": 0.8}]

    class Broken:
        def search(self, *a, **kw):
            raise FileNotFoundError("missing model")

    dual = corpus.DualCorpus.__new__(corpus.DualCorpus)
    dual.primary, dual.multilingual = Index(), Broken()
    rows = dual.search("question")
    assert rows[0]["url"] == "https://source.example"
    assert rows[0]["retrieval_warning"] == "multilingual_unavailable:FileNotFoundError"


@pytest.mark.parametrize(
    "suffix,scanned,refresh", [("xlsb", False, True), ("pdf", True, True), ("html", False, False)]
)
def test_upgraded_readers_refresh_only_affected_cached_content(
    monkeypatch, suffix, scanned, refresh
):
    monkeypatch.setenv("DETHROTTLED_FORMAT_WORKER_URL", "http://formats")
    monkeypatch.setenv("DETHROTTLED_LAYOUT_WORKER_URL", "http://layout")
    monkeypatch.setattr(fetch, "valid_url", lambda u: True)
    monkeypatch.setattr(
        fetch,
        "_tier_direct",
        lambda *a: ({"text": "upgraded extraction", "structured": True}, "", a[0]),
    )

    class Cache:
        def get(self, *a, **kw):
            return {
                "ok": True,
                "text": "old extraction",
                "chars": 14,
                "acquisition": {"layout_worker_configured": True},
                "extraction": {"pages": [{"method": "ocr"}] if scanned else []},
            }

        def put(self, *a, **kw):
            pass

    result = fetch.fetch_and_extract("https://fixture.example/a." + suffix, cache=Cache())
    assert result["text"] == ("upgraded extraction" if refresh else "old extraction")


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="Linux supervisor uses POSIX process groups")
@pytest.mark.parametrize("mode", ["stop", "crash", "complete"])
def test_backfill_native_child_is_supervised(mode):
    import sys

    from dethrottled.backfill import BackfillJob

    job = BackfillJob()
    program = (
        "import time;time.sleep(30)"
        if mode == "stop"
        else "import os,signal,resource;resource.setrlimit(resource.RLIMIT_CORE,(0,0));"
        "os.kill(os.getpid(),signal.SIGSEGV)"
        if mode == "crash"
        else "print('{\"passages\": 291}')"
    )
    job.start([sys.executable, "-c", program])
    try:
        if mode != "stop":
            # Cold/contended ARM runners can take longer than three seconds to
            # start Python. Do not turn a still-starting crash fixture into an
            # intentional stop and then assert that it crashed.
            job.watcher.join(timeout=15)
            assert not job.watcher.is_alive(), "child did not finish within the test deadline"
    finally:
        job.stop()
    assert job.process.poll() is not None and not job.watcher.is_alive()
    assert (
        job.state["status"]
        == {"stop": "interrupted", "crash": "failed", "complete": "complete"}[mode]
    )
    if mode == "complete":
        assert job.state["passages"] == 291


@pytest.mark.parametrize("lose_number", [False, True])
def test_layout_length_guard_does_not_count_appended_native_table_twice(monkeypatch, lose_number):
    pymupdf = pytest.importorskip("pymupdf")
    from dethrottled import layout
    data = (Path(__file__).resolve().parents[1] /
            "evaluations/dependable/fixtures/table.pdf").read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        native = pdf[0].get_text()
    candidate = ("## Page 1\nAllocation table. Verified source units: tonnes.\n"
                 "| Region | 2024 | 2025 |\n| ALPHA | 17 | 7341 |\n| BETA | 291 | 420 |")
    if lose_number:
        candidate = candidate.replace("7341", "")
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"status": "success", "text": candidate, "tables": [{}], "tables_total": 1}
    monkeypatch.setenv("DETHROTTLED_LAYOUT_WORKER_URL", "http://layout")
    monkeypatch.setattr(layout.requests, "post", lambda *a, **k: Response())
    text, meta = layout.read_pdf(data, native, {"pages": [{"page": 1, "method": "text"}],
        "warnings": []}, 12000, {"document_mode": "layout"})
    if lose_number:
        assert "7341" in text and "layout_unavailable_or_incomplete; native_parser_used" in (
            meta["warnings"])
    else:
        assert meta["parser"] == "docling" and text == candidate
