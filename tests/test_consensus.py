"""Intent expansion and cross-variant consensus are opt-in and explainable."""

from dethrottled import consensus


def test_intent_patterns_are_conservative():
    assert consensus.intent("rust vs go performance") == "comparison"
    assert consensus.intent("how to install uv") == "howto"
    assert consensus.intent("transformer paper benchmark") == "research"
    assert consensus.intent("python asyncio code example") == "code"
    assert consensus.intent("python sqlite3 documentation") == "reference"
    assert consensus.intent("latest release announcement") == "news"
    assert consensus.intent("something ordinary") == "general"


def test_expand_queries_keeps_the_original_and_adds_one_variant():
    variants = consensus.expand_queries("rust vs go performance")
    assert variants[0] == "rust vs go performance"
    assert len(variants) == 2 and "comparison" in variants[1]
    long_query = " ".join("word%d" % n for n in range(16))
    assert consensus.expand_queries(long_query) == [long_query]


def test_merge_variants_deduplicates_and_counts_consensus():
    first = [{"url": "https://www.example.com/a", "title": "A", "engine": "web-ddg",
              "discovery": [{"provider": "web", "query": "q"}]}]
    second = [{"url": "https://example.com/a", "title": "A", "engine": "web-bing",
               "discovery": [{"provider": "bing", "query": "q variant"}]}]
    merged = consensus.merge_variants([first, second])
    assert len(merged) == 1
    assert merged[0]["engines_consensus"] == 2
    assert merged[0]["query_variants"] == [0, 1]
    assert merged[0]["consensus_score"] == 2.5
