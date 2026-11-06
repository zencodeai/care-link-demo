#!/usr/bin/env python3
"""Validate planning records only; never runs proposed commands or contacts services."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent


def check(condition, message):
    if not condition:
        raise ValueError(message)


def load(name):
    return json.loads((ROOT / name).read_text())


def safe_owned_path(path):
    return not path.startswith(("/", "~")) and ".." not in Path(path).parts and path not in {"*", "**", "."}


def semantics(kind, value):
    if kind == "WorkPacket":
        for path in value["write_paths"]:
            check(safe_owned_path(path), "write path leaves assigned repository scope")
        if value["mode"] in {"planning", "review"}:
            check(not value["write_paths"], "read-only packet has write paths")
            check(set(value["allowed_actions"]) <= {"read_source", "propose"}, "read-only mode has effect actions")
        if set(value["allowed_actions"]) - {"read_source", "propose"}:
            a = value["authorization"]
            check(a["source_kind"] != "none" and a["instruction_reference"], "effect action lacks actual scoped authorization")
        if value["role"] in {"imp_scope", "imp_review"}:
            check(not value["write_paths"], "read-only role cannot claim writer scope")
        for lease in value["resource_leases"]:
            check(lease["owner_task_id"] == value["task_id"], "foreign resource lease")
    if kind == "AgentResult":
        for path in value["changed_paths"]:
            check(safe_owned_path(path), "agent changed foreign scope")
        if value["role"] in {"imp_scope", "imp_review"}:
            check(not value["changed_paths"], "read-only specialist reports edits")
        for result in value["checks"]:
            if result["status"] in {"passed", "failed"}:
                check(result["evidence_path"] and result["evidence_digest"], "reported execution lacks evidence")
            if result["status"] == "not_run":
                check(result["actual"], "not_run lacks explanation")
    if kind in {"DemoPacket", "HumanDecision"}:
        check(value["gate_id"] == "G-" + value["stage_id"][-2:], "stage/gate mismatch")
    if kind == "DemoPacket" and value["state"] == "demonstrated":
        for step in value["normal_steps"] + value["adverse_steps"]:
            check(step["actual"] and step["evidence_refs"], "demonstrated step lacks actual evidence")
    if kind == "HumanDecision":
        check(not value["is_example"], "example cannot be actual human acceptance")
        check(value["authorization"]["source_kind"] != "none" and value["authorization"]["instruction_reference"],
              "human action cannot be inferred from a JSON record")


def acyclic(rows, key="id"):
    nodes = {r[key]: r for r in rows}
    check(len(nodes) == len(rows), "duplicate DAG identifier")
    visited, active = set(), set()

    def visit(node):
        check(node not in active, "dependency cycle: " + node)
        if node in visited:
            return
        check(node in nodes, "missing dependency: " + node)
        active.add(node)
        for dependency in nodes[node].get("depends_on", []):
            visit(dependency)
        active.remove(node)
        visited.add(node)

    for node in nodes:
        visit(node)


def main():
    schema = load("contracts/planning.schema.json")
    Draft202012Validator.check_schema(schema)
    definitions = schema["$defs"]
    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                check(value["$ref"].startswith("#/$defs/") and value["$ref"].split("/")[-1] in definitions,
                      "nonlocal or missing handoff type reference")
            if value.get("type") == "object":
                check(value.get("additionalProperties") is False, "open nested handoff object")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(definitions)
    for fixture in load("contracts/fixtures.json")["fixtures"]:
        validator = Draft202012Validator({"$defs": definitions, "$ref": "#/$defs/" + fixture["type"]}, format_checker=FormatChecker())
        valid = not list(validator.iter_errors(fixture["value"]))
        check(valid == fixture["schema_valid"], "fixture shape mismatch: " + fixture["id"])
        semantic_valid = valid
        if valid:
            try:
                semantics(fixture["type"], fixture["value"])
            except ValueError:
                semantic_valid = False
        check(semantic_valid == fixture["semantics_valid"], "fixture semantics mismatch: " + fixture["id"])
    for path, kind in [("examples/imp-00-work-packet.json", "WorkPacket"),
                       ("examples/agent-result.example.json", "AgentResult"),
                       ("examples/demo-packet.example.json", "DemoPacket")]:
        value = load(path)
        Draft202012Validator({"$defs": definitions, "$ref": "#/$defs/" + kind}, format_checker=FormatChecker()).validate(value)
        semantics(kind, value)
        check(value["is_example"], "example file looks like actual execution/approval")
    plan = load("implementation-plan.json")
    stages, tasks = plan["stages"], plan["tasks"]
    acyclic(stages)
    acyclic(tasks)
    stage_ids = {s["id"] for s in stages}
    check(stage_ids == {"IMP-%02d" % n for n in range(11)}, "missing stage")
    gates = {s["gate_id"] for s in stages}
    check(len(gates) == len(stages), "shared/duplicate human gate")
    check(not plan["human_decisions"], "new plan must not invent human acceptance")
    roles = load("agent-contracts.json")
    names = {a["name"] for a in roles["roles"]}
    check(len(names) == len(roles["roles"]) and len(names) == 7, "invalid role catalog")
    check(roles["max_parallel_specialists"] == plan["max_parallel_specialists"] == 3, "concurrency drift")
    for role in roles["roles"]:
        check(not role["may_delegate"] and not role["may_accept_human_gate"], "specialist authority expansion")
        native = tomllib.loads((ROOT / role["native_template"]).read_text())
        check(set(native) == {"name", "description", "developer_instructions"}, "unsupported/unintended native override")
        check(native["name"] == role["name"] and native["developer_instructions"], "role/template mismatch")
    config = tomllib.loads((ROOT / "codex/project-config.fragment.toml").read_text())
    check(config == {"agents": {"enabled": True, "max_concurrent_threads_per_session": 3}}, "unexpected config fragment")
    for stage in stages:
        check(stage["gate_id"] == "G-" + stage["id"][-2:], "stage/gate mismatch")
        check(stage["state"] == "planned" and stage["human_acceptance"] is None and not stage["completion_evidence"],
              "unexecuted stage carries acceptance/evidence")
        check(stage["demo_steps"] and stage["adverse_tests"] and stage["rollback"] and stage["human_decision"],
              "stage lacks reviewable demo/adverse/rollback/decision")
        check(set(stage["specialists"]) <= names, "unknown stage role")
    for task in tasks:
        check(task["stage_id"] in stage_ids and task["role"] in names and task["state"] == "planned", "invalid task binding")
        check(task["mode"] in {"planning", "implementation", "verification", "review"}, "invalid task mode")
        check(all(safe_owned_path(p) for p in task["candidate_write_paths"]), "invalid task ownership candidate")
        check(all(t["stage_id"] == task["stage_id"] for t in tasks if t["id"] in task["depends_on"]),
              "cross-stage task dependency must be declared at stage gate")
    workflow = load("stage-workflow.json")
    states = set(workflow["states"])
    check(workflow["initial"] in states and set(workflow["terminal"]) <= states, "invalid workflow boundary")
    transition_keys = set()
    reachable = {workflow["initial"]}
    for transition in workflow["transitions"]:
        check(set(transition["from"]) <= states and transition["to"] in states and transition["guard"] and
              transition["effect"], "unclosed workflow transition")
        for source in transition["from"]:
            check(source not in workflow["terminal"], "terminal workflow state has outgoing event")
            pair = (source, transition["event"])
            check(pair not in transition_keys, "ambiguous workflow transition")
            transition_keys.add(pair)
        if transition["to"] == "accepted":
            check(transition["owner"] == "actual_human", "agent can accept human gate")
    for _ in states:
        for transition in workflow["transitions"]:
            if set(transition["from"]) & reachable:
                reachable.add(transition["to"])
    check(states <= reachable, "unreachable workflow state")
    operations = json.loads((REPO / "doc/LLD/contracts/operations.json").read_text())["operations"]
    allocations = plan["operation_allocation"]
    check(len({o["operation_id"] for o in allocations}) == len(allocations), "duplicate operation allocation")
    check({o["operation_id"] for o in allocations} == {o["operation_id"] for o in operations}, "operation allocation omission")
    for operation in allocations:
        check(operation["completion_stage"] in stage_ids, "unknown operation completion stage")
        if operation["operation_id"] == "identity_link_request":
            check(operation["disposition"] == "disabled_scope_guard_only", "identity link silently enabled")
    trace = json.loads((REPO / "doc/LLD/traceability.json").read_text())
    check({r["requirement"] for r in plan["requirement_allocation"]} ==
          {r["requirement"] for r in trace["requirements"]}, "local requirement omitted")
    for r in plan["requirement_allocation"]:
        check(r["lead_stage"] in stage_ids and r["evidence_status"] == "not_implemented", "false requirement evidence")
    defaults = json.loads((REPO / "doc/LLD/implementation-defaults.json").read_text())
    check(plan["deployment_target"] == defaults["deployment_target"] == "this_workstation", "target drift")
    check(plan["selected_model_identifier"] == defaults["selected_model_identifier"], "model drift")
    for tool in load("tooling.json")["tools"]:
        check(tool["version"] is None and tool["installation_status"] == "not_assessed" and
              not tool["executed_for_implementation"], "unobserved tool pin or execution")
        check(tool["first_stage"] in stage_ids and tool["primary_sources"] and tool["required_checks"], "incomplete tool recommendation")
    inventory = load("planning-inventory.json")
    for item in inventory["inputs"]:
        check(hashlib.sha256((REPO / item["path"]).read_bytes()).hexdigest() == item["sha256"],
              "baseline drift: " + item["path"])
    for item in inventory.get("artifacts", []):
        check(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"],
              "planning artifact drift: " + item["path"])
    errors = []
    for path in ROOT.rglob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            local = target.split("#")[0].strip("<>")
            if local and not (path.parent / local).exists():
                errors.append((path.name, local))
    check(not errors, "broken local links: " + str(errors))
    print(f"PASS: {len(stages)} staged gates, {len(tasks)} tasks, {len(allocations)} operation allocations, "
          f"{len(names)} TOML roles, handoff fixtures, DAGs, links and frozen inputs. Planning checks only.")


if __name__ == "__main__":
    main()
