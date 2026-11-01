import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from dethrottled import server

server.index_fetched = lambda *a: 0


def rank(*a, **kw):
    time.sleep(0.4)
    return [], {"ok": True}, []


server._ranked = rank
client = TestClient(server.app)
rows = []
for n in [1, 2, 3, 6]:

    def read(i):
        response = client.post(
            "/research", json={"question": "Known fixture allocation", "max_sources": 1}
        )
        return {
            "status": response.status_code,
            "detail": response.json().get("detail"),
            "retry_after": response.headers.get("Retry-After"),
            "limiter_header": response.headers.get("X-Dethrottled-Limiter"),
        }

    with ThreadPoolExecutor(n) as pool:
        results = list(pool.map(read, range(n)))
    rows.append(
        {
            "requests": n,
            "results": results,
            "renderer_admission": server.fetcher._RENDER_QUEUE.stats(),
        }
    )
for row in rows:
    print(os.environ["LABEL"], row, flush=True)
Path("/evidence/" + os.environ["LABEL"] + "-research.json").write_text(json.dumps(rows, indent=2))
