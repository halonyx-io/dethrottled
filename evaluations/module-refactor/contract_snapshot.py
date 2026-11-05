import json

from pydantic import ValidationError

from dethrottled import server

names = [
    "SearchBody",
    "FetchBody",
    "SearchFetchBody",
    "ResearchBody",
    "DocumentReadBody",
    "DocumentImageBody",
    "FetchJobBody",
    "JobReadBody",
    "StructureBody",
    "SiteBody",
    "DriveStep",
    "DriveBody",
]
cases = {
    "SearchBody": [
        {"query": "  test  "},
        {"query": " "},
        {"query": "test", "limit": 16},
        {"query": "test", "engines": "auto,yahoo"},
        {"query": "test", "rerank": True},
        {"query": "test", "unknown": True},
    ],
    "FetchBody": [
        {"urls": ["https://example.com"]},
        {"urls": ["https://example.com"], "page_start": 3, "page_end": 2},
        {"urls": ["https://example.com"], "focus": "x", "raw": True},
        {"urls": ["https://example.com"], "wait_for": "main", "profile": "fast"},
    ],
    "SearchFetchBody": [{"query": "test"}, {"query": "test", "max_chars": 0}],
    "ResearchBody": [{"question": "test"}, {"question": "test", "engines": "unsupported"}],
    "DocumentReadBody": [{"document_id": "x"}, {"document_id": "x", "row_start": 9, "row_end": 8}],
    "DocumentImageBody": [{"document_id": "x"}, {"document_id": "x", "max_dimension": 2}],
    "FetchJobBody": [
        {"urls": ["https://example.com"]},
        {"urls": ["https://example.com"], "operation_id": "bad/"},
    ],
    "JobReadBody": [{"job_id": "x"}, {"job_id": "x", "limit": 11}],
    "StructureBody": [{"document_id": "x"}, {"document_id": "x", "offset": -1}],
    "SiteBody": [
        {"urls": ["https://example.com/a"]},
        {"urls": ["https://example.com/a", "https://other.example/b"]},
    ],
    "DriveStep": [{"action": "text"}, {"action": "wait", "ms": 30001}],
    "DriveBody": [
        {"url": "https://example.com"},
        {},
        {"url": "https://example.com", "timeout_ms": 1},
    ],
}
out = {"openapi": server.app.openapi(), "models": {}, "validation": {}}
for name in names:
    cls = getattr(server, name)
    out["models"][name] = cls.model_json_schema()
    outcomes = []
    for case in cases[name]:
        try:
            outcomes.append({"accepted": cls.model_validate(case).model_dump(mode="json")})
        except ValidationError as e:
            outcomes.append({"rejected": e.errors(include_context=False, include_url=False)})
    out["validation"][name] = outcomes
print(json.dumps(out, sort_keys=True))
