#!/usr/bin/env python3
"""Validate design artifacts only. Never connects to application/runtime services.

Requires jsonschema[format] and openapi-spec-validator (tooling, not app dependencies).
Run: python doc/LLD/validate_design.py
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent


def read(name):
    return json.loads((ROOT / name).read_text())


def check(condition, message):
    if not condition:
        raise ValueError(message)


def decimal_max(validator, maximum, instance, schema):
    if isinstance(instance, str) and instance.isdigit() and int(instance) > int(maximum):
        yield ValidationError("decimal revision exceeds signed-64-bit maximum")


ContractValidator = validators.extend(Draft202012Validator, {"x-decimalMaximum": decimal_max})


def instant(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def semantic(name, value):
    """Selected cross-field contract rules, never a runtime authorization engine."""
    if name == "ConsentGrant":
        duration = (instant(value["expires_at"]) - instant(value["effective_at"])).total_seconds()
        check(duration > 0, "consent interval must be nonempty")
        if value["purpose"] == "referral":
            check(duration <= 900, "referral consent exceeds fifteen minutes")
    if name == "ReviewCommand":
        check((value["decision"] == "edit") == (value["edited_text"] is not None),
              "only edit requires and accepts edited_text")
    if name == "FieldState":
        check(bool(value["assertion_ids"]) == (value["state"] == "captured"),
              "captured needs evidence; unknown/deferred cannot carry a hidden value")
    if name in {"TaskCreate", "TaskView"}:
        binding = value["binding"]
        if binding["kind"] == "session":
            check(value["scope"]["session_id"] == binding["session_id"], "task session binding mismatch")
        elif binding["kind"] != "training_scenario":
            check(value["scope"]["session_id"] is None, "non-session task cannot inherit a session scope")
    if name == "InferenceResult":
        check((value["state"] == "completed") == (value["proposal"] is not None),
              "only completed inference has a proposal")
    if name == "SignedDelegation":
        actor, evidence = value["actor"], value["evidence"]
        if actor["kind"] == "human":
            check(evidence["kind"] == "human_identity", "human cannot use workload-duty evidence")
            check(actor["principal_id"] == evidence["principal_id"], "identity principal mismatch")
            check(actor["identity_evidence_id"] == evidence["id"], "identity evidence reference mismatch")
        else:
            check(evidence["kind"] == "workload_duty", "workload cannot manufacture a human identity")
            check(actor["actor_id"] == evidence["actor_id"], "workload duty actor mismatch")
            check(actor["duty_id"] == evidence["duty_id"] and actor["workload_id"] == evidence["workload_id"],
                  "attested workload/duty evidence mismatch")
        check(value["body_digest"] == evidence["request_digest"], "delegation body digest mismatch")
    if name == "JournalAppend":
        if value["kind"] == "restrict_intent":
            check(value["restriction"]["kind"] != "none", "restriction needs replayable semantics")
        if value["kind"] == "relax_intent":
            check(value["relaxation_evidence_digest"] is not None, "relaxation needs exact evidence")
    if name == "PromotionPropose":
        b = value["binding"]
        for k in ["target_id", "backup_digest", "head_digest", "restriction_barrier", "validation_digest", "serving_generation"]:
            check(value[k] == b[k], "promotion duplicate binding mismatch: " + k)
    if name == "DirectoryView":
        facts = value["facts"]
        if facts["operating_state"] in {"temporary_closure", "regional_outage"}:
            check(facts["availability"] == "unavailable", "closed/outage service cannot claim availability")
        if facts["operating_state"] in {"api_failure", "conflicting_source"}:
            check(facts["availability"] == "unknown", "unknown source cannot claim availability")
        if value["state"] in {"stale", "quarantined", "suspended"}:
            check(facts["availability"] != "available_fixture", "unadmitted source cannot claim availability")


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from nodes(child)


def bundle(value):
    if isinstance(value, list):
        return [bundle(v) for v in value]
    if isinstance(value, dict):
        return {k: ("#/components/schemas/" + v.split("/")[-1]
                    if k == "$ref" and v.startswith("#/$defs/") else bundle(v)) for k, v in value.items()}
    return value


def main():
    schema = read("contracts/definitions.schema.json")
    Draft202012Validator.check_schema(schema)
    definitions = schema["$defs"]
    for n in nodes(definitions):
        if "$ref" in n:
            check(n["$ref"].startswith("#/$defs/") and n["$ref"].split("/")[-1] in definitions,
                  "unresolved/nonlocal schema reference: " + n["$ref"])
        if n.get("type") == "object":
            check(n.get("additionalProperties") is False, "object schema must reject unknown keys")
            check(set(n.get("required", [])) <= set(n.get("properties", {})), "unknown required property")
    api = read("contracts/openapi.json")
    validate(api)
    check(api["components"]["schemas"] == bundle(definitions), "OpenAPI schema bundle drift")
    operations = read("contracts/operations.json")["operations"]
    ids, routes = set(), set()
    for op in operations:
        key = (op["method"], op["path"])
        check(op["operation_id"] not in ids and key not in routes, "duplicate operation/route")
        ids.add(op["operation_id"])
        routes.add(key)
        check(op["response"] in definitions and (op["request"] is None or op["request"] in definitions),
              "operation references unknown type")
        wire = api["paths"][op["path"]][op["method"].lower()]
        check(wire["operationId"] == op["operation_id"] and wire["x-design-rules"] == op, "API ownership drift")
        if op["method"] != "GET":
            check(op["idempotency"] != "none", "unbound mutation idempotency")
    tool_names = []
    for branch in definitions["ToolArguments"]["oneOf"]:
        tool_names.append(definitions[branch["$ref"].split("/")[-1]]["properties"]["tool"]["const"])
    check(len(tool_names) == len(set(tool_names)), "duplicate tool discriminant")
    check(not ({"consent_grant", "send_emergency", "shell", "browse", "sql"} & set(tool_names)), "forbidden tool")
    fixtures = read("contracts/fixtures.json")["fixtures"]
    tested = set()
    for f in fixtures:
        check(f["schema"] in definitions, "fixture references unknown type")
        validator = ContractValidator({"$defs": definitions, "$ref": "#/$defs/" + f["schema"]}, format_checker=FormatChecker())
        valid = not list(validator.iter_errors(f["value"]))
        if valid and f["layer"] == "schema_and_semantics":
            try:
                semantic(f["schema"], f["value"])
            except (ValueError, KeyError, TypeError):
                valid = False
        check(valid == f["valid"], "fixture unexpected result: " + f["id"])
        if valid:
            tested.add(f["schema"])
    check(set(definitions) <= tested, "missing positive type fixtures")
    state_types = {"session": ("SessionView", "service_phase"), "transport": ("SessionView", "transport"),
                   "task": ("TaskView", "state"), "dispatch": ("DispatchView", "state"),
                   "follow_up": ("FollowUpView", "state"), "help": ("HelpView", "state"),
                   "activation": ("ActivationView", "state"), "rights": ("RightsView", "state"),
                   "restore": ("RestoreView", "state")}
    for machine in read("contracts/state-machines.json")["machines"]:
        states = set(machine["states"])
        if machine["name"] in state_types:
            dto, field = state_types[machine["name"]]
            check(states == set(definitions[dto]["properties"][field]["enum"]), "wire/machine state drift")
        check(len(states) == len(machine["states"]), "duplicate state")
        check(machine["initial"] in states and set(machine["terminal"]) <= states, "invalid state boundary")
        seen = set()
        reachable = {machine["initial"]}
        for t in machine["transitions"]:
            check(set(t["from"]) <= states and t["to"] in states and t["guard"] and t["effect"], "unclosed transition")
            for source in t["from"]:
                key = (source, t["event"])
                check(key not in seen, "ambiguous source/event: " + str(key))
                seen.add(key)
                check(source not in machine["terminal"], "terminal state has outgoing transition")
        for _ in states:
            for t in machine["transitions"]:
                if set(t["from"]) & reachable:
                    reachable.add(t["to"])
        check(states <= reachable, "unreachable states: " + str(states - reachable))
    trace = read("traceability.json")
    check(len(trace["requirements"]) == 90 and len(trace["source_elements"]) == 37
          and len(trace["source_requirements"]) == 114 and len(trace["invariants"]) == 16, "trace omissions")
    for row in trace["requirements"] + trace["source_requirements"]:
        for name in row["mechanisms"]:
            check((ROOT / name).is_file(), "trace mechanism missing")
        check(row["evidence_status"] == "not_assessed", "unearned runtime evidence")
    storage = read("storage-model.json")
    records = {r["name"]: r for r in storage["records"]}
    check(len(records) == len(storage["records"]), "duplicate storage record")
    for table in records.values():
        columns = table["columns"]
        for key in table["primary_key"]:
            check(key in columns and not columns[key]["nullable"], "invalid/nullable primary key")
        for fields in table["unique"]:
            check(set(fields) <= set(columns), "invalid unique key")
        for index in table["indexes"]:
            check(set(index.split(",")) <= set(columns), "invalid index columns")
        for column in columns.values():
            for attribute in ["contract", "item_contract"]:
                if attribute in column:
                    check(column[attribute] in definitions, "storage references unknown DTO")
        for foreign in table["foreign_keys"]:
            target = records[foreign["target"]]
            check(table["database"] == target["database"], "fictional cross-database FK")
            check(len(foreign["columns"]) == len(foreign["target_columns"]), "FK arity mismatch")
            check(set(foreign["columns"]) <= set(columns) and
                  set(foreign["target_columns"]) <= set(target["columns"]), "invalid FK columns")
            target_key = foreign["target_columns"]
            check(target_key == target["primary_key"] or target_key in target["unique"], "FK target not unique")
    inventory = read("design-inventory.json")
    for item in inventory["inputs"]:
        check(hashlib.sha256((REPO / item["path"]).read_bytes()).hexdigest() == item["sha256"],
              "source input drift: " + item["path"])
    check(inventory["historical_lld_recovered"] is False, "historical design reuse")
    for artifact in inventory.get("artifacts", []):
        check(hashlib.sha256((ROOT / artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"],
              "LLD artifact drift: " + artifact["path"])
    control_register = read("control-register.json")
    control_ids = set()
    verification_text = (ROOT / "13-verification-and-traceability.md").read_text()
    for control in control_register["controls"]:
        check(control["id"] not in control_ids and control["protected_boundary"] and control["responsible_role"],
              "incomplete/duplicate local control")
        control_ids.add(control["id"])
        check((ROOT / control["mechanism"]).is_file() and control["runtime_evidence"] == "not_assessed",
              "control mechanism/evidence invalid")
        for test in control["verification"]:
            check(test in verification_text, "control references missing verification")
    errors = []
    for f in ROOT.rglob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", f.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            path = target.split("#")[0].strip("<>")
            if path and not (f.parent / path).exists():
                errors.append((f.name, path))
    check(not errors, "broken local links: " + str(errors))
    print(f"PASS: {len(definitions)} type definitions, {len(operations)} operations, {len(fixtures)} fixtures, "
          f"{len(records)} storage records, OpenAPI, state closure, trace, links and frozen inputs. "
          "Design checks only; no runtime tests.")


if __name__ == "__main__":
    main()
