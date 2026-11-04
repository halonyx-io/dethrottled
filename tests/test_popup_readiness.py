"""Test popup readiness independently of a browser installation."""

import ast
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def ready_tab():
    tree = ast.parse(
        (Path(__file__).resolve().parents[1] / "browser-search/service.py").read_text()
    )
    node = next(
        x for x in tree.body if isinstance(x, ast.AsyncFunctionDef) and x.name == "_ready_tab"
    )
    namespace = dict(
        asyncio=asyncio,
        time=time,
        _host_allowed=lambda url, hosts: url.startswith("http://allowed/"),
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<worker>", "exec"), namespace)
    return namespace["_ready_tab"]


def test_waits_for_popup_creation_and_initial_navigation():
    class Context:
        reads = 0

        @property
        def pages(self):
            self.reads += 1
            return (
                []
                if self.reads == 1
                else [
                    SimpleNamespace(
                        url="about:blank" if self.reads == 2 else "http://allowed/report"
                    )
                ]
            )

    result = asyncio.run(ready_tab()(Context(), 0, ["allowed"], 200))
    assert result.url == "http://allowed/report"


@pytest.mark.parametrize("url", ["http://forbidden/report", "about:blank"])
def test_scope_or_timeout_stays_a_failure(url):
    with pytest.raises(ValueError, match="outside_allowed_hosts"):
        asyncio.run(
            ready_tab()(SimpleNamespace(pages=[SimpleNamespace(url=url)]), 0, ["allowed"], 1)
        )
