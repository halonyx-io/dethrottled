"""Budgeted shared matrices with bounded construction and a streaming fallback."""

from __future__ import annotations

import threading

from .corpus_config import integer

# Serialize matrix construction/scans, not query inference or DB writes. This
# prevents concurrent readers retaining old matrices across cache replacement.
SCAN_LOCK = threading.Lock()


def candidates(store, model, q, threshold, depth, eligible, per_url):
    import numpy as np

    with SCAN_LOCK:
        with store.lock:
            generation = store.db.execute(
                "SELECT value FROM metadata WHERE key='generation'"
            ).fetchone()[0]
            if generation != store.matrix_generation:
                store.matrices.clear()
                store.matrix_generation = generation
            held = store.matrices.get(model)
            if held is None:
                total = store.db.execute(
                    "SELECT count(*) FROM embeddings e JOIN passages p ON p.id=e.passage_id "
                    "JOIN sources s ON s.id=p.source_id WHERE e.model=? AND s.active=1 "
                    "AND e.dimensions=? AND e.revision=?",
                    (model, len(q), store.revisions[model]),
                ).fetchone()[0]
                budget = integer("VECTOR_MIB", 256) * 1024**2
                # Matrix + identifiers + scores/order + bounded decode scratch.
                required = total * (len(q) * 4 + 24)
                block_rows = max(1, min(1024, budget // max(len(q) * 4 * 4, 1)))
                scratch = block_rows * len(q) * 4 * 3
                while (
                    store.matrices
                    and sum(value[0].nbytes + value[1].nbytes for value in store.matrices.values())
                    + required
                    + scratch
                    > budget
                ):
                    store.matrices.pop(next(iter(store.matrices)))
                cursor = store.db.execute(
                    "SELECT e.passage_id,e.vector,s.url FROM embeddings e "
                    "JOIN passages p ON p.id=e.passage_id "
                    "JOIN sources s ON s.id=p.source_id "
                    "WHERE e.model=? AND s.active=1 AND e.dimensions=? AND e.revision=?",
                    (model, len(q), store.revisions[model]),
                )
            else:
                cursor = None
        if held is None and required + scratch <= budget:
            vectors = np.empty((total, len(q)), dtype="float32")
            identifiers = np.empty(total, dtype="int64")
            urls, offset = [], 0
            try:
                while True:
                    with store.lock:
                        block = cursor.fetchmany(block_rows)
                    if not block:
                        break
                    stop = offset + len(block)
                    if stop > total:
                        # Concurrent promotion changed this connection's view.
                        # Retry on the next query instead of publishing a mixed cache.
                        raise RuntimeError("corpus changed during matrix construction")
                    vectors[offset:stop] = np.frombuffer(
                        b"".join(row["vector"] for row in block), dtype="float32"
                    ).reshape(len(block), -1)
                    identifiers[offset:stop] = [row["passage_id"] for row in block]
                    urls.extend(row["url"] for row in block)
                    offset = stop
            finally:
                cursor.close()
            if offset != total:
                raise RuntimeError("corpus changed during matrix construction")
            held = (vectors, identifiers, urls)
            with store.lock:
                store.matrices[model] = held
        if held is not None:
            vectors, identifiers, urls = held
            scores = vectors @ q
            out, seen = [], {}
            for index in np.argsort(-scores, kind="stable"):
                if scores[index] < threshold:
                    break
                url = urls[index]
                if eligible(url) and seen.get(url, 0) < per_url:
                    seen[url] = seen.get(url, 0) + 1
                    out.append((int(identifiers[index]), float(scores[index]), model))
                    if len(out) >= depth:
                        break
            return out
        # Small memory budgets and oversized corpora can still be queried.
        import heapq

        heaps = {}
        try:
            while True:
                with store.lock:
                    block = cursor.fetchmany(block_rows)
                if not block:
                    break
                vectors = np.frombuffer(
                    b"".join(row["vector"] for row in block), dtype="float32"
                ).reshape(len(block), -1)
                scores = vectors @ q
                for row, score in zip(block, scores):
                    if score < threshold or not eligible(row["url"]):
                        continue
                    heap = heaps.setdefault(row["url"], [])
                    candidate = (float(score), row["passage_id"])
                    if len(heap) < per_url:
                        heapq.heappush(heap, candidate)
                    elif candidate > heap[0]:
                        heapq.heapreplace(heap, candidate)
        finally:
            cursor.close()
        return [(identifier, score, model) for score, identifier in heapq.nlargest(depth,
                (item for heap in heaps.values() for item in heap))]
