"""Small DOMs, response presentation and distinct connect/read budgets."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dethrottled import fetch, server
from dethrottled.api_models import FetchBody


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DETHROTTLED_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_queue_corpus", lambda *a, **kw: None)
    monkeypatch.setattr(fetch, "ENABLE_TLS", False)
    monkeypatch.setattr(fetch, "CRAWL4AI_URL", "")
    return TestClient(server.app)


@pytest.mark.parametrize("html,selector,value", [
    ("<h1>Short title</h1>", "h1", "Short title"),
    ("<title>Head only</title>", "title", "Head only"),
    ('<a href="/next"></a>', "a", "/next"),
])
@pytest.mark.parametrize("fmt", ["text", "html"])
def test_tiny_html_retains_selector_dom(client, monkeypatch, html, selector, value, fmt):
    monkeypatch.setattr(fetch, "_tier_direct", lambda *a: ({"html": html}, "", a[0]))
    rule = {"selector": selector}
    if selector == "a":
        rule["attribute"] = "href"
    row = client.post("/fetch", json={
        "urls": ["https://fixture.example/"], "selectors": {"field": rule},
        "format": fmt, "render": "never", "recovery": "manual",
    }).json()[0]
    assert row["structured"] == {"field": value}
    assert row["structured_status"]["satisfied"]
    if fmt == "text":
        assert row["quality"] == "thin"
    assert "_selector_html" not in row


def response(url):
    html = b"<html><body>" + b"Useful evidence. " * 100 + b"</body></html>"
    return SimpleNamespace(status_code=200, headers={"Content-Type": "text/html"},
                           url=url, close=lambda: None, iter_content=lambda n: [html])


def test_crawl4ai_payload_preserves_html_only_when_requested():
    from dethrottled import fetch

    payload = {"markdown": "prose " * 100,
               "html": "<html><body><h1>Example Domain</h1><p>" + "padding " * 200 + "</p></body></html>",
               "cleaned_html": "<html><body><p>cleaned</p></body></html>"}
    token = fetch._READ_OPTIONS.set({"keep_html": True})
    try:
        result, reason, _ = fetch._crawl4ai_payload(payload, "https://example.com")
    finally:
        fetch._READ_OPTIONS.reset(token)
    assert not reason and "Example Domain" in result["html"]
    assert "prose" in result["text"]

    tiny = {"markdown": "short", "cleaned_html": "<h1>Tiny</h1>"}
    token = fetch._READ_OPTIONS.set({"keep_html": True})
    try:
        result, _, _ = fetch._crawl4ai_payload(tiny, "https://example.com")
    finally:
        fetch._READ_OPTIONS.reset(token)
    assert result["html"] == "<h1>Tiny</h1>"

    token = fetch._READ_OPTIONS.set({"keep_html": False})
    try:
        result, _, _ = fetch._crawl4ai_payload(payload, "https://example.com")
    finally:
        fetch._READ_OPTIONS.reset(token)
    assert "html" not in result


def test_direct_has_short_connect_budget_and_original_read_budget(monkeypatch):
    seen = {}
    monkeypatch.setattr(fetch, "_throttle", lambda *a: None)

    def get(url, **kw):
        seen.update(kw)
        return response(url)

    fetch._tier_direct_once("https://fixture.example/", 20, get=get)
    assert seen["timeout"] == (2, 20)


def test_short_caller_timeout_is_not_increased(monkeypatch):
    seen = {}
    monkeypatch.setattr(fetch, "_throttle", lambda *a: None)

    def get(url, **kw):
        seen.update(kw)
        return response(url)

    fetch._tier_direct_once("https://fixture.example/", 0.25, get=get)
    assert seen["timeout"] == (0.25, 0.25)


def test_tls_connect_budget_preserves_existing_stream_budget(monkeypatch):
    pytest.importorskip("curl_cffi")
    seen = {}
    monkeypatch.setattr(fetch, "ENABLE_TLS", True)

    def get(url, **kw):
        seen.update(kw)
        return response(url)

    fetch._tier_tls_once("https://fixture.example/", get=get)
    assert seen["timeout"] == (2, 6)


def test_large_detailed_response_warns_without_changing_default_or_evidence():
    from dethrottled.content import present_row

    row = {"content": "Excerpt", "document_id": "retained", "warnings": ["Existing"],
           "extraction": {"pages": [{"page": 1, "text_layer_blocks": [
               {"text": "Fact. " * 30000, "bbox": [1, 2, 3, 4]}]}]}}
    original = deepcopy(row)
    detailed = present_row(row, "detailed")
    assert row == original
    assert FetchBody(urls=["https://fixture.example/"]).response_format == "detailed"
    assert detailed["extraction"] == row["extraction"]
    assert any("response_format=concise" in w for w in detailed["warnings"])
    concise = present_row(row, "concise")
    assert concise["warnings"] == ["Existing"]
    assert "text_layer_blocks" not in concise["extraction"]["pages"][0]
    assert concise["document_id"] == "retained"


def test_small_detailed_response_does_not_warn():
    from dethrottled.content import present_row

    row = {"content": "Short evidence", "quality": "ok"}
    presented = present_row(row, "detailed")
    assert presented["content"] == row["content"] and presented["tokens_estimated"] == 3


def test_clipped_tiny_html_preserves_partial_flag(client, monkeypatch):
    monkeypatch.setattr(fetch, "_tier_direct", lambda *a: (
        {"html": "<h1>Clipped</h1>", "clipped": True}, "html_truncated", a[0]))
    row = client.post("/fetch", json={
        "urls": ["https://fixture.example/"], "render": "never", "recovery": "manual",
        "selectors": {"heading": {"selector": "h1"}},
    }).json()[0]
    assert row["structured"]["heading"] == "Clipped"
    assert row["structured_status"]["source_html_partial"]
    assert row["source_partial"]


@pytest.mark.parametrize("fmt", ["detailed", "concise"])
def test_http_presentation_applies_warning_only_to_large_detailed(client, monkeypatch, fmt):
    row = {"content": "Excerpt", "quality": "ok", "warnings": [],
           "extraction": {"pages": [{"page": 1, "text_layer_blocks": [
               {"text": "Fact. " * 30000}]}]}}
    monkeypatch.setattr(server, "_extract_row", lambda *a, **kw: deepcopy(row))
    result = client.post("/fetch", json={
        "urls": ["https://fixture.example/"], "response_format": fmt,
    }).json()[0]
    assert any("large_detailed_response" in w for w in result["warnings"]) == (fmt == "detailed")
    assert ("text_layer_blocks" in result["extraction"]["pages"][0]) == (fmt == "detailed")
    assert row["warnings"] == []


@pytest.mark.parametrize("transport", ["direct", "tls"])
def test_connected_slow_body_retains_read_allowance(monkeypatch, transport):
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    if transport == "tls":
        pytest.importorskip("curl_cffi")
    data = b"<html><body>" + b"Retained evidence. " * 100 + b"</body></html>"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data[:20])
            self.wfile.flush()
            time.sleep(0.15)
            self.wfile.write(data[20:])

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    monkeypatch.setattr(fetch, "CONNECT_TIMEOUT", 0.05)
    monkeypatch.setattr(fetch, "ENABLE_TLS", True)
    monkeypatch.setattr(fetch, "TLS_TIMEOUT", 1)
    monkeypatch.setattr(fetch, "_throttle", lambda *a: None)
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/"
        if transport == "direct":
            payload, reason, _ = fetch._tier_direct_once(url, 1)
        else:
            payload, reason, _ = fetch._tier_tls_once(url)
        assert reason == "" and payload["html"].encode() == data
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=1)
