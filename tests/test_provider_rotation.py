"""Optional provider key/proxy rotation; no network."""

from dethrottled import providers


class Response:
    def __init__(self, status=200, rows=None):
        self.status_code = status
        self.is_redirect = False
        self._rows = rows or []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http_%d" % self.status_code)

    def json(self):
        return {"results": self._rows}


def test_keys_rotate_on_rate_limit(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_EXA_API_KEYS", "key-a,key-b")
    monkeypatch.delenv("DETHROTTLED_EXA_API_KEY", raising=False)
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs["headers"].get("x-api-key"))
        if len(calls) == 1:
            return Response(429)
        return Response(200, [{"url": "https://example.com/a", "title": "A", "snippet": "s"}])

    monkeypatch.setattr(providers.requests, "post", post)
    report = {}
    rows = providers.search("exa", "q", 3, report)
    assert calls == ["key-a", "key-b"]
    assert rows and rows[0]["url"] == "https://example.com/a"
    assert report["status"] == "ok" and report["key_index"] == 1
    assert report["key_attempts"] == [{"key": 0, "status": 429}]


def test_exhausted_keys_are_reported_not_hidden(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_TAVILY_API_KEYS", "a,b")
    monkeypatch.delenv("DETHROTTLED_TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(providers.requests, "post", lambda *a, **k: Response(429))
    report = {}
    assert providers.search("tavily", "q", 3, report) == []
    assert report["status"] == "keys_exhausted"
    assert len(report["key_attempts"]) == 2


def test_proxy_pool_rotates_per_search(monkeypatch):
    monkeypatch.setenv("DETHROTTLED_PARALLEL_API_KEYS", "a")
    monkeypatch.setenv("DETHROTTLED_SEARCH_PROXIES", "http://p1:1,http://p2:2")
    seen = []

    def post(url, **kwargs):
        seen.append(kwargs.get("proxies"))
        return Response(200, [{"url": "https://example.com/a", "title": "A"}])

    monkeypatch.setattr(providers.requests, "post", post)
    providers.search("parallel", "q", 1, {})
    providers.search("parallel", "q", 1, {})
    assert seen[0]["https"] == "http://p1:1"
    assert seen[1]["https"] == "http://p2:2"
