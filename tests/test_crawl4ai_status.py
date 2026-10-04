"""A rendered error document must not become a successful extraction."""

from dethrottled import fetch


def test_crawl4ai_uses_final_target_status(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {"results": [{"success": True, "status_code": 302,
                                 "redirected_status_code": 404,
                                 "redirected_url": "https://example.org/missing",
                                 "markdown": "Error page " * 100}]}

    requests_sent = []
    monkeypatch.setattr(fetch.requests, "post",
                        lambda *a, **kw: (requests_sent.append(kw), Response())[1])
    monkeypatch.setattr(fetch, "CRAWL4AI_URL", "http://renderer")
    payload, reason, final = fetch._crawl4ai_via_crawl("https://example.org/old")
    assert payload == {}
    assert reason == "crawl4ai_target_http_404"
    assert final == "https://example.org/missing"
    assert requests_sent[0]["json"]["crawler_config"]["params"]["check_robots_txt"] is False


def test_crawl4ai_accepts_rendered_success():
    assert fetch._crawl4ai_target_error({"status_code": 200}) == ""
    assert fetch._crawl4ai_target_error({"status_code": 302,
                                         "redirected_status_code": 200}) == ""


def test_direct_error_reads_only_challenge_prefix(monkeypatch):
    class Response:
        status_code = 403
        headers = {}
        encoding = "utf-8"

        def __init__(self):
            self.chunks_read = 0
            self.closed = False

        @property
        def content(self):
            raise AssertionError("must not buffer the error body")

        def iter_content(self, size):
            for part in (b"Just a moment..." + b"x" * 9000, b"ignored"):
                self.chunks_read += 1
                yield part

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(fetch, "_throttle", lambda domain: None)
    monkeypatch.setattr(fetch.requests, "get", lambda *a, **kw: response)
    payload, reason, _ = fetch._tier_direct("https://example.org/a", 2)
    assert payload == ""
    assert reason == "challenge_needs_a_human"
    assert response.chunks_read == 1
    assert response.closed
