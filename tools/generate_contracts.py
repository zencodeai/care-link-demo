"""Reproduce the bounded developer contract snapshot from reviewed LLD definitions."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    ROOT / "packages/contracts/python/src/care_link_contracts/schema.json",
    ROOT / "packages/contracts/typescript/src/schema.json",
)
NAMES = ("SessionCreate", "RevisionCommand", "Error")


def render() -> str:
    source = json.loads((ROOT / "doc/LLD/contracts/definitions.schema.json").read_text())
    selected: dict[str, object] = {}

    def include(name: str) -> None:
        if name in selected:
            return
        selected[name] = source["$defs"][name]
        walk(selected[name])

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if "$ref" in value:
                include(value["$ref"].split("/")[-1])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for name in NAMES:
        include(name)
    properties = {
        "contract_version": {"const": "dev-1"},
        "status": {"const": "developer_only"},
        "tags": {"$ref": "#/$defs/Tag"},
        "participant_admission": {"const": False},
        "business_operations": {"const": "unavailable"},
        "contract_validation": {"const": True},
    }
    selected["DeveloperCapability"] = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    return (
        json.dumps(
            {
                "$schema": source["$schema"],
                "$id": "urn:care-link:developer:dev-1",
                "$defs": selected,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render()
    for target in TARGETS:
        if args.check:
            if not target.exists() or target.read_text() != expected:
                raise SystemExit(f"Contract snapshot drift: {target.relative_to(ROOT)}")
        else:
            target.write_text(expected)
    print("Contract snapshots match reviewed definitions.")


if __name__ == "__main__":
    main()
