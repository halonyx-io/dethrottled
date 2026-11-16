"""Per-site routes for 50 of the sites agents use most: where to start, and
official keyless APIs that read better than the page.

Measured on live 1.8.10, 16 Nov 2026 (`~/web-bench/results/site-routes`), one
representative page per site through the full ladder, every result checked by
hand. Two things live here, and only here, so every site-specific choice is in
one reviewable table:

PINS     the step that read the site, tried first. The rest of the ladder
         still follows in its normal order if it fails, so a pin can only cost
         one attempt, never a read. Sites read by plain HTTP need no pin.
READERS  official, keyless APIs for sites whose pages are walled or slow:
         Stack Exchange (Cloudflare wall, 15 s then failure), PubMed
         (bot-check page, 5 s via the browser), GitHub (5.9 s via the
         renderer), npm (Cloudflare wall), ScienceDirect (Cloudflare wall;
         Crossref metadata and abstract) and ResearchGate (Cloudflare wall;
         OpenAlex metadata and abstract). A reader that fails or hits its
         quota hands over to the normal ladder; the attempt is recorded as
         `api:<name>`.

Not here on purpose: anything that defeats a site's bot protection. Reuters,
Indeed, G2, WSJ, Yelp, TripAdvisor, Bloomberg, eBay, EUR-Lex and Google
(search and Scholar) stay honest, reported failures.
"""
from __future__ import annotations

import html
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlparse

from . import __version__
from . import netfilter as requests

PINS = {
    # TLS first: plain HTTP was challenged or silent for 3 s first.
    "cloudflare.com": "tls", "openai.com": "tls", "medium.com": "tls",
    "www.microsoft.com": "tls", "sec.gov": "tls",
    # Renderer first: plain HTTP returned an app shell or a refusal.
    "developers.cloudflare.com": "crawl4ai", "docs.docker.com": "crawl4ai",
    "imdb.com": "crawl4ai", "commission.europa.eu": "crawl4ai", "crunchbase.com": "crawl4ai",
    "instagram.com": "crawl4ai", "x.com": "crawl4ai", "reddit.com": "crawl4ai",
    "learn.microsoft.com": "crawl4ai", "github.com": "crawl4ai",
    "pubmed.ncbi.nlm.nih.gov": "crawl4ai",
    # Real browser first: every cheaper step refused (HTTP 202) or came back empty.
    "booking.com": "headed",
}

USER_AGENT = "dethrottled/%s (+https://github.com/halonyx-io/dethrottled)" % __version__
TIMEOUT = 8


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def _match(host: str, table: dict):
    """Most specific entry for host (exact, then parent domains)."""
    parts = host.split(".")
    for index in range(len(parts) - 1):
        candidate = ".".join(parts[index:])
        if candidate in table:
            return table[candidate]
        if index == 0 and candidate.startswith("www.") and candidate[4:] in table:
            return table[candidate[4:]]
    return None


def pinned_step(url: str) -> str | None:
    return _match(_host(url), PINS)


def _get(url, **kwargs):
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return requests.get(url, timeout=kwargs.pop("timeout", TIMEOUT), headers=headers, **kwargs)


