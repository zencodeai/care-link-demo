"""Join the frozen design inventories to the reviewed IMP-10 evidence map."""

import argparse
import json
from pathlib import Path
from typing import Any

from tools.check import ROOT

SESSION = ROOT / "doc/IMP/slices/IMP-10-integrated-demonstrator/sessions/001-implementation"


def read(path: Path) -> Any:
    return json.loads(path.read_text())


def generate() -> dict[str, object]:
    design = read(ROOT / "doc/LLD/traceability.json")
    plan = read(ROOT / "doc/IMP/implementation-plan.json")
    controls = read(ROOT / "doc/LLD/control-register.json")["controls"]
    observed = read(SESSION / "observations.json")
    allocations = {item["requirement"]: item for item in plan["requirement_allocation"]}
    if set(allocations) != {item["requirement"] for item in design["requirements"]}:
        raise ValueError("Requirement allocation disagrees with the design inventory")
    for item in design["requirements"]:
        item["allocation"] = allocations[item["requirement"]]
    groups = {
        "requirements": (design["requirements"], "requirement"),
        "source_requirements": (design["source_requirements"], "requirement"),
        "source_elements": (design["source_elements"], "element"),
        "invariants": (design["invariants"], "invariant"),
        "acceptance_groups": (design["acceptance_groups"], "id"),
        "controls": (controls, "id"),
        "operations": (plan["operation_allocation"], "operation_id"),
    }
    if set(observed) - (set(groups) | {"verification", "evidence"}):
        raise ValueError("Unknown evidence group")
    evidence = observed["evidence"]
    current: dict[str, object] = {}
    for name, (items, key) in groups.items():
        reviewed = observed.get(name, {})
        ids = {item[key] for item in items}
        if len(ids) != len(items) or set(reviewed) - ids:
            raise ValueError(f"Unknown or duplicate identifiers in {name}")
        for item in items:
            item["current_evidence"] = reviewed.get(
                item[key],
                {
                    "state": "not_individually_assessed",
                    "note": (
                        "Design disposition and historical allocation retained. "
                        "Current evidence was not assessed for this individual row."
                    ),
                },
            )
        current[name] = items
    if set(observed["verification"]) != {f"VT-{i:02d}" for i in range(1, 19)}:
        raise ValueError("Verification family reconciliation is incomplete")
    for name, rows in observed.items():
        if name == "evidence":
            continue
        for row in rows.values():
            if set(row.get("evidence", [])) - set(evidence):
                raise ValueError(f"Unknown evidence reference in {name}")
    return {
        "scope": (
            "Local private synthetic candidate dispositions. Runtime approvals "
            "require separate authority."
        ),
        "counts": {name: len(items) for name, (items, _) in groups.items()},
        **current,
        "verification": observed["verification"],
        "evidence": evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = SESSION / "trace-disposition.json"
    document = json.dumps(generate(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if path.read_text() != document:
            raise SystemExit("IMP-10 disposition matrix drift")
    else:
        path.write_text(document)


if __name__ == "__main__":
    main()
