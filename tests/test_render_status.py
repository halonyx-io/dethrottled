"""A rendered error document must not become a successful extraction."""

from dethrottled import fetch


def test_render_uses_final_target_status(monkeypatch):
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
    monkeypatch.setattr(fetch, "RENDER_URL", "http://renderer")
    payload, reason, final = fetch._render_request("https://example.org/old")
    assert payload == {}
    assert reason == "render_target_http_404"
    assert final == "https://example.org/missing"
    assert requests_sent[0]["json"]["crawler_config"]["params"]["check_robots_txt"] is False


def test_render_accepts_rendered_success():
    assert fetch._render_target_error({"status_code": 200}) == ""
    assert fetch._render_target_error({"status_code": 302,
                                         "redirected_status_code": 200}) == ""


def test_direct_error_reads_only_challenge_prefix(monkeypatch):
    class Response:
        status_code = 403
        encoding = "utf-8"

        def __init__(self):
            self.headers = {}
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
    payload, reason, _ = fetch._tier_direct_once("https://example.org/a", 2, get=fetch.requests.get)
    assert payload == ""
    assert reason == "challenge_detected"
    assert response.chunks_read == 1
    assert response.closed
