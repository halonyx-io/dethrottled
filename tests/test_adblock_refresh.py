"""Unchanged lists reuse compiled rules without losing durable timestamps."""

import json

from test_adblock import Reply, body

from dethrottled import adblock


def test_readers_do_not_parse_unchanged_304_snapshots(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "1")
    writer = adblock.Filter(tmp_path)
    writer.update(lambda *a, **k: Reply(body(), headers={"ETag": "v1"}), now=100)
    reader = adblock.Filter(tmp_path, reader=True)
    reader.load()
    original = reader.rules
    calls = []
    parse = adblock.parse
    monkeypatch.setattr(adblock, "parse", lambda data: (calls.append(1), parse(data))[1])
    writer.update(lambda *a, **k: Reply(code=304), now=200)
    reader.load()
    assert reader.rules is original
    assert calls == []
    assert reader.last_check == 200 and reader.metadata["updated_at"] == 100
    restarted = adblock.Filter(tmp_path, reader=True)
    restarted.load()
    assert restarted.match("https://ads.example") and restarted.last_check == 200
    assert calls == [1]


def test_identical_200_reuses_rules_and_preserves_refresh_timestamps(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "1")
    writer = adblock.Filter(tmp_path)
    writer.update(lambda *a, **k: Reply(body()), now=100)
    original = writer.rules
    monkeypatch.setattr(
        adblock,
        "parse",
        lambda _: (_ for _ in ()).throw(AssertionError("unchanged contents parsed again")),
    )
    writer.update(lambda *a, **k: Reply(body(), headers={"ETag": "new"}), now=200)
    assert writer.error is None and writer.rules is original
    assert writer.metadata["updated_at"] == 200 and writer.last_check == 200
    assert writer.metadata["etag"] == "new"


def test_same_claimed_digest_cannot_hide_corrupted_body(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "1")
    writer = adblock.Filter(tmp_path)
    writer.update(lambda *a, **k: Reply(body()), now=100)
    original = writer.rules
    data = json.loads(writer.path.read_text())
    data["body"] += "corrupt"
    adblock._atomic(writer.path, data)
    writer.load()
    assert writer.rules is original and writer.error.startswith("cache_invalid:")


def test_changed_contents_still_recompile_once_for_each_reader(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "1")
    writer = adblock.Filter(tmp_path)
    writer.update(lambda *a, **k: Reply(body()), now=100)
    reader = adblock.Filter(tmp_path, reader=True)
    reader.load()
    old = reader.rules
    writer.update(lambda *a, **k: Reply(body("new.example")), now=200)
    reader.load()
    assert reader.rules is not old and reader.match("https://new.example")
    assert not reader.match("https://ads.example") and reader.metadata["updated_at"] == 200
    current = reader.rules
    reader.load()
    assert reader.rules is current


def test_304_cannot_activate_corrupted_cached_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "1")
    writer = adblock.Filter(tmp_path)
    writer.update(lambda *a, **k: Reply(body()), now=100)
    original = writer.rules
    data = json.loads(writer.path.read_text())
    data["sha256"] = "0" * 64
    adblock._atomic(writer.path, data)
    writer.update(lambda *a, **k: Reply(code=304), now=200)
    assert writer.rules is original and writer.error.startswith("update_failed:")
    assert writer.metadata["updated_at"] == 100
