"""Small live-web coverage check, with preregistered domains/phrases and raw replies.

This is acquisition/discovery evidence, not a paid-provider or answer-accuracy benchmark.
"""

import concurrent.futures
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = Path(os.getenv("DETHROTTLED_EVAL_OUTPUT", "evaluation-results"))
SEARCH = [
    ("python-sqlite", "Python sqlite3 official documentation", "python.org"),
    ("sqlite-wal", "SQLite WAL checkpoint official documentation", "sqlite.org"),
    ("mdn-indexeddb", "IndexedDB API MDN", "mozilla.org"),
    ("docling-layout", "Docling table structure PDF documentation", "docling-project.github.io"),
    ("crossref-api", "Crossref REST API documentation", "crossref.org"),
    ("w3c-provenance", "W3C PROV overview recommendation", "w3.org"),
    ("french-python", "documentation Python sqlite3 français", "python.org"),
    ("german-python", "Python Dokumentation sqlite3 deutsch", "python.org"),
]
READ = [
    ("python-doc", "https://docs.python.org/3/library/sqlite3.html", ["sqlite3", "Connection"]),
    ("sqlite-wal-doc", "https://www.sqlite.org/wal.html", ["checkpoint", "WAL"]),
    ("mdn-doc", "https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API", ["IndexedDB"]),
    ("docling-doc", "https://docling-project.github.io/docling/", ["Docling"]),
    ("w3c-doc", "https://www.w3.org/TR/prov-overview/", ["PROV"]),
    ("ietf-text", "https://www.rfc-editor.org/rfc/rfc9110.txt", ["HTTP Semantics"]),
    (
        "json-source",
        "https://raw.githubusercontent.com/vega/vega-datasets/main/data/cars.json",
        ["Miles_per_Gallon", "Horsepower"],
    ),
    (
        "csv-source",
        "https://raw.githubusercontent.com/plotly/datasets/master/2014_usa_states.csv",
        ["Alabama", "California"],
    ),
]
# Additional pairs widen the frozen suite to forty source tasks. Each pair has
# separate discovery and reading checks; these are not eighty independent questions.
PAIRS = [
    (
        "postgres-json",
        "PostgreSQL JSON types documentation",
        "postgresql.org",
        "https://www.postgresql.org/docs/current/datatype-json.html",
        ["jsonb"],
    ),
    (
        "redis-streams",
        "Redis streams documentation XADD",
        "redis.io",
        "https://redis.io/docs/latest/develop/data-types/streams/",
        ["XADD"],
    ),
    (
        "docker-health",
        "Docker Dockerfile HEALTHCHECK reference",
        "docker.com",
        "https://docs.docker.com/reference/dockerfile/",
        ["HEALTHCHECK"],
    ),
    (
        "kubernetes-probes",
        "Kubernetes liveness readiness startup probes documentation",
        "kubernetes.io",
        "https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/",
        ["readiness"],
    ),
    (
        "git-merge",
        "Git merge documentation official",
        "git-scm.com",
        "https://git-scm.com/docs/git-merge",
        ["merge"],
    ),
    (
        "rust-ownership",
        "Rust book ownership rules official",
        "rust-lang.org",
        "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
        ["ownership"],
    ),
    (
        "go-context",
        "Go context package documentation",
        "go.dev",
        "https://pkg.go.dev/context",
        ["WithCancel"],
    ),
    (
        "node-streams",
        "Node.js stream pipeline documentation",
        "nodejs.org",
        "https://nodejs.org/api/stream.html",
        ["pipeline"],
    ),
    (
        "typescript-narrowing",
        "TypeScript handbook narrowing documentation",
        "typescriptlang.org",
        "https://www.typescriptlang.org/docs/handbook/2/narrowing.html",
        ["typeof"],
    ),
    (
        "numpy-broadcasting",
        "NumPy broadcasting user guide",
        "numpy.org",
        "https://numpy.org/doc/stable/user/basics.broadcasting.html",
        ["broadcasting"],
    ),
    (
        "pandas-merge",
        "pandas merge API reference",
        "pandas.pydata.org",
        "https://pandas.pydata.org/docs/reference/api/pandas.merge.html",
        ["merge"],
    ),
    (
        "scipy-sparse",
        "SciPy sparse matrices documentation",
        "scipy.org",
        "https://docs.scipy.org/doc/scipy/reference/sparse.html",
        ["sparse"],
    ),
    (
        "pytorch-autograd",
        "PyTorch autograd automatic differentiation documentation",
        "pytorch.org",
        "https://docs.pytorch.org/docs/stable/autograd.html",
        ["autograd"],
    ),
    (
        "sklearn-validation",
        "scikit learn cross validation documentation",
        "scikit-learn.org",
        "https://scikit-learn.org/stable/modules/cross_validation.html",
        ["cross-validation"],
    ),
    (
        "fastapi-async",
        "FastAPI concurrency async await documentation",
        "fastapi.tiangolo.com",
        "https://fastapi.tiangolo.com/async/",
        ["await"],
    ),
    (
        "pydantic-models",
        "Pydantic models documentation validation",
        "pydantic.dev",
        "https://docs.pydantic.dev/latest/concepts/models/",
        ["BaseModel"],
    ),
    (
        "playwright-frames",
        "Playwright Python frames frame locator",
        "playwright.dev",
        "https://playwright.dev/python/docs/frames",
        ["frame_locator"],
    ),
    (
        "nginx-proxy",
        "nginx proxy_pass module documentation",
        "nginx.org",
        "https://nginx.org/en/docs/http/ngx_http_proxy_module.html",
        ["proxy_pass"],
    ),
    (
        "caddy-proxy",
        "Caddy reverse_proxy directive documentation",
        "caddyserver.com",
        "https://caddyserver.com/docs/caddyfile/directives/reverse_proxy",
        ["reverse_proxy"],
    ),
    (
        "openssl-dgst",
        "OpenSSL dgst documentation SHA256",
        "openssl.org",
        "https://docs.openssl.org/master/man1/openssl-dgst/",
        ["sha256"],
    ),
    (
        "curl-manual",
        "curl manual retry official",
        "curl.se",
        "https://curl.se/docs/manpage.html",
        ["--retry"],
    ),
    (
        "rfc-json",
        "RFC 8259 JSON official",
        "rfc-editor.org",
        "https://www.rfc-editor.org/rfc/rfc8259.txt",
        ["JavaScript Object Notation"],
    ),
    (
        "w3c-dcat",
        "W3C DCAT version 3 catalog recommendation",
        "w3.org",
        "https://www.w3.org/TR/vocab-dcat-3/",
        ["DCAT"],
    ),
    (
        "whatwg-fetch",
        "WHATWG Fetch standard specification",
        "whatwg.org",
        "https://fetch.spec.whatwg.org/",
        ["fetch"],
    ),
    (
        "unicode-normalization",
        "Unicode normalization forms UAX 15",
        "unicode.org",
        "https://www.unicode.org/reports/tr15/",
        ["Normalization"],
    ),
    (
        "openalex-api",
        "OpenAlex API documentation works",
        "openalex.org",
        "https://docs.openalex.org/",
        ["OpenAlex"],
    ),
    (
        "datacite-api",
        "DataCite REST API documentation",
        "datacite.org",
        "https://support.datacite.org/docs/api",
        ["DataCite"],
    ),
    (
        "zenodo-api",
        "Zenodo REST API documentation",
        "zenodo.org",
        "https://developers.zenodo.org/",
        ["Zenodo"],
    ),
    (
        "nasa-earth",
        "NASA Earth fact sheet official",
        "nasa.gov",
        "https://science.nasa.gov/earth/facts/",
        ["Earth"],
    ),
    (
        "esa-jupiter",
        "ESA Juice Jupiter mission overview",
        "esa.int",
        "https://www.esa.int/Science_Exploration/Space_Science/Juice",
        ["Jupiter"],
    ),
    (
        "worldbank-api",
        "World Bank indicators API documentation",
        "worldbank.org",
        "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation",
        ["API"],
    ),
    (
        "oecd-api",
        "OECD SDMX API data documentation",
        "oecd.org",
        "https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html",
        ["API"],
    ),
]
SEARCH += [(n, q, d) for n, q, d, u, e in PAIRS]
READ += [(n, u, e) for n, q, d, u, e in PAIRS]
manifest = {
    "search": SEARCH,
    "read": READ,
    "order": ["baseline", "candidate"],
    "limits": "40 paired query/source tasks (80 mechanical checks), one run per build, "
    "same-host sequential builds are exposed to upstream time variation.",
}
OUT.mkdir(exist_ok=True)
(OUT / "web-manifest.json").write_text(json.dumps(manifest, indent=2))
builds = os.getenv("DETHROTTLED_EVAL_BUILDS", "baseline,candidate").split(",")
records = []
if builds != ["baseline", "candidate"] and (OUT / "web-results.json").exists():
    records = [
        r for r in json.loads((OUT / "web-results.json").read_text()) if r["build"] not in builds
    ]


