"""Corpus search returns one page once, whatever address it was indexed under."""
from test_corpus_v2 import admit, finish
from test_corpus_v2 import store as store_fixture

store = store_fixture
REPORT = ("The regional allocation report records 7341 tonnes for the northern grid "
          "and explains each adjustment made during the audit year. ") * 40
OTHER = ("A separate survey of wind capacity lists turbine counts by county "
         "and the maintenance schedule agreed for the coming season. ") * 40


def test_mirror_passages_are_listed_under_the_kept_hit(store):
    admit(store, REPORT, url="https://example.org/report")
    finish(store)
    admit(store, REPORT, url="https://mirror.example/copy")
    finish(store)
    admit(store, OTHER, url="https://other.example/wind")
    finish(store)
    hits = store.search("allocation report tonnes", mode="lexical", limit=10, per_url=1)
    urls = [hit["url"] for hit in hits]
    assert urls.count("https://example.org/report") + urls.count("https://mirror.example/copy") == 1
    kept = next(hit for hit in hits if hit["url"] in {"https://example.org/report",
                                                      "https://mirror.example/copy"})
    assert kept["duplicates"][0]["reason"] == "same_text"
    assert "_print" not in kept


def test_one_page_under_two_addresses_counts_once_towards_per_url(store):
    admit(store, REPORT, url="https://www.example.org/report?utm_source=feed")
    finish(store)
    admit(store, REPORT.replace("7341", "7342"), url="https://example.org/report/")
    finish(store)
    hits = store.search("allocation report", mode="lexical", limit=10, per_url=1)
    assert len(hits) == 1
