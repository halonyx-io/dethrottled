import threading
import time

from dethrottled import server


def test_read_batch_overlaps_reads_with_four_per_request_and_keeps_order():
    active = peak = 0
    lock = threading.Lock()

    def read(index):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.06 if index % 2 else 0.03)
        with lock:
            active -= 1
        return index

    assert server._read_batch(list(range(9)), read) == list(range(9))
    assert 2 <= peak <= 4


def test_read_batch_empty():
    assert server._read_batch([], lambda item: item) == []


def test_cache_initializes_once_when_first_readers_arrive_together(monkeypatch):
    creations = []

    class FakeCache:
        def __init__(self, path):
            time.sleep(0.02)
            creations.append(path)

    monkeypatch.setattr(server, "_cache", None)
    monkeypatch.setattr(server, "Cache", FakeCache)
    caches = server._read_batch(list(range(4)), lambda _: server.cache())
    assert len(creations) == 1
    assert all(cache is caches[0] for cache in caches)
