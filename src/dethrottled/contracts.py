"""Compact discovery of required HTTP fields from the actual OpenAPI contract."""


def requests(schema):
    routes = []
    for path, operations in sorted(schema["paths"].items()):
        for method, operation in sorted(operations.items()):
            body = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if "$ref" in body:
                body = schema["components"]["schemas"][body["$ref"].rsplit("/", 1)[-1]]
            routes.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "required_body_fields": body.get("required", []),
                    "body_fields": list(body.get("properties", {})),
                    "query_parameters": [
                        {"name": p["name"], "required": p.get("required", False)}
                        for p in operation.get("parameters", [])
                        if p.get("in") == "query"
                    ],
                }
            )
    return {"openapi": "/openapi.json", "routes": routes}
