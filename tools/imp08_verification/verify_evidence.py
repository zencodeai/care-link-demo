"""Verify source/build, session schemas and actual IMP-08 evidence bindings offline."""

import hashlib
import json
from pathlib import Path
from typing import Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "doc/IMP/slices/IMP-08-operational-governance/sessions/001-implementation"


class _Validator(Protocol):
    def validate(self, value: object) -> None: ...


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(value: dict[str, str]) -> None:
    if digest(ROOT / value["path"]) != value["sha256"]:
        raise ValueError("Evidence/source binding drift: " + value["path"])


def main() -> None:
    manifest = json.loads((SESSION / "candidate-manifest.json").read_text())
    for name in ("source_hashes", "reference_hashes", "build_hashes"):
        for path, expected in manifest[name].items():
            if digest(ROOT / path) != expected:
                raise ValueError("Candidate drift: " + path)
    candidate = manifest["candidate"]
    if candidate["environment_digest"] != digest(SESSION / "environment.json"):
        raise ValueError("Environment binding drift")
    print("Source, reference, build and environment hashes matched.")

    schema = json.loads((ROOT / "doc/IMP/contracts/planning.schema.json").read_text())
    for path in (
        *SESSION.glob("*-work-packet.json"),
        SESSION / "agent-result.json",
        SESSION / "demo-packet.json",
    ):
        kind = (
            "WorkPacket"
            if "work-packet" in path.name
            else "AgentResult"
            if path.name == "agent-result.json"
            else "DemoPacket"
        )
        value = json.loads(path.read_text())
        validator = Draft202012Validator(
            {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/" + kind},
            format_checker=FormatChecker(),
        )
        cast(_Validator, validator).validate(value)
        for source in value.get("inputs", value.get("output_refs", [])):
            binding(source)
    print("WorkPacket, AgentResult and DemoPacket contracts and source bindings valid.")

    result = json.loads((SESSION / "results.json").read_text())
    binding(result["candidate_manifest"])
    for check in result["checks"]:
        if check["status"] != "passed":
            raise ValueError("Unresolved qualification check")
        if digest(ROOT / check["evidence_path"]) != check["evidence_digest"]:
            raise ValueError("Check log drift")
    demo = json.loads((SESSION / "demo-packet.json").read_text())
    if demo["candidate"] != candidate or demo["human_decision_id"] is not None:
        raise ValueError("Demo candidate/human decision mismatch")
    for step in (*demo["normal_steps"], *demo["adverse_steps"]):
        for evidence in step["evidence_refs"]:
            binding(evidence)
    ledger = json.loads((ROOT / "doc/IMP/executions/2026-11-21-IMP-08/ledger.json").read_text())
    for key in ("candidate_manifest", "results", "qualification_packet"):
        binding(ledger[key])
    for predecessor in ledger["predecessors"]:
        binding(predecessor)
        state = json.loads((ROOT / predecessor["path"]).read_text())["state"]
        if state not in {"accepted", "automated_qualified"}:
            raise ValueError("Unqualified dependency")
    print("Check logs, dependency evidence and qualification references matched.")

    plan = json.loads((ROOT / "doc/IMP/implementation-plan.json").read_text())
    expected = next(row["relevant_operations"] for row in plan["tasks"] if row["id"] == "IMP-08-A")
    actual = json.loads((SESSION / "operation-trace.json").read_text())
    if set(expected) != {row["operation_id"] for row in actual["operations"]}:
        raise ValueError("Operation trace mismatch")
    print("Canonical operation coverage matched; human review remains deferred.")


if __name__ == "__main__":
    main()