def _text_from_html(fragment: str) -> str:
    """Keep code blocks and paragraphs readable; drop the rest of the markup."""
    fragment = fragment or ""
    fragment = re.sub(r"(?is)<pre[^>]*>(.*?)</pre>",
                      lambda m: "\n```\n" + re.sub(r"<[^>]+>", "", m.group(1)) + "\n```\n",
                      fragment)
    fragment = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</blockquote>", "\n", fragment)
    fragment = re.sub(r"(?i)<li[^>]*>", "- ", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = html.unescape(fragment)
    return re.sub(r"\n{3,}", "\n\n", fragment).strip()


def _iso(epoch) -> str:
    try:
        return datetime.fromtimestamp(int(epoch), timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _result(text, *, title, source, method, published="", partial=False, warnings=(),
            license=""):
    extraction = {"method": "api:" + method, "api_source": source}
    if partial:
        extraction.update(partial=True, partial_reason="publisher_page_unavailable")
    if license:
        extraction["license"] = license
    # structured: an API answer is complete as returned (never "thin"), keeps its
    # line breaks (code), and is not scanned as a web page for block markers.
    return {"text": text, "title": title, "extractor": "api:" + method, "structured": True,
            "content_type": "html", "extraction": extraction,
            "page_metadata": {"published": published} if published else {},
            "content_status": "partial" if partial else "complete",
            "source_partial": partial, "warnings": list(warnings)}


class Unavailable(Exception):
    """The API could not serve this; the normal ladder takes over."""


# ── Stack Exchange ──────────────────────────────────────────────────────────
# Keyless: 300 requests a day per IP, two per question read.
_SE_SITES = {"stackoverflow.com": "stackoverflow", "superuser.com": "superuser",
             "serverfault.com": "serverfault", "askubuntu.com": "askubuntu",
             "mathoverflow.net": "mathoverflow.net", "stackapps.com": "stackapps"}
_SE_PATH = re.compile(r"^/(?:questions|q|a)/(\d+)")
_se_backoff_until = 0.0
_se_lock = threading.Lock()


def _se_site(host):
    host = host.removeprefix("www.")
    if host in _SE_SITES:
        return _SE_SITES[host]
    if host.endswith(".stackexchange.com") and host.count(".") == 2:
        return host.split(".")[0]
    return None


def _se_call(path, site):
    global _se_backoff_until
    with _se_lock:
        if time.time() < _se_backoff_until:
            raise Unavailable("stackexchange_backoff")
    response = _get("https://api.stackexchange.com/2.3" + path,
                    params={"site": site, "filter": "withbody"})
    try:
        data = response.json()  # errors are JSON too, with error_name
    except ValueError:
        data = {}
    if response.status_code != 200 or "error_id" in data:
        raise Unavailable("stackexchange_%s" % (data.get("error_name") or response.status_code))
    with _se_lock:
        if data.get("backoff"):
            _se_backoff_until = time.time() + float(data["backoff"])
        if int(data.get("quota_remaining", 1)) <= 0:
            _se_backoff_until = time.time() + 3600
    return data


def read_stackexchange(url):
    parsed = urlparse(url)
    site, match = _se_site(_host(url)), _SE_PATH.match(parsed.path)
    if not site or not match:
        return None
    number = match.group(1)
    if parsed.path.startswith("/a/"):
        answer = _se_call("/answers/%s" % number, site).get("items") or []
        if not answer:
            raise Unavailable("stackexchange_answer_not_found")
        number = str(answer[0]["question_id"])
    question = (_se_call("/questions/%s" % number, site).get("items") or [None])[0]
    if not question:
        raise Unavailable("stackexchange_question_not_found")
    answers = _se_call("/questions/%s/answers" % number + "?sort=votes&order=desc&pagesize=5",
                       site).get("items") or []
    title = html.unescape(question.get("title", ""))
    owner = (question.get("owner") or {}).get("display_name", "unknown")
    parts = ["# " + title,
             "Question, score %s, asked %s by %s. Tags: %s" % (
                 question.get("score"), _iso(question.get("creation_date")), html.unescape(owner),
                 ", ".join(question.get("tags", []))),
             _text_from_html(question.get("body", ""))]
    for index, answer in enumerate(answers, 1):
        author = (answer.get("owner") or {}).get("display_name", "unknown")
        parts += ["## Answer %d%s, score %s, by %s, %s" % (
                      index, " (accepted)" if answer.get("is_accepted") else "",
                      answer.get("score"), html.unescape(author),
                      _iso(answer.get("creation_date"))),
                  _text_from_html(answer.get("body", ""))]
    total = question.get("answer_count", len(answers))
    if total > len(answers):
        parts.append("(%d of %d answers shown, highest score first.)" % (len(answers), total))
    parts.append("Source: %s. Content by its authors, licensed CC BY-SA."
                 % question.get("link", url))
    return _result("\n\n".join(parts), title=title, source="api.stackexchange.com",
                   method="stackexchange", published=_iso(question.get("creation_date")),
                   license="CC BY-SA")


# ── PubMed (NCBI E-utilities) ───────────────────────────────────────────────
# Keyless: three requests a second per IP.
_PUBMED = re.compile(r"^/(\d+)/?$")
_ncbi_lock = threading.Lock()
_ncbi_next = 0.0


def _ncbi(path, params):
    global _ncbi_next
    with _ncbi_lock:
        delay = _ncbi_next - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _ncbi_next = time.monotonic() + 0.34
    response = _get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/" + path,
                    params={**params, "tool": "dethrottled"})
    if response.status_code != 200:
        raise Unavailable("ncbi_http_%d" % response.status_code)
    return response


def read_pubmed(url):
    if _host(url) != "pubmed.ncbi.nlm.nih.gov":
        return None
    match = _PUBMED.match(urlparse(url).path)
    if not match:
        return None
    pmid = match.group(1)
    text = _ncbi("efetch.fcgi", {"db": "pubmed", "id": pmid, "rettype": "abstract",
                                 "retmode": "text"}).text.strip()
    if len(text) < 80:
        raise Unavailable("ncbi_empty")
    summary = _ncbi("esummary.fcgi", {"db": "pubmed", "id": pmid, "retmode": "json"}).json()
    record = (summary.get("result") or {}).get(pmid) or {}
    title = record.get("title", "")
    published = ""
    for key in ("sortpubdate", "epubdate", "pubdate"):
        found = re.match(r"(\d{4})/(\d{2})/(\d{2})", record.get(key) or "")
        if found:
            published = "-".join(found.groups())
            break
    return _result(text + "\n\nSource: PubMed %s (NCBI E-utilities)." % pmid, title=title,
                   source="eutils.ncbi.nlm.nih.gov", method="pubmed", published=published)


# ── GitHub ──────────────────────────────────────────────────────────────────
# README and files from raw.githubusercontent.com (no quota); repository details
# from the keyless REST API (60 requests an hour per IP), skipped when exhausted.
_GH_RESERVED = {"about", "orgs", "settings", "marketplace", "topics", "search", "login",
                "explore", "features", "pricing", "sponsors", "collections", "trending",
                "notifications", "issues", "pulls", "enterprise", "apps", "site"}
_GH_TEXT = re.compile(r"\.(?:md|markdown|rst|txt|py|js|ts|tsx|jsx|go|rs|java|kt|c|h|cpp|hpp|cs|"
                      r"rb|php|sh|bash|zsh|yml|yaml|toml|ini|cfg|json|xml|html|css|scss|sql|"
                      r"swift|m|scala|lua|r|pl|dockerfile|gitignore|env|lock)$", re.I)
_gh_api_until = 0.0


def _github_details(owner, repo):
    global _gh_api_until
    if time.time() < _gh_api_until:
        return {}
    response = _get("https://api.github.com/repos/%s/%s" % (owner, repo),
                    headers={"Accept": "application/vnd.github+json"})
    if response.status_code in (403, 429):
        reset = response.headers.get("X-RateLimit-Reset")
        _gh_api_until = float(reset) if reset and reset.isdigit() else time.time() + 900
        return {}
    if response.status_code == 404:
        raise Unavailable("github_repo_not_found")
    return response.json() if response.status_code == 200 else {}


def read_github(url):
    if _host(url) not in {"github.com", "www.github.com"}:
        return None
    segments = [unquote(part) for part in urlparse(url).path.split("/") if part]
    if len(segments) < 2 or segments[0].lower() in _GH_RESERVED:
        return None
    owner, repo = segments[0], segments[1].removesuffix(".git")
    if len(segments) >= 5 and segments[2] == "blob" and _GH_TEXT.search(segments[-1]):
        raw = "https://raw.githubusercontent.com/%s/%s/%s" % (
            owner, repo, "/".join(quote(part) for part in segments[3:]))
        response = _get(raw)
        if response.status_code != 200 or not response.text.strip():
            raise Unavailable("github_raw_http_%d" % response.status_code)
        name = "/".join(segments[4:])
        return _result("# %s/%s: %s\n\n%s\n\nSource: %s" % (owner, repo, name, response.text, raw),
                       title="%s/%s: %s" % (owner, repo, name),
                       source="raw.githubusercontent.com", method="github")
    if len(segments) != 2:
        return None  # issues, pulls, trees, wikis: the page itself
    details = _github_details(owner, repo)
    readme = ""
    for name in ("README.md", "readme.md", "README.rst", "README", "Readme.md", "README.txt"):
        response = _get("https://raw.githubusercontent.com/%s/%s/HEAD/%s" % (owner, repo, name))
        if response.status_code == 200 and response.text.strip():
            readme = response.text
            break
    if not readme and not details:
        raise Unavailable("github_no_readme")
    lines = ["# %s/%s" % (owner, repo)]
    if details:
        if details.get("description"):
            lines.append(details["description"])
        facts = ["Stars %s" % details.get("stargazers_count"),
                 "forks %s" % details.get("forks_count"),
                 "language %s" % details.get("language"),
                 "licence %s" % ((details.get("license") or {}).get("spdx_id") or "none"),
                 "updated %s" % (details.get("pushed_at") or "")[:10]]
        lines.append(" · ".join(facts))
        if details.get("topics"):
            lines.append("Topics: " + ", ".join(details["topics"]))
        if details.get("homepage"):
            lines.append("Homepage: " + details["homepage"])
        if details.get("archived"):
            lines.append("This repository is archived.")
    warnings = [] if details else ["github_api_quota_exhausted; repository details omitted"]
    lines += ["", "README:", readme or "(no README found)"]
    return _result("\n".join(lines), title="%s/%s" % (owner, repo),
                   source="api.github.com" if details else "raw.githubusercontent.com",
                   method="github", published=(details.get("pushed_at") or "")[:10],
                   warnings=warnings)


# ── npm ─────────────────────────────────────────────────────────────────────
_NPM = re.compile(r"^/package/((?:@[^/]+/)?[^/]+)")


def read_npm(url):
    if _host(url).removeprefix("www.") != "npmjs.com":
        return None
    match = _NPM.match(urlparse(url).path)
    if not match:
        return None
    name = unquote(match.group(1))
    response = _get("https://registry.npmjs.org/%s/latest" % name.replace("/", "%2F", 1)
                    if name.startswith("@") else "https://registry.npmjs.org/%s/latest" % name)
    if response.status_code != 200:
        raise Unavailable("npm_http_%d" % response.status_code)
    meta = response.json()
    version = meta.get("version", "latest")
    readme = ""
    for file in ("README.md", "readme.md", "Readme.md", "README"):
        got = _get("https://cdn.jsdelivr.net/npm/%s@%s/%s" % (name, version, file))
        if got.status_code == 200 and got.text.strip():
            readme = got.text
            break
    repository = meta.get("repository")
    repository = repository.get("url") if isinstance(repository, dict) else repository
    lines = ["# %s %s" % (name, version), meta.get("description") or "",
             "Licence %s · %d dependencies" % (meta.get("license") or "none",
                                                 len(meta.get("dependencies") or {})),
             "Install: npm install %s" % name]
    if meta.get("homepage"):
        lines.append("Homepage: " + meta["homepage"])
    if repository:
        lines.append("Repository: " + str(repository))
    if meta.get("keywords"):
        lines.append("Keywords: " + ", ".join(meta["keywords"][:20]))
    lines += ["", "README:", readme or "(no README published)"]
    return _result("\n".join(lines), title="%s %s" % (name, version),
                   source="registry.npmjs.org", method="npm")


# ── Papers behind walls: open metadata and abstract ─────────────────────────
_PII = re.compile(r"/pii/([A-Z0-9]+)", re.I)
_RG = re.compile(r"^/publication/\d+_(.+)$")
PARTIAL_NOTE = ("publisher_page_unavailable; metadata_and_abstract_from_open_scholarly_"
                "records; read the open-access copy for full text")


def _crossref_text(item):
    title = " ".join(item.get("title") or [])
    authors = ", ".join(" ".join(filter(None, (a.get("given"), a.get("family"))))
                        for a in (item.get("author") or [])[:20])
    issued = "-".join(str(p) for p in ((item.get("issued") or {}).get("date-parts") or [[]])[0])
    abstract = _text_from_html(item.get("abstract", ""))
    lines = ["# " + title, "Authors: " + authors,
             "Published: %s in %s" % (issued, " ".join(item.get("container-title") or [])),
             "DOI: https://doi.org/" + item.get("DOI", "")]
    lines += ["", "Abstract:", abstract or "(no abstract deposited with Crossref)"]
    return title, "\n".join(lines), issued


def read_sciencedirect(url):
    if _host(url).removeprefix("www.") != "sciencedirect.com":
        return None
    match = _PII.search(urlparse(url).path)
    if not match:
        return None
    response = _get("https://api.crossref.org/works",
                    params={"filter": "alternative-id:" + match.group(1), "rows": 1}, timeout=12)
    items = ((response.json().get("message") or {}).get("items")
             if response.status_code == 200 else [])
    if not items:
        raise Unavailable("crossref_not_found")
    title, text, issued = _crossref_text(items[0])
    return _result(text + "\n\nSource: Crossref metadata for %s." % url, title=title,
                   source="api.crossref.org", method="crossref", partial=True,
                   published=issued if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", issued) else "",
                   warnings=[PARTIAL_NOTE])


def _openalex_abstract(index):
    if not index:
        return ""
    words = sorted((position, word) for word, places in index.items() for position in places)
    return " ".join(word for _, word in words)


def read_researchgate(url):
    if _host(url).removeprefix("www.") != "researchgate.net":
        return None
    match = _RG.match(urlparse(url).path)
    if not match:
        return None
    wanted = unquote(match.group(1)).replace("_", " ").strip()
    response = _get("https://api.openalex.org/works",
                    params={"filter": "title.search:" + wanted, "per-page": 5}, timeout=12)
    if response.status_code != 200:
        raise Unavailable("openalex_http_%d" % response.status_code)
    def norm(value):
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    work = next((w for w in response.json().get("results") or []
                 if norm(w.get("display_name")) == norm(wanted)), None)
    if not work:
        raise Unavailable("openalex_no_exact_title")
    authors = ", ".join((a.get("author") or {}).get("display_name", "")
                        for a in (work.get("authorships") or [])[:20])
    oa = (work.get("best_oa_location") or {}).get("landing_page_url") or ""
    lines = ["# " + work.get("display_name", ""), "Authors: " + authors,
             "Published: %s" % work.get("publication_date", ""),
             "DOI: %s" % (work.get("doi") or "none")]
    if oa:
        lines.append("Open-access copy: " + oa)
    lines += ["", "Abstract:", _openalex_abstract(work.get("abstract_inverted_index"))
              or "(no abstract in OpenAlex)"]
    return _result("\n".join(lines) + "\n\nSource: OpenAlex record for %s." % url,
                   title=work.get("display_name", ""), source="api.openalex.org",
                   method="openalex", partial=True, published=work.get("publication_date", ""),
                   warnings=[PARTIAL_NOTE])


# Looked up by name at call time, so the table is the single place to read.
READERS = (("stackexchange", "read_stackexchange"), ("pubmed", "read_pubmed"),
           ("github", "read_github"), ("npm", "read_npm"),
           ("crossref", "read_sciencedirect"), ("openalex", "read_researchgate"))


def reader_for(url: str):
    """(name, callable returning (payload, reason, final_url)) or None."""
    host = _host(url)
    if not host:
        return None
    for name, function in READERS:
        def run(function=function, name=name):
            try:
                payload = globals()[function](url)
            except Unavailable as exc:
                return {}, "api_%s_unavailable:%s" % (name, exc), url
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                return {}, "api_%s_failed:%s" % (name, type(exc).__name__), url
            return (payload or {}), ("" if payload else "api_%s_not_applicable" % name), url
        if _applies(name, url):
            return name, run
    return None


_APPLIES = {
    "stackexchange": lambda url: bool(_se_site(_host(url)) and _SE_PATH.match(urlparse(url).path)),
    "pubmed": lambda url: (_host(url) == "pubmed.ncbi.nlm.nih.gov"
                           and bool(_PUBMED.match(urlparse(url).path))),
    "github": lambda url: _host(url) in {"github.com", "www.github.com"} and _github_shape(url),
    "npm": lambda url: (_host(url).removeprefix("www.") == "npmjs.com"
                        and bool(_NPM.match(urlparse(url).path))),
    "crossref": lambda url: (_host(url).removeprefix("www.") == "sciencedirect.com"
                             and bool(_PII.search(urlparse(url).path))),
    "openalex": lambda url: (_host(url).removeprefix("www.") == "researchgate.net"
                             and bool(_RG.match(urlparse(url).path))),
}


def _applies(name, url):
    return _APPLIES[name](url)


def _github_shape(url):
    segments = [part for part in urlparse(url).path.split("/") if part]
    if len(segments) < 2 or segments[0].lower() in _GH_RESERVED:
        return False
    return len(segments) == 2 or (len(segments) >= 5 and segments[2] == "blob"
                                  and bool(_GH_TEXT.search(segments[-1])))


# Site-specific advice when a read fails: the agent's better next step.
ADVICE = (
    ("google.com", "/search", "Google refuses automated searches here; use the search tool "
                              "instead."),
    ("scholar.google.com", "/", "Google Scholar refuses automated reads; use the search tool "
                                "with profile=academic."),
)


def advice(url: str) -> str:
    host, path = _host(url).removeprefix("www."), urlparse(url).path or "/"
    for site, prefix, text in ADVICE:
        if host == site and path.startswith(prefix):
            return text
    return ""


def describe() -> dict:
    return {"pins": dict(PINS), "readers": [name for name, _ in READERS],
            "advice": [site + prefix for site, prefix, _ in ADVICE]}

