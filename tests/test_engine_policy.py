"""Per-profile engine order with evidence-based demotion (engine_policy.py)."""
import pytest

from dethrottled import engine_policy as ep


@pytest.fixture(autouse=True)
def enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(ep, "ENABLED", True)
    monkeypatch.setattr(ep._paths, "data_dir", lambda: tmp_path)
    ep.reset()
    yield
    ep.reset()


def rows(engine, count, dated):
    return [{"engine": engine, "url": "https://%s.example/a/%d" % (engine.replace(" ", ""), i),
             **({"publishedDate": "2026-11-14T01:00:00Z"} if dated else {})}
            for i in range(count)]


def test_default_order_interleaves_engines():
    ordered, meta = ep.order("news", rows("bing news", 2, False) + rows("duckduckgo news", 2, True))
    assert [r["engine"] for r in ordered] == [
        "duckduckgo news", "bing news", "duckduckgo news", "bing news"]
    assert meta["demoted"] == []


def test_an_engine_is_demoted_only_after_enough_evidence():
    for count in range(1, ep.MIN_OBSERVATIONS + 1):
        ep.observe("news", rows("duckduckgo news", 5, True) + rows("brave news", 5, False))
        assert ("brave-news" in ep.demoted("news")) is (count >= ep.MIN_OBSERVATIONS)


def test_a_demoted_engine_is_moved_back_never_removed():
    for _ in range(ep.MIN_OBSERVATIONS):
        ep.observe("news", rows("duckduckgo news", 5, True) + rows("bing news", 5, False))
    ordered, meta = ep.order("news", rows("bing news", 2, False) + rows("duckduckgo news", 2, True))
    assert [r["engine"] for r in ordered] == [
        "duckduckgo news", "duckduckgo news", "bing news", "bing news"]
    assert meta["demoted"] == ["bing-news"]


def test_a_demoted_engine_recovers_when_its_results_improve():
    for _ in range(ep.MIN_OBSERVATIONS):
        ep.observe("news", rows("duckduckgo news", 5, True) + rows("bing news", 5, False))
    for _ in range(30):
        ep.observe("news", rows("duckduckgo news", 5, True) + rows("bing news", 5, True))
    assert ep.demoted("news") == []


def test_profiles_without_a_value_rule_are_not_scored():
    ep.observe("web", rows("yandex", 5, False))
    assert ep.stats()["profiles"] == {}


def test_the_record_holds_engine_names_and_numbers_only(tmp_path):
    ep.observe("news", [{"engine": "duckduckgo news", "url": "https://secret.example/story",
                         "title": "Private query words"}])
    ep.flush()
    text = (tmp_path / "engine-policy.json").read_text()
    assert "secret" not in text and "Private" not in text and "duckduckgo-news" in text
