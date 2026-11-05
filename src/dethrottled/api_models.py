"""Request schemas and validation for the HTTP API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .workflow import RESEARCH_SOURCE_LIMIT


class SearchBody(BaseModel):
    # Unknown fields are rejected rather than ignored, so a caller that mistypes
    # one hears about it instead of silently getting the default.
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    # The contract's name for result count. num_results and max_items remain
    # accepted for callers already written against them; limit wins.
    limit: int | None = Field(default=None, ge=1, le=15)
    num_results: int = Field(default=15, ge=1, le=15)
    max_items: int | None = Field(default=None, ge=1, le=15)
    # Default search combines DDG with small Yahoo/Yandex supplements.
    # News feeds are selected through an explicit news profile/category.
    categories: Literal["", "news", "academic"] = ""
    # SearXNG uses this hint. Direct web engines are
    # English-centric and do not take it, so it biases rather than constrains.
    language: str = ""
    engines: str = ""

    @field_validator("engines")
    @classmethod
    def validate_sources(cls, value):
        allowed = {"auto", "web", "news", "mwmbl", "crossref", "openalex", "arxiv",
                   "yahoo", "yandex",
                   "exa", "tavily", "parallel"}
        if any(x.strip() not in allowed for x in value.split(",") if x.strip()):
            raise ValueError("supported sources: " + ", ".join(sorted(allowed)))
        return ",".join("web" if x.strip() == "auto" else x.strip()
                        for x in value.split(",") if x.strip())

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, value):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()

    # Honoured: bypasses the search cache for this call. It was accepted and
    # ignored until an external benchmark set it, measured this engine's cache
    # against another engine doing live work, and published the wrong
    # conclusion. Accepting a field costs nothing right up until someone
    # believes it.
    fresh: bool = False
    cache_mode: Literal["use", "refresh", "bypass"] = "use"
    max_age: float | None = Field(default=None, ge=0, le=1814400)
    profile: Literal["fast", "web", "balanced", "thorough", "news", "academic"] = "web"

    # Source order is the measured default; BM25 remains opt-in.
    rank: bool = False
    ranking: Literal["source", "bm25", "fusion"] = "source"
    prefer_domains: list[str] = Field(default_factory=list, max_length=10)
    # Accept explicit false for existing callers. Reject true instead of
    # claiming success when the removed model cannot run.
    rerank: bool = False

    @field_validator("rerank")
    @classmethod
    def reranker_is_retired(cls, value: bool) -> bool:
        if value:
            raise ValueError("Dethrottled no longer provides a reranker")
        return value
    # How many already-fetched corpus passages to merge into the pool before
    # ranking. 0 disables it. These cost no fetch, so they are cheaper than the
    # web rows they compete with, not merely additional.
    corpus: int = Field(default=0, ge=0, le=20)
    # 0.0 = pure relevance, 1.0 = freshness dominates. Bounded and
    # multiplicative: it may reorder relevant results and may never promote an
    # irrelevant one.
    recency: float = Field(default=0.0, ge=0, le=1)


class FetchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urls: list[str] = Field(min_length=1, max_length=10)
    # What the ladder is ALLOWED to do, not what it must do. "never" keeps it
    # on the cheap local tiers for callers to whom latency matters more than
    # coverage.
    # auto    escalate to the renderer only when cheaper tiers fail (default)
    # always  try the renderer FIRST, for a page you know needs a browser
    # never   stay on the cheap local tiers
    # auto | always | never. A bool is also accepted and mapped, because
    # callers were written against one -- and because typing this field
    # differently on two engines is what returned 422 on every fetch through a
    # bridge for a day. The enum is canonical; True means always, False auto.
    render: Literal["auto", "always", "never"] | bool = "auto"
    # text   article prose (default)
    # links  prose with anchors kept as markdown, for link discovery
    # html   the source, for callers doing their own parsing
    #
    # Replaces the raw/links booleans, which could contradict each other and
    # left a caller no way to say "either one" without knowing which won.
    format: Literal["text", "links", "html"] = "text"
    # The prose is the point; `raw` is for callers doing their own parsing, and
    # is the only reason this is a distinct verb rather than a rename. Kept
    # because callers send it; `format` wins when both appear.
    raw: bool = False
    # Keep the anchors, rendered as markdown links. For callers doing link
    # discovery rather than reading: an index page's VALUE is its outbound
    # links, and the article extractors throw those away by design.
    links: bool = False
    # 8000, not 3500: 3,500 characters is about 550 words, and a news article
    # is 500 to 800 -- this endpoint was truncating typical articles. Not
    # 10,000, because past roughly eight thousand most sites are into
    # related-articles and footer.
    max_chars: int = Field(default=8000, ge=1, le=1000000)
    fresh: bool = False
    cache_mode: Literal["use", "refresh", "bypass"] = "use"
    max_age: float | None = Field(default=None, ge=0, le=1814400)
    wait_for: str = Field(default="", max_length=500)
    render_delay: float = Field(default=0.5, ge=0, le=5)
    headed_fallback: bool = False
    public_only: bool = False
    focus: str = Field(default="", max_length=1000)
    response_format: Literal["detailed", "concise"] = "detailed"
    evidence_namespace: str = Field(default="local", max_length=100)
    ocr_language: str = Field(default="", pattern=r"^[a-z_]*(?:\+[a-z_]+)*$", max_length=100)
    document_mode: Literal["auto", "native", "layout"] = "auto"
    ocr_mode: Literal["auto", "always", "never"] = "auto"
    row_start: int = Field(default=1, ge=1, le=1048576)
    row_end: int | None = Field(default=None, ge=1, le=1048576)
    sheet: str = Field(default="", max_length=200)
    max_cell_chars: int | None = Field(default=None, ge=1, le=1000000)
    page_start: int = Field(default=1, ge=1, le=100000)
    page_end: int | None = Field(default=None, ge=1, le=100000)
    recovery: Literal["auto", "manual"] = "auto"
    profile: Literal["fast", "balanced", "thorough"] = "balanced"


    @model_validator(mode="after")
    def read_constraints(self):
        if self.page_end is not None and (self.page_end < self.page_start
                                          or self.page_end - self.page_start >= 100):
            raise ValueError("page range must contain 1 to 100 pages")
        if self.row_end is not None and (self.row_end < self.row_start
                                         or self.row_end - self.row_start >= 2000):
            raise ValueError("row range must contain 1 to 2000 rows")
        if self.focus and (self.format != "text" or self.raw or self.links):
            raise ValueError("focus requires text format")
        if self.wait_for and (self.render == "never" or self.profile == "fast"):
            raise ValueError("wait_for requires rendering")
        return self


class SearchFetchBody(SearchBody):
    document_mode: Literal["auto", "native", "layout"] = "auto"
    ocr_mode: Literal["auto", "always", "never"] = "auto"
    ocr_language: str = Field(default="", pattern=r"^[a-z_]*(?:\+[a-z_]+)*$", max_length=100)
    evidence_namespace: str = Field(default="local", max_length=100)
    # auto | always | never. A bool is also accepted and mapped, because
    # callers were written against one -- and because typing this field
    # differently on two engines is what returned 422 on every fetch through a
    # bridge for a day. The enum is canonical; True means always, False auto.
    render: Literal["auto", "always", "never"] | bool = "auto"
    raw: bool = False
    # 3000. Leaner than /extract on purpose: this path multiplies by the number
    # of results, and it is the ranking path, where measurement says less text
    # ranks better -- titles plus 240 characters beat 3,000 characters of body.
    # 3000 is the measured sweet spot for the ranking path.
    max_chars: int = Field(default=3000, ge=1, le=1000000)


class ResearchBody(BaseModel):
    """A question and optional facets; returns sources, not a model answer."""
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=500)
    queries: list[str] = Field(default_factory=list, max_length=10)
    max_sources: int = Field(default=10, ge=1, le=RESEARCH_SOURCE_LIMIT)
    max_chars: int = Field(default=12000, ge=500, le=120000)
    language: str = ""
    fresh: bool = False
    follow_assets: bool = True
    engines: str = ""
    profile: Literal["web", "balanced", "thorough", "academic", "news"] = "web"
    categories: str = ""
    response_format: Literal["detailed", "concise"] = "detailed"
    evidence_namespace: str = Field(default="local", max_length=100)


    @field_validator("engines")
    @classmethod
    def validate_engines(cls, value):
        return SearchBody.validate_sources(value)


class DocumentReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=100)
    public_only: bool = False
    focus: str = Field(default="", max_length=1000)
    reparse: bool = False
    row_start: int = Field(default=1, ge=1, le=1048576)
    row_end: int | None = Field(default=None, ge=1, le=1048576)
    sheet: str = Field(default="", max_length=200)
    max_cell_chars: int | None = Field(default=None, ge=1, le=1000000)
    page_start: int = Field(default=1, ge=1, le=100000)
    page_end: int | None = Field(default=None, ge=1, le=100000)
    document_mode: Literal["auto", "native", "layout"] = "auto"
    ocr_mode: Literal["auto", "always", "never"] = "auto"
    ocr_language: str = Field(default="", pattern=r"^[a-z_]*(?:\+[a-z_]+)*$", max_length=100)
    offset: int = Field(default=0, ge=0)
    max_chars: int = Field(default=12000, ge=1, le=1000000)
    response_format: Literal["detailed", "concise"] = "detailed"
    evidence_namespace: str = Field(default="local", max_length=100)


    @model_validator(mode="after")
    def bounded_ranges(self):
        if self.row_end is not None and (self.row_end < self.row_start
                                        or self.row_end - self.row_start >= 2000):
            raise ValueError("row range must contain 1 to 2000 rows")
        if self.page_end is not None and (self.page_end < self.page_start
                                         or self.page_end - self.page_start >= 100):
            raise ValueError("page range must contain 1 to 100 pages")
        return self


class DocumentImageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_only: bool = False
    document_id: str = Field(min_length=1, max_length=100)
    page: int = Field(default=1, ge=1)
    max_dimension: int = Field(default=2400, ge=512, le=6000)
    crop: tuple[int, int, int, int] | None = None
    evidence_namespace: str = Field(default="local", max_length=100)


class FetchJobBody(FetchBody):
    operation_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._-]*$")


class JobReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=100)
    cursor: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=10)
    evidence_namespace: str = Field(default="local", max_length=100)


class StructureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=100)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=100)
    focus: str = Field(default="", max_length=1000)
    evidence_namespace: str = Field(default="local", max_length=100)


class SiteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    urls: list[str] = Field(min_length=1, max_length=10)
    max_pages: int = Field(default=10, ge=1, le=50)
    max_depth: int = Field(default=2, ge=0, le=5)
    path_prefix: str = Field(default="/", max_length=1000, pattern=r"^/")
    render: Literal["auto", "always", "never"] = "auto"
    public_only: bool = False
    evidence_namespace: str = Field(default="local", max_length=100)

    @model_validator(mode="after")
    def site_scope(self):
        from urllib.parse import urlsplit

        from .site import canonical
        self.urls = [canonical(u) for u in self.urls]
        origins = {(urlsplit(u).scheme, urlsplit(u).netloc) for u in self.urls}
        if len(origins) != 1 or any(
            not urlsplit(u).path.startswith(self.path_prefix) for u in self.urls
        ):
            raise ValueError("seeds must share one origin and match path_prefix")
        return self


class DriveStep(BaseModel):
    """One action for the browser to take. `action` selects which fields matter."""
    model_config = ConfigDict(extra="forbid")

    # goto      navigate to `url`
    # click     click `selector`
    # fill      set `value` and emit input/change events at `selector`
    # press     press `value` (a key) at `selector` (defaults to the page body)
    # wait      sleep `ms`
    # wait_for  wait for `selector` to appear, up to `ms`
    # text      read the text of `selector` (or the whole body)
    action: str = Field(min_length=1, max_length=20)
    frame: str = Field(default="", max_length=1000,
                       description="CSS selector for an allowed iframe")
    selector: str = Field(default="", max_length=1000)
    value: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=2048)
    ms: int = Field(default=1000, ge=0, le=30000)
    delay_ms: int = Field(default=0, ge=0, le=1000)
    name: str = Field(default="", max_length=200)
    index: int = Field(default=0, ge=0, le=500)
    limit: int = Field(default=10, ge=1, le=10)
    max_chars: int | None = Field(default=None, ge=1, le=1000000)


class DriveBody(BaseModel):
    """A scripted sequence for the private browser worker to perform.

    The manipulation twin of FetchBody: /fetch READS a page, /drive OPERATES
    one. Steps run in order and the run stops at the first failure -- an agent
    that has to click through an app gets asked to, and told exactly which step
    failed and why, rather than being handed a page and left to guess.
    """
    model_config = ConfigDict(extra="forbid")

    url: str = Field(default="", max_length=2048)
    steps: list[DriveStep] = Field(default_factory=list, max_length=40)
    # Whole-run budget. The worker also caps each step; this is the backstop
    # that stops one slow selector holding a browser forever.
    timeout_ms: int = Field(default=45000, ge=1000, le=180000)
    session: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9._-]*$")
    operation_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9._-]*$")
    close_session: bool = False
    allowed_hosts: list[str] = Field(default_factory=list, max_length=32)
    public_only: bool = False
    canaries: list[str] = Field(default_factory=list, max_length=20)
    include_events: bool = True
    screenshot: bool | Literal["never", "failure", "canary", "always"] = "failure"
    screenshot_full_page: bool = False
    evidence_namespace: str = Field(default="local", max_length=100)
    ocr_language: str = Field(default="", pattern=r"^[a-z_]*(?:\+[a-z_]+)*$", max_length=100)

    @model_validator(mode="after")
    def _need_something(self):
        # Reject an empty request here rather than round-tripping to the worker
        # to be told the same thing. Same refusal, one less hop, and the caller
        # gets a 422 from the API it is actually talking to.
        if not self.url and not self.steps and not (self.session and self.close_session):
            raise ValueError("nothing to do: supply url and/or steps")
        return self
