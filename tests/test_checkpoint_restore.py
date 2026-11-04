"""An incomplete IndexedDB restore must not silently become a usable session."""

import ast
import asyncio
from pathlib import Path

import pytest


def restore_function():
    path = Path(__file__).resolve().parents[1] / "browser-search/service.py"
    nodes = [
        n
        for n in ast.parse(path.read_text()).body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name in {"_indexeddb_state", "_restored_context"}
    ]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<worker>", "exec"), namespace)
    return namespace["_restored_context"]


STATE = {
    "origins": [
        {
            "origin": "https://example.com",
            "indexedDB": [
                {
                    "name": "auth",
                    "stores": [{"name": "tokens", "records": [{"key": 0, "value": False}]}],
                }
            ],
        }
    ]
}


class Context:
    closed = False

    def __init__(self, state):
        self.state = state

    async def storage_state(self, **options):
        assert options == {"indexed_db": True}
        return self.state

    async def close(self):
        self.closed = True


class Browser:
    def __init__(self, states):
        self.states = iter(states)
        self.contexts = []

    async def new_context(self, **options):
        assert options["storage_state"] == STATE
        context = Context(next(self.states))
        self.contexts.append(context)
        return context


def test_incomplete_restore_is_closed_and_retried_before_navigation():
    browser = Browser([{}, STATE])
    context, attempts = asyncio.run(restore_function()(browser, STATE))
    assert attempts == 2 and context is browser.contexts[1]
    assert browser.contexts[0].closed and not context.closed


def test_persistent_loss_fails_and_closes_every_context():
    browser = Browser([{}, {}, {}])
    with pytest.raises(ValueError, match="original_checkpoint_preserved"):
        asyncio.run(restore_function()(browser, STATE))
    assert all(c.closed for c in browser.contexts)