def run(item):
    build, kind, case = item
    name, source, expected = case
    base = (
        os.getenv("DETHROTTLED_EVAL_BASELINE_URL", "http://127.0.0.1:18396")
        if build == "baseline"
        else os.getenv("DETHROTTLED_EVAL_CANDIDATE_URL", "http://127.0.0.1:8787")
    )
    path = "/v2/search" if kind == "search" else "/fetch"
    payload = (
        {"query": source, "limit": 8, "fresh": True, "profile": "web"}
        if kind == "search"
        else {
            "urls": [source],
            "fresh": True,
            "max_chars": 120000,
            "recovery": "manual",
            "render": "never",
        }
    )
    request = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=150) as response:
            result = json.load(response)
        if kind == "search":
            rows = result.get("results", [])
            passed = any(expected in row.get("url", "") for row in rows)
        else:
            passed = result[0].get("quality") == "ok" and all(
                value.casefold() in result[0].get("content", "").casefold() for value in expected
            )
        row = {"pass": passed, "result": result}
    except Exception as exc:
        row = {"pass": False, "error": type(exc).__name__ + ": " + str(exc)[:200]}
    return {
        "build": build,
        "kind": kind,
        "case": name,
        "input": payload,
        "elapsed_ms": round((time.monotonic() - start) * 1000),
        **row,
    }


for build in builds:
    health_base = (
        os.getenv("DETHROTTLED_EVAL_BASELINE_URL", "http://127.0.0.1:18396")
        if build == "baseline"
        else os.getenv("DETHROTTLED_EVAL_CANDIDATE_URL", "http://127.0.0.1:8787")
    )
    for attempt in range(60):
        try:
            with urllib.request.urlopen(health_base + "/health", timeout=2) as ready:
                assert json.load(ready)["status"] == "ok"
            break
        except Exception:
            if attempt == 59:
                raise RuntimeError("Benchmark service was not ready; no cases scored") from None
            time.sleep(1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(
            run, [(build, "search", c) for c in SEARCH] + [(build, "read", c) for c in READ]
        ):
            records.append(result)
            (OUT / "web-results.json").write_text(json.dumps(records, indent=2))
            print(build, result["kind"], result["case"], result["pass"], flush=True)
print(
    {
        b: {
            k: sum(r["pass"] for r in records if r["build"] == b and r["kind"] == k)
            for k in ["search", "read"]
        }
        for b in ["baseline", "candidate"]
    }
)
