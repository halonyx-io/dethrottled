"""Waymarks: skip what a site has repeatedly refused, fail fast on known walls.

Measured cases behind each rule are in src/dethrottled/waymarks.py.
"""
import json
import os

import pytest
from test_fetch_internals import ARTICLE, tier

from dethrottled import fetch as f
from dethrottled import research
from dethrottled import waymarks as w

URL = "https://news.example.org/story"


@pytest.fixture(autouse=True)
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(w, "ENABLED", True)
    monkeypatch.setattr(w._paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(w, "_secret", None)
    monkeypatch.setattr(research, "public_url", lambda url: "intranet" not in url)
    monkeypatch.setattr(f, "_throttle", lambda domain: None)
    monkeypatch.setattr(f, "CRAWL4AI_URL", "http://renderer.invalid")
    w.reset()
    f._tier_rest.clear()
    yield
    w.reset()


def timed_out(tier_name="direct"):
    return {"tier": tier_name, "outcome": "failed", "reason": "ReadTimeout", "elapsed_ms": 20000}


def won(tier_name="tls"):
    return {"tier": tier_name, "outcome": "extracted", "reason": "", "elapsed_ms": 900}


def wall():
    return [{"tier": "direct", "outcome": "challenge", "reason": "challenge_detected"},
            {"tier": "tls", "outcome": "challenge", "reason": "tls_challenge_detected"},
            {"tier": "headed", "outcome": "challenge",
             "reason": "headed_challenge_unresolved:cloudflare"}]


def test_a_step_is_skipped_only_after_three_failures_with_a_later_win():
    for count in range(1, 4):
        w.observe(URL, [timed_out(), won()], "local")
        assert ("direct" in w.plan(URL, "local")["skip"]) is (count >= 3)


def test_nothing_is_skipped_when_no_later_step_has_worked():
    for _ in range(5):
        w.observe(URL, [timed_out(), {"tier": "tls", "outcome": "failed",
                                      "reason": "tls_ReadTimeout"}], "local")
    assert w.plan(URL, "local")["skip"] == {}


def test_a_step_that_answers_again_is_forgotten():
    for _ in range(3):
        w.observe(URL, [timed_out(), won()], "local")
    w.observe(URL, [won("direct")], "local")
    assert w.plan(URL, "local")["skip"] == {}


def test_page_level_results_and_our_own_capacity_never_build_a_streak():
    for _ in range(5):
        w.observe(URL, [{"tier": "direct", "outcome": "shell"},
                        {"tier": "crawl4ai", "outcome": "failed",
                         "reason": "crawl4ai_busy:render_memory_pressure"},
                        won("headed")], "local")
    assert w.plan(URL, "local")["skip"] == {}


def test_one_callers_streak_stays_private_until_a_second_caller_corroborates():
    for _ in range(3):
        w.observe(URL, [timed_out(), won()], "agent-a")
    assert "direct" in w.plan(URL, "agent-a")["skip"]
    assert w.plan(URL, "agent-b")["skip"] == {}, "agent-b must not learn agent-a's sites"
    w.observe(URL, [timed_out(), won()], "agent-c")
    assert "direct" in w.plan(URL, "agent-b")["skip"]


def test_private_hosts_are_never_recorded():
    for _ in range(5):
        w.observe("https://intranet.lan/wiki", [timed_out(), won()], "local")
    assert w.stats()["sites"] == 0


def test_the_file_holds_no_hosts_paths_or_callers(tmp_path):
    for _ in range(3):
        w.observe(URL, [timed_out(), won()], "agent-a")
    w.flush()
    text = (tmp_path / "waymarks.json").read_text()
    for secret in ("example", "news", "story", "agent-a"):
        assert secret not in text
    assert json.loads(text)
    if os.name == "posix":  # Windows has no POSIX permission bits
        assert oct((tmp_path / "waymarks.key").stat().st_mode & 0o777) == "0o600"


def test_skipped_steps_are_probed_again_after_the_probe_interval(monkeypatch):
    for _ in range(3):
        w.observe(URL, [timed_out(), won()], "local")
    later = __import__("time").time() + w.PROBE_SECONDS + 1
    monkeypatch.setattr(w.time, "time", lambda: later)
    assert w.plan(URL, "local")["skip"] == {}


def test_a_known_wall_fails_at_once_and_is_retried_later(monkeypatch):
    for _ in range(3):
        w.observe(URL, wall(), "local")
    plan = w.plan(URL, "local")
    assert plan["wall"]["kind"] == "cloudflare"
    later = __import__("time").time() + w.WALL_PROBE_SECONDS + 1
    monkeypatch.setattr(w.time, "time", lambda: later)
    assert w.plan(URL, "local")["wall"] is None


def test_the_ladder_skips_a_learned_step_and_says_so(monkeypatch):
    for _ in range(3):
        w.observe(URL, [timed_out(), won()], "local")
    monkeypatch.setattr(f, "_tier_direct", lambda *a, **k: pytest.fail("skipped step was run"))
    monkeypatch.setattr(f, "_tier_tls", tier(html=ARTICLE))
    result = f.fetch_and_extract(URL, max_chars=5000)
    assert result["ok"] and result["tier"] == "tls"
    skipped = result["acquisition_attempts"][0]
    assert skipped["tier"] == "direct" and skipped["outcome"] == "skipped"
    assert skipped["reason"] == "waymark:timeout x3"


def test_the_ladder_fails_fast_on_a_known_wall(monkeypatch):
    for _ in range(3):
        w.observe(URL, wall(), "local")
    for name in ("_tier_direct", "_tier_tls", "_tier_crawl4ai", "_tier_headed"):
        monkeypatch.setattr(f, name, lambda *a, **k: pytest.fail("wall was fetched"))
    result = f.fetch_and_extract(URL, max_chars=5000)
    assert not result["ok"] and result["reason"].startswith("waymark_known_wall:cloudflare")
    assert result["acquisition_attempts"][0]["waymark"]["streak"] == 3


def test_a_read_teaches_the_record_through_the_public_entry_point(monkeypatch):
    monkeypatch.setattr(f, "_tier_direct", tier(reason="ReadTimeout"))
    monkeypatch.setattr(f, "_tier_tls", tier(html=ARTICLE))
    for index in range(3):
        f.fetch_and_extract(URL + "?n=%d" % index, max_chars=5000)
    assert "direct" in w.plan(URL, "local")["skip"]


def test_disabled_means_no_learning_and_no_skipping(monkeypatch):
    monkeypatch.setattr(w, "ENABLED", False)
    for _ in range(3):
        w.observe(URL, [timed_out(), won()], "local")
    assert w.plan(URL, "local") == {"skip": {}, "wall": None}


def test_remote_callers_see_counts_not_domain_names(monkeypatch):
    from fastapi.testclient import TestClient

    from dethrottled import server
    from dethrottled.access import CLAIMS
    monkeypatch.setattr(server.domain_health, "stats", lambda: {
        "enabled": True, "tracked": 1,
        "domains": {"secret-site.example": {"ok": 0, "fail": 6, "deprioritised": True}}})
    client = TestClient(server.app)
    assert "secret-site.example" in client.get("/stats").text  # the local operator
    token = CLAIMS.set({"namespace": "remote-agent"})
    try:
        remote = server.stats()
    finally:
        CLAIMS.reset(token)
    assert "secret-site.example" not in json.dumps(remote)
    assert remote["domain_health"]["deprioritised"] == 1
    assert "sites" in remote["waymarks"]
