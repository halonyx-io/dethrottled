"""Run in the REST adapter environment; no network or credentials needed."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import httpx

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/opt/dethrottled-access")


async def run():
    rest_spec = importlib.util.spec_from_file_location(
        "validation_rest", repo / "adapters/rest_gateway.py"
    )
    rest = importlib.util.module_from_spec(rest_spec)
    sys.modules[rest_spec.name] = rest
    rest_spec.loader.exec_module(rest)

    original_client = rest.httpx.AsyncClient

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def request(self, *a, **kw):
            return httpx.Response(
                429,
                json={"detail": {"reason": "research_busy"}},
                headers={"Retry-After": "7", "X-Dethrottled-Limiter": "research"},
            )

    rest.httpx.AsyncClient = lambda *a, **kw: FakeClient()
    try:
        response = await rest.upstream("POST", "/research", {})
        assert response.status_code == 429 and response.headers["Retry-After"] == "7"
        assert response.headers["X-Dethrottled-Limiter"] == "research"
    finally:
        rest.httpx.AsyncClient = original_client
    print(
        json.dumps(
            {
                "rest_retry_headers_preserved": True,
                "research_retry_after": response.headers["Retry-After"],
                "limiter": response.headers["X-Dethrottled-Limiter"],
            }
        )
    )


asyncio.run(run())
