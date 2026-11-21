"""Generate additive knowledge/dispatch OpenAPI from the shared wire schemas."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "doc/LLD/contracts/agentic.openapi.json"


def render() -> str:
    source = json.loads(
        (ROOT / "packages/contracts/python/src/care_link_contracts/schema.json").read_text()
    )["$defs"]
    selected: dict[str, object] = {}

    def include(name: str) -> None:
        if name in selected:
            return
        selected[name] = source[name]
        walk(source[name])

    def walk(value: object) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                include(ref.removeprefix("#/$defs/"))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for name in [
        "KnowledgeQuery",
        "KnowledgeResults",
        "RuntimeWorkRequest",
        "RuntimeWorkItem",
        "Error",
    ]:
        include(name)
    schemas = json.loads(json.dumps(selected).replace("#/$defs/", "#/components/schemas/"))

    def operation(
        operation_id: str, request: str, response: str, internal: bool
    ) -> dict[str, object]:
        parameters: list[dict[str, object]] = [
            {
                "in": "header",
                "name": "Idempotency-Key" if internal else "X-CSRF-Token",
                "required": True,
                "schema": {"type": "string", "format": "uuid"}
                if internal
                else {"type": "string", "minLength": 32, "maxLength": 256},
            }
        ]
        return {
            "operationId": operation_id,
            "security": [{"RuntimeMTLS" if internal else "BrowserSession": []}],
            "parameters": parameters,
            "x-query-parameters": "forbidden",
            "x-authority": "current runtime workload" if internal else "current actor role",
            "x-effect": "consume ephemeral metadata only"
            if internal
            else "read-only knowledge lookup",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/" + request}}
                },
            },
            "responses": {
                code: {
                    "description": "Typed result" if code == "200" else "Closed safe error",
                    "headers": {"Cache-Control": {"schema": {"type": "string"}}},
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/"
                                + (response if code == "200" else "Error")
                            }
                        }
                    },
                }
                for code in ["200", "400", "401", "403", "409", "503"]
            },
        }

    canonical = json.loads((ROOT / "doc/LLD/contracts/openapi.json").read_text())
    result = {
        "openapi": "3.1.0",
        "info": {"title": "CARE-Link agentic transport amendment", "version": "imp06-003"},
        "paths": {
            "/v1/assistance/knowledge": {
                "post": operation("knowledge_lookup", "KnowledgeQuery", "KnowledgeResults", False)
            },
            "/internal/v1/broker/work": {
                "post": operation(
                    "runtime_work_claim", "RuntimeWorkRequest", "RuntimeWorkItem", True
                )
            },
        },
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "BrowserSession": canonical["components"]["securitySchemes"]["BrowserSession"],
                "RuntimeMTLS": {
                    "type": "mutualTLS",
                    "description": "Exact current Runtime workload only",
                },
            },
        },
    }
    return json.dumps(result, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.is_file() or TARGET.read_text() != expected:
            raise SystemExit("Agentic OpenAPI drift")
    else:
        TARGET.write_text(expected)
    print("Additive agentic OpenAPI matches shared contracts")


if __name__ == "__main__":
    main()
