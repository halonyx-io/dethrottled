"""The DNB API signs the exact /drive body it posts to the worker."""

import pytest

from dethrottled import delegation, fetch


@pytest.mark.parametrize("public_target", [True, False])
def test_headed_read_signs_each_drive_payload(monkeypatch, tmp_path, public_target):
    pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    monkeypatch.setenv("DETHROTTLED_DNB", "1")
    monkeypatch.setenv("DETHROTTLED_DNB_PRIVATE_KEY", str(tmp_path / "issuer.pem"))
    monkeypatch.setenv("DETHROTTLED_DNB_PUBLIC_KEY", str(tmp_path / "issuer.pub"))
    delegation.ensure_keys()

    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "steps": [
                {"action": "goto", "data": {}, "document_ready_state": "complete"},
                {"action": "html", "data": "<html>Einstein</html>",
                 "document_ready_state": "complete"},
            ]}

    def post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "payload": json, "headers": headers})
        return Response()

    monkeypatch.setattr(fetch.requests, "post", post)
    from dethrottled import research
    monkeypatch.setattr(research, "public_url", lambda url: public_target)
    payload, reason, final = fetch._headed_read(
        "https://quotes.toscrape.com/js/", "http://dnb:19888")

    assert reason == ""
    assert final == "https://quotes.toscrape.com/js/"
    assert "Einstein" in payload["html"]
    assert calls and all("x-dnb-delegation" in call["headers"] for call in calls)
    for call in calls:
        claims = delegation.verify(
            call["headers"]["x-dnb-delegation"], call["payload"],
            str(tmp_path / "issuer.pub"), path="/drive")
        # A public target gets a public-only session: navigation stays on the
        # exact host while subresources may reach any public destination. A
        # private target keeps the internal scope, whose egress is the host.
        assert claims["public_only"] is public_target
        assert claims["allowed_hosts"] == ["quotes.toscrape.com"]
