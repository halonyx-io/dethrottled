"""Fresh-agent smoke tasks for the six-upgrade fixture. No tools are prescribed.

Fixture source and expected values are declared, not a general web accuracy benchmark.
"""

import argparse
import importlib.util
import json
import time
import uuid
from pathlib import Path

spec = importlib.util.spec_from_file_location("agent_harness", Path(__file__).with_name("run.py"))
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": "Bearer " + args.token_file.read_text().strip(),
               "Accept": "application/json, text/event-stream"}
    def rpc(method, params):
        return harness.request(args.endpoint, {"jsonrpc": "2.0", "id": uuid.uuid4().hex,
                               "method": method, "params": params}, headers)["result"]
    init = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "upgrade-cold-agent", "version": "1"}})
    tools = rpc("tools/list", {})["tools"]
    published = {"initialize": init, "tools": tools}
    (args.output / "published.json").write_text(json.dumps(published, indent=2))
    tasks = [
        ("site", args.fixture + "/site/", "Read all report pages linked beneath this source. "
         "Give ALPHA and BETA allocations and units, and disclose source coverage limits."),
        ("captions", args.fixture + "/captions.vtt", "What shipment size is stated, and what "
         "are the start and end times in seconds of the supporting caption?"),
        ("selectors", args.fixture + "/site/a", "Give the exact sentence stating the ALPHA "
         "allocation and its precise character start/end offsets in the retained source, "
         "together with the document version hash."),
    ]
    protocol = {"model": args.model, "temperature": 0, "max_turns": 12, "tasks": tasks,
                "instructions": "Normal published MCP policy and tool schemas only.",
                "expected": {"ALPHA": "7341 crates", "BETA": "291 tonnes",
                             "caption_start": 5.0, "caption_end": 7.5},
                "limit": "Three synthetic tasks, one run each, no baseline comparison."}
    (args.output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    summaries = []
    for name, source, task in tasks:
        messages = [{"role": "system", "content": harness.COMMON + init["instructions"]},
                    {"role": "user", "content": f"Source: {source}\n{task}"}]
        events, answer, error = [], "", None
        started = time.monotonic()
        try:
            for _ in range(12):
                response = harness.request(args.ollama + "/api/chat", {
                    "model": args.model, "messages": messages, "stream": False,
                    "options": {"temperature": 0}, "tools": [{"type": "function",
                    "function": {"name": t["name"], "description": t.get("description", ""),
                                 "parameters": t["inputSchema"]}} for t in tools]})
                message = response["message"]
                message.pop("thinking", None)
                messages.append(message)
                for call in message.get("tool_calls", []):
                    result = rpc("tools/call", {"name": call["function"]["name"],
                                 "arguments": call["function"]["arguments"]})
                    events.append({"call": call, "result": result})
                    text, _images = harness.tool_message(result)
                    reply = {"role": "tool", "tool_name": call["function"]["name"],
                             "content": text}
                    if call.get("id"):
                        reply["tool_call_id"] = call["id"]
                    messages.append(reply)
                if not message.get("tool_calls"):
                    answer = message.get("content", "")
                    break
            if not answer:
                error = "turn_budget_exhausted"
        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)[:300]
        record = {"case": name, "messages": messages, "events": events, "answer": answer,
                  "error": error, "elapsed_s": round(time.monotonic() - started, 3)}
        (args.output / (name + ".json")).write_text(json.dumps(record, indent=2))
        summaries.append({k: v for k, v in record.items() if k not in {"messages", "events"}})
        (args.output / "summary.json").write_text(json.dumps(summaries, indent=2))
        print(name, "completed" if answer else error, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="deepseek-v4.1-flash:cloud")
    main(parser.parse_args())
