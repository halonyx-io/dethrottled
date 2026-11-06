"""Source selection, deterministic fields and mapping against controlled evidence."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dethrottled import search as fs
from dethrottled import server
from dethrottled.api_models import FetchBody, SearchBody
from dethrottled.content import constrained
from dethrottled.search_constraints import discovery_query
from dethrottled.selectors import fields
from dethrottled.site import crawl, map_site


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DETHROTTLED_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DETHROTTLED_ENGINE_HEALTH", str(tmp_path / "engines.json"))
    monkeypatch.setattr(server, "_queue_corpus", lambda *a, **k: None)
    return TestClient(server.app)


@pytest.mark.parametrize(
    "domains,excluded,host,expected",
    [
        (["nasa.gov"], [], "science.nasa.gov", True),
        (["nasa.gov"], [], "notnasa.gov", False),
        (["nasa.gov"], [], "nasa.gov.evil.org", False),
        (["nasa.gov", "noaa.gov"], [], "noaa.gov", True),
        (["nasa.gov"], ["science.nasa.gov"], "science.nasa.gov", False),
        ([], ["pinterest.com"], "www.pinterest.com", False),
        ([], ["pinterest.com"], "nasa.gov", True),
    ],
)
def test_explicit_constraints_enforce_host_boundaries(domains, excluded, host, expected):
    query, impossible = discovery_query("climate", domains, excluded)
    assert not impossible
    assert constrained(query, {"url": "https://" + host + "/report"}) is expected


def test_constraints_intersect_existing_site_instead_of_broadening():
    query, impossible = discovery_query("climate site:nasa.gov", ["science.nasa.gov"], [])
    assert not impossible
    assert constrained(query, {"url": "https://science.nasa.gov/a"})
    assert not constrained(query, {"url": "https://www.nasa.gov/a"})
    assert discovery_query("climate site:nasa.gov", ["noaa.gov"], [])[1]
    assert discovery_query("climate", ["nasa.gov"], ["nasa.gov"])[1]
    query, _ = discovery_query("climate -site:nasa.gov", ["nasa.gov", "noaa.gov"], [])
    assert not constrained(query, {"url": "https://nasa.gov/a"})
    assert constrained(query, {"url": "https://noaa.gov/a"})


@pytest.mark.parametrize(
    "value",
    [
        "https://nasa.gov",
        "*.nasa.gov",
        "nasa.gov/a",
        "nasa.gov:443",
        "-site:nasa.gov",
        "",
        "a..org",
    ],
)
def test_invalid_domain_is_request_error(value):
    with pytest.raises(ValueError):
        SearchBody(query="climate", domains=[value])


def test_idna_and_case_normalization():
    assert SearchBody(query="x", domains=["NASA.GOV.", "nasa.gov"]).domains == ["nasa.gov"]
    assert SearchBody(query="x", domains=["bücher.de"]).domains == ["xn--bcher-kva.de"]


def test_unsatisfiable_constraints_make_no_upstream_calls(client, monkeypatch):
    monkeypatch.setattr(fs, "search", lambda *a, **k: pytest.fail("upstream must not run"))
    result = client.post(
        "/v2/search",
        json={"query": "climate", "domains": ["nasa.gov"], "exclude_domains": ["nasa.gov"]},
    ).json()
    assert result["results"] == []
    assert result["outcome"] == "constraints_unsatisfiable"
    assert not result["degraded"]


def test_constraints_apply_to_corpus_and_preserve_order(client, monkeypatch):
    calls = []

    def acquire(query, **kw):
        calls.append(query)
        return (
            [
                {"url": "https://nasa.gov/a", "title": "A"},
                {"url": "https://noaa.gov/b", "title": "B"},
            ],
            {"discovery": {"outcome": "results", "degraded": False}},
        )

    monkeypatch.setattr(fs, "search", acquire)
    monkeypatch.setattr(
        server.ranker,
        "apply",
        lambda rows, *a, **k: ([*rows, {"url": "https://evil.org/c", "title": "C"}], []),
    )
    result = client.post(
        "/v2/search", json={"query": "climate", "domains": ["nasa.gov", "noaa.gov"], "limit": 2}
    ).json()
    assert [r["url"] for r in result["results"]] == ["https://nasa.gov/a", "https://noaa.gov/b"]
    assert len(calls) == 1 and "site:nasa.gov OR site:noaa.gov" in calls[0]


def test_no_survivors_preserves_provider_outage(client, monkeypatch):
    monkeypatch.setattr(
        fs,
        "search",
        lambda *a, **k: ([], {"discovery": {"outcome": "unavailable", "degraded": True}}),
    )
    result = client.post("/v2/search", json={"query": "climate", "domains": ["nasa.gov"]}).json()
    assert result["outcome"] == "unavailable"
    assert result["discovery"]["constraint_outcome"] == "no_matching_candidates"


def test_searx_filters_before_engine_cap_without_pagination(monkeypatch, tmp_path):
    monkeypatch.setenv("DETHROTTLED_ENGINE_HEALTH", str(tmp_path / "health.json"))
    monkeypatch.setattr(fs, "SEARXNG_URL", "http://worker")
    calls = []

    def get(url, **kw):
        calls.append(kw["params"])
        items = [{"url": f"https://other.org/{i}", "engine": "yahoo"} for i in range(4)]
        items += [{"url": f"https://nasa.gov/{i}", "engine": "yahoo"} for i in range(5)]
        return SimpleNamespace(status_code=200, json=lambda: {"results": items})

    monkeypatch.setattr(fs.requests, "get", get)
    rows = fs.searxng("climate site:nasa.gov", engines="yahoo", max_items=3)
    assert [r["url"] for r in rows] == [f"https://nasa.gov/{i}" for i in range(3)]
    assert [r["discovery"][0]["rank"] for r in rows] == [5, 6, 7]
    assert len(calls) == 1 and calls[0]["pageno"] == 1


RULES = {
    "title": {"selector": "h1"},
    "price": {"selector": ".price"},
    "links": {"selector": "a", "attribute": "href", "all": True},
    "optional": {"selector": ".optional", "required": False},
}
HTML = (
    '<html><h1>Verified title</h1><p class="price">£17.25</p>'
    '<a href="/first">One</a><a href="/second">Two</a></html>'
)


def specs(raw=RULES):
    return FetchBody(urls=["https://example.org"], selectors=raw).selectors


def test_selector_values_have_provenance_without_changing_quality():
    row = {
        "url": "https://example.org",
        "quality": "ok",
        "content": "prose",
        "document_id": "doc_1",
    }
    fields(row, specs(), HTML)
    assert row["structured"] == {
        "title": "Verified title",
        "price": "£17.25",
        "links": ["/first", "/second"],
        "optional": None,
    }
    assert row["structured_status"]["satisfied"]
    assert row["structured_provenance"]["document_id"] == "doc_1"
    assert len(row["structured_provenance"]["html_sha256"]) == 64
    assert row["quality"] == "ok" and row["content"] == "prose"


@pytest.mark.parametrize(
    "html,missing,reason",
    [
        ("<h1>Only title</h1>", ["price", "links"], "fields_absent"),
        ("<p>No fields</p>", ["title", "price", "links"], "fields_absent"),
        ("", ["title", "price", "links"], "html_unavailable"),
    ],
)
def test_missing_fields_are_not_transport_failure(html, missing, reason):
    row = fields({"quality": "ok"}, specs(), html)
    assert row["quality"] == "ok"
    assert not row["structured_status"]["satisfied"]
    assert row["structured_status"]["missing"] == missing
    assert row["structured_status"]["reason"] == reason


def test_selector_output_bounded_and_truncation_explicit():
    rules = {str(i): {"selector": "p", "all": True, "max_chars": 10000} for i in range(32)}
    row = fields({}, specs(rules), "<p>" + "X" * 12000 + "</p>")
    assert sum(len(s) for vals in row["structured"].values() for s in vals) == 64000
    assert row["structured_status"]["truncated_fields"]


@pytest.mark.parametrize(
    "selectors", [{"x": "string"}, {"x": {"selector": "["}}, {"": {"selector": "h1"}}]
)
def test_invalid_selector_contract_is_422(client, selectors):
    assert (
        client.post(
            "/extract", json={"urls": ["https://example.org"], "selectors": selectors}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("path", ["/fetch", "/extract"])
def test_selectors_use_acquired_html_not_truncated_prose(client, monkeypatch, path):
    calls = []

    def acquire(url, **kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "url": url,
            "tier": "direct",
            "extractor": "trafilatura",
            "text": ("A" * 1000)[: kwargs["max_chars"]],
            "chars": 1000,
            "html": HTML,
            "cached": False,
        }

    monkeypatch.setattr(server.fetcher, "fetch_and_extract", acquire)
    result = client.post(
        path,
        json={
            "urls": ["https://example.org"],
            "max_chars": 10,
            "selectors": RULES,
            "recovery": "manual",
        },
    ).json()[0]
    assert result["content"] == "A" * 10
    assert result["structured"]["title"] == "Verified title"
    assert "_selector_html" not in result and "html" not in result
    assert calls[0]["keep_html"] and calls[0]["format"] == "text"


def test_map_reads_seed_not_discovered_pages():
    calls = []

    def read(url):
        calls.append(url)
        return {
            "quality": "ok",
            "html": '<a href="/a">A</a><a href="/b">B</a><a href="https://other.org/x">X</a>',
        }

    result = map_site(["https://example.org/"], read, max_pages=10)
    assert calls == ["https://example.org/"]
    assert [r["url"] for r in result["sources"]] == [
        "https://example.org/",
        "https://example.org/a",
        "https://example.org/b",
    ]
    assert result["coverage"]["attempted"] == 0 and result["coverage"]["discovery_requests"] == 1
    assert result["coverage"]["outside_scope"] == 1
    assert all("document_id" not in r and "quality" not in r for r in result["sources"])


def test_map_nested_sitemaps_and_request_limit():
    pages = {
        "https://example.org/index.xml": "<sitemapindex><sitemap><loc>https://example.org/one.xml</loc>"
        "</sitemap><sitemap><loc>https://example.org/two.xml</loc></sitemap></sitemapindex>",
        "https://example.org/one.xml": "<urlset><url><loc>https://example.org/a</loc></url>"
        "<url><loc>https://other.org/b</loc></url></urlset>",
    }
    result = map_site(
        ["https://example.org/index.xml"],
        lambda u: {"quality": "ok", "content": pages[u]},
        max_discovery_requests=2,
    )
    assert result["sources"] == [
        {"url": "https://example.org/a", "depth": 2, "parent": "https://example.org/one.xml"}
    ]
    assert result["coverage"]["discovery_requests"] == 2
    assert result["coverage"]["stop_reason"] == "discovery_request_limit"
    assert result["continuation_urls"] == ["https://example.org/two.xml"]


def test_map_failure_redirect_and_truncation_are_visible():
    row = map_site(
        ["https://example.org"], lambda u: {"quality": "failed", "failure_reason": "timeout"}
    )
    assert row["outcome"] == "no_urls_discovered"
    assert row["coverage"]["discovery_failed"] == 1
    row = map_site(
        ["https://example.org"],
        lambda u: {
            "quality": "ok",
            "final_url": "https://other.org/",
            "html": '<a href="/stolen">x</a>',
        },
    )
    assert not row["sources"]
    assert row["discovery_attempts"][0]["failure_reason"] == "redirect_outside_site_scope"
    row = map_site(
        ["https://example.org"], lambda u: {"quality": "ok", "html": "<p>Hi</p>", "truncated": True}
    )
    assert row["outcome"] == "partial"


def test_map_url_limit_and_default_crawl_unchanged():
    def read(u):
        return {"quality": "ok", "html": "".join(f'<a href="/{i}">x</a>' for i in range(80))}

    row = map_site(["https://example.org"], read, max_pages=15)
    assert len(row["sources"]) == 15 and row["coverage"]["depth_or_discovery_limited"] == 66
    assert row["coverage"]["stop_reason"] == "url_limit"
    assert crawl(["https://example.org"], read, max_pages=2)["coverage"]["attempted"] == 2


def test_map_endpoint_neither_retains_nor_indexes_discovery(client, monkeypatch):
    monkeypatch.setattr(server, "_extract_row", lambda *a, **k: pytest.fail("no retained evidence"))
    monkeypatch.setattr(
        server.fetcher,
        "fetch_and_extract",
        lambda url, **kw: {"ok": True, "url": url, "html": HTML},
    )
    result = client.post(
        "/site/crawl", json={"urls": ["https://example.org"], "mode": "map"}
    ).json()
    assert result["operation"] == "site_map" and result["coverage"]["discovery_requests"] == 1
    assert result["workflow"]["next_actions"][0]["tool"] == "fetch"


@pytest.mark.parametrize(
    "reason", ["invalid_url", "public_target_required", "redirect_target_not_public"]
)
def test_terminal_refusals_do_not_trigger_browser_work(reason):
    from dethrottled.readplan import run

    row = run(
        "not-a-url",
        {"quality": "failed", "failure_reason": reason},
        read=lambda *a: pytest.fail("no extra reads"),
        drive=lambda *a, **k: pytest.fail("no browser work"),
        options={"allow_render": True},
        browser_available=True,
    )
    assert row["read_plan"]["stop_reason"] == "terminal_target_refusal"
    assert row["read_plan"]["decisions"] == []


def test_transient_connection_failure_keeps_recovery():
    from dethrottled.readplan import run

    calls = []
    row = run(
        "https://example.org/",
        {"quality": "failed", "failure_reason": "ConnectionError"},
        read=lambda *a: {},
        drive=lambda *a, **kw: calls.append(a) or {"ok": False},
        options={"allow_render": True},
        browser_available=True,
    )
    assert calls and row["read_plan"]["stop_reason"] != "terminal_target_refusal"


def test_existing_grouped_site_operators_rewrite_cleanly():
    query, impossible = discovery_query(
        "climate (site:nasa.gov OR site:noaa.gov)", ["nasa.gov"], []
    )
    assert not impossible and "( OR )" not in query and "noaa.gov" not in query
    assert constrained(query, {"url": "https://nasa.gov/report"})


def test_filtered_valid_serp_does_not_trigger_more_ddg_acquisition(monkeypatch, tmp_path):
    from dethrottled import discovery

    monkeypatch.setenv("DETHROTTLED_CHEAP_DISCOVERY", "1")
    monkeypatch.setenv("DETHROTTLED_ENGINE_HEALTH", str(tmp_path / "engines.json"))
    monkeypatch.setattr(fs, "BROWSER_SEARCH_URL", "")
    requests = []

    def get(*a, **kw):
        requests.append(1)
        return SimpleNamespace(
            status_code=200,
            headers={},
            text='<a class="result-link" href="https://other.org/report">A substantive report</a>'
            '<div class="result-snippet">A substantive source on the requested subject.</div>',
        )

    monkeypatch.setattr(discovery.requests, "get_using", get)
    monkeypatch.setattr(fs, "browser_search", lambda *a, **k: pytest.fail("no extra acquisition"))
    diagnostics = {}
    rows = fs.web_search("climate site:nasa.gov", max_items=10, diagnostics=diagnostics)
    assert rows == [] and len(requests) == 1
    assert diagnostics["status"] == "no_matching_candidates"
    from dethrottled.search_diagnostics import outcome

    assert outcome(0, diagnostics) == "empty"


def test_static_provider_filters_before_primary_cap(monkeypatch):
    from dethrottled import discovery

    html = "".join(
        f'<a class="result-link" href="https://{host}/{i}">A substantive report {i}</a>'
        '<div class="result-snippet">Substantive evidence for the requested subject.</div>'
        for i, host in enumerate(["other.org"] * 4 + ["nasa.gov"] * 12)
    )
    monkeypatch.setattr(
        discovery.requests,
        "get_using",
        lambda *a, **k: SimpleNamespace(status_code=200, headers={}, text=html),
    )
    diagnostics = {}
    rows = discovery.tls_search("climate site:nasa.gov", max_items=10, diagnostics=diagnostics)
    assert len(rows) == 10 and diagnostics["status"] == "ok"
    assert rows[0]["url"] == "https://nasa.gov/4"


def test_browser_recovery_fields_use_the_adopted_dom():
    from dethrottled.readplan import run

    html = HTML.replace("</html>", "<p>" + "Useful retained evidence. " * 60 + "</p></html>")

    def drive(*a, **kw):
        return {
            "ok": True,
            "final": {"url": "https://example.org/"},
            "steps": [
                {"action": "read_state", "data": {}},
                {"action": "html", "data": html, "ok": True},
            ],
        }

    row = run(
        "https://example.org/",
        {"quality": "thin", "content": "short"},
        read=lambda *a: {},
        drive=drive,
        options={"allow_render": True, "retain_html": True},
        browser_available=True,
    )
    body = FetchBody(urls=["https://example.org/"], selectors=RULES)
    server._finish_selectors([row], body)
    assert row["structured"]["title"] == "Verified title"
    assert row["structured_status"]["satisfied"]
    assert not any(k.startswith("_selector") for k in row)


def test_partial_html_is_distinct_from_filled_fields():
    row = fields({"quality": "ok"}, specs(), HTML, html_partial=True)
    assert row["structured_status"]["satisfied"]
    assert row["structured_status"]["source_html_partial"]


def test_private_redirect_preserves_terminal_policy_reason(monkeypatch):
    from dethrottled import fetch, research

    monkeypatch.setattr(research, "public_url", lambda url: "public.example.org" in url)
    monkeypatch.setattr(fetch, "_throttle", lambda *a: None)
    seen = []

    def get(url, **kw):
        seen.append(url)
        return SimpleNamespace(
            status_code=302, headers={"Location": "http://127.0.0.1/private"}, close=lambda: None
        )

    token = fetch._READ_OPTIONS.set({"public_only": True})
    try:
        _, reason, _ = fetch._tier_direct_once("https://public.example.org/", 1, get=get)
        assert reason == "public_target_required"
        _, reason, _ = fetch._tier_tls_once("https://public.example.org/", get=get)
        assert reason == "public_target_required"
    finally:
        fetch._READ_OPTIONS.reset(token)
    assert seen == ["https://public.example.org/"] * 2


def test_explicit_network_policy_refusal_does_not_escalate_tiers(monkeypatch):
    from dethrottled import fetch

    monkeypatch.setattr(fetch, "_tier_direct", lambda url, *a: ({}, "public_target_required", url))
    monkeypatch.setattr(fetch, "_tier_tls", lambda *a: pytest.fail("no policy bypass"))
    monkeypatch.setattr(fetch, "_tier_crawl4ai", lambda *a: pytest.fail("no policy bypass"))
    row = fetch.fetch_and_extract("https://example.org/")
    assert row["policy_blocked"] == "network"
    assert [a["tier"] for a in row["acquisition_attempts"]] == ["direct"]


def test_terminal_target_guidance_does_not_recommend_retry():
    from dethrottled.workflow import guidance

    for reason in ["invalid_url", "public_target_required", "redirect_target_not_public"]:
        row = guidance({"quality": "failed", "failure_reason": reason})
        assert row["state"] == "target_refused" and row["next_actions"] == []


def test_old_job_retries_keep_their_request_fingerprint(client, monkeypatch):
    import json
    from hashlib import sha256

    from dethrottled.api_models import FetchJobBody

    captured = []
    manager = SimpleNamespace(
        submit=lambda namespace, payload, *a: captured.append(payload) or "job",
        get=lambda *a: {"job_id": "job"},
    )
    monkeypatch.setattr(server, "jobs", lambda: manager)
    request = {"urls": ["https://example.org/"], "operation_id": "existing"}
    legacy = FetchJobBody(**request).model_dump(exclude={"operation_id", "selectors"})
    assert client.post("/jobs/fetch", json=request).status_code == 200

    def fingerprint(value):
        return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    assert fingerprint(captured[-1]) == fingerprint(legacy)
    assert (
        client.post(
            "/jobs/fetch", json={**request, "selectors": {"title": {"selector": "h1"}}}
        ).status_code
        == 200
    )
    assert fingerprint(captured[-1]) != fingerprint(legacy)
