#!/usr/bin/env python3
"""Check client-playbook route/tool/action/field coverage without calling providers."""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit(root):
    sys.path.insert(0, str(root / "src"))
    from dethrottled import server

    text = (root / "docs/AGENT-PLAYBOOK.md").read_text()
    routes = {
        (method.upper(), path)
        for path, methods in server.app.openapi()["paths"].items()
        for method in methods
    }
    listed = set(re.findall(r"`(GET|POST) ([^`]+)`", text))
    errors = []
    if routes != listed:
        errors.append(
            "Playbook routes: missing="
            + repr(sorted(routes - listed))
            + ", unknown="
            + repr(sorted(listed - routes))
        )
    tree = ast.parse((root / "adapters/mcp_server.py").read_text())
    tools = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name)
            and d.func.value.id == "mcp"
            and d.func.attr == "tool"
            for d in node.decorator_list
        )
    }
    for name in sorted(tools):
        if "`" + name + "`" not in text:
            errors.append("Playbook omits MCP tool: " + name)
    browser = ast.parse((root / "browser-search/service.py").read_text())
    actions = next(
        ast.literal_eval(node.value)
        for node in browser.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "DRIVE_ACTIONS" for target in node.targets
        )
    )
    for name in actions:
        if "`" + name + "`" not in text:
            errors.append("Playbook omits browser action: " + name)
    for model in (server.SearchBody, server.FetchBody, server.DriveBody):
        for field in model.model_fields:
            if not re.search(r"\b" + re.escape(field) + r"\b", text):
                errors.append("Playbook omits request field: " + model.__name__ + "." + field)
    for field in server.app.openapi()["paths"]["/corpus/search"]["get"]["parameters"]:
        if not re.search(r"\b" + re.escape(field["name"]) + r"\b", text):
            errors.append("Playbook omits corpus control: " + field["name"])
    return {
        "routes": len(routes),
        "mcp_tools": len(tools),
        "browser_actions": len(actions),
        "errors": errors,
        "scope": "Name/route coverage, not prose-semantic validation",
    }


def main():
    with tempfile.TemporaryDirectory(prefix="dethrottled-agent-docs-") as data:
        os.environ["DETHROTTLED_DATA_DIR"] = data
        result = audit(ROOT)
    print(json.dumps(result, indent=2))
    return bool(result["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
