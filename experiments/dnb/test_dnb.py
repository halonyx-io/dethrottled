"""Prototype boundaries and deterministic extraction; run inside its image."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import dnb_service as dnb
import pytest
from fastapi import HTTPException
from pydantic import ValidationError


def body(**params):
    return dnb.CrawlRequest(
        urls=["https://example.org/"], crawler_config={"type": "CrawlerRunConfig", "params": params}
    )


@pytest.mark.parametrize(
    "params",
    [
        {"js_code": "alert(1)"},
        {"page_timeout": True},
        {"page_timeout": 60000},
        {"delay_before_return_html": float("nan")},
        {"wait_for": "js:alert(1)"},
        {"cache_mode": "enabled"},
        {"check_robots_txt": True},
    ],
)
def test_unsupported_or_unbounded_options_fail(params):
    with pytest.raises(HTTPException) as error:
        dnb.options(body(**params))
    assert error.value.status_code == 422


def test_batch_is_deliberately_not_supported():
    with pytest.raises(ValidationError):
        dnb.CrawlRequest(urls=["https://a.test", "https://b.test"])


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://u:p@example.org",
        "http://example.org:999999",
        "javascript:alert(1)",
    ],
)
def test_url_boundary(url):
    assert not dnb.valid_url(url)


def test_crawl_uses_upstream_extraction_and_relative_link_resolution():
    text = '<html><head><base href="https://example.org/papers/"></head><body><article>'
    text += "<h1>Complete evidence</h1><p>First marker quartz-782</p>"
    text += "<p>Substantial evidence about browsers and content.</p>" * 40
    text += '<a href="appendix">Appendix</a><p>Final marker jade-382</p></article></body></html>'
    result = dnb.extract("https://example.org", text)
    md = result["markdown"]["raw_markdown"]
    assert result["success"] and "quartz-782" in md and "jade-382" in md
    assert "https://example.org/papers/appendix" in md


def test_nonpublic_target_rejected_before_context_creation(monkeypatch):
    monkeypatch.setattr(dnb, "ALLOW_INTERNAL", False)
    monkeypatch.setattr(dnb.browser, "_public_network_target", AsyncMock(return_value=False))
    create = AsyncMock()
    monkeypatch.setattr(dnb, "create_state", create)
    with pytest.raises(HTTPException) as error:
        asyncio.run(dnb.crawl(body()))
    assert error.value.status_code == 403
    create.assert_not_awaited()


def test_failed_navigation_closes_context_and_releases_admission(monkeypatch):
    monkeypatch.setattr(dnb, "ALLOW_INTERNAL", True)
    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(dnb, "RENDER_SLOTS", semaphore)
    page = SimpleNamespace(on=lambda *args: None)
    monkeypatch.setattr(
        dnb.browser, "_navigate", AsyncMock(side_effect=TimeoutError("navigation timeout"))
    )
    context = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        dnb, "create_state", AsyncMock(return_value={"page": page, "context": context})
    )
    dnb.app.state.browser = object()
    with pytest.raises(HTTPException) as error:
        asyncio.run(dnb.crawl(body()))
    assert error.value.status_code == 504
    assert error.value.detail["code"] == "browser_timeout"
    assert error.value.detail["retryable"] is False
    context.close.assert_awaited_once()
    assert semaphore._value == 1


def test_blank_render_is_not_usable_content():
    result = dnb.extract("https://example.org", "<html><body><script>1+1</script></body></html>")
    assert not result["success"]


def test_unknown_browser_config_is_not_silently_ignored():
    request = dnb.CrawlRequest(
        urls=["https://example.org"],
        browser_config={"type": "BrowserConfig", "params": {"user_agent": "unverified"}},
    )
    with pytest.raises(HTTPException):
        dnb.options(request)


@pytest.mark.parametrize("params", [
    {"url": "http://["},
    {"steps": [{"action": "goto", "url": "http://["}]},
])
def test_malformed_drive_url_leaves_no_admission_or_journal_entry(monkeypatch, params):
    monkeypatch.setattr(dnb, "DRIVE_INFLIGHT", 0)
    monkeypatch.setattr(dnb, "principal", lambda _: {"sub": "test-owner"})
    journal = SimpleNamespace(begin=lambda *_: pytest.fail("invalid URL entered journal"))
    monkeypatch.setattr(dnb, "OPERATION_STORE", journal)
    monkeypatch.setattr(dnb, "SESSION_OWNERS", SimpleNamespace(claim=lambda *_: None))
    body = dnb.browser.DriveRequest(session="fixture", operation_id="test", **params)
    with pytest.raises(HTTPException) as error:
        asyncio.run(dnb.bounded_drive(body, None))
    assert error.value.status_code == 422
    assert dnb.DRIVE_INFLIGHT == 0
