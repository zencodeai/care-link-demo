"""Reproduce the bounded developer contract snapshot from reviewed LLD definitions."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    ROOT / "packages/contracts/python/src/care_link_contracts/schema.json",
    ROOT / "packages/contracts/typescript/src/schema.json",
)
NAMES = (
    "SessionCreate",
    "RevisionCommand",
    "Error",
    "LoginStart",
    "LoginIntent",
    "LoginCallback",
    "BrowserSession",
    "Empty",
    "StepUpStart",
    "Ceremony",
    "CeremonyConfirm",
    "HelpCreate",
    "HelpView",
    "HelpAuthorityRequest",
    "FreshHelpAuthority",
    "Signal",
    "SignalAck",
    "StaticManifest",
    "StaticPublish",
    "CommandResult",
    "SessionView",
    "DisclosureAck",
    "TurnSubmit",
    "AssessmentView",
    "AssertionCreate",
    "AssertionView",
    "ChoiceCommand",
    "HumanRequest",
    "ReasonCommand",
    "QueueView",
    "QueuePage",
    "AssignmentCommand",
    "AssignmentView",
    "TransferPreparation",
    "TransferConfirm",
    "ObserveCommand",
    "MessageSubmit",
    "MessageView",
    "MessagePage",
    "ContinuationRotate",
    "ContinuationIssued",
    "ContinuationRecover",
    "OperationStatus",
    "ControlChange",
    "ChannelChallengeView",
    "ChannelAckSubmit",
    "ChannelAckView",
    "EventView",
    "PolicyInput",
    "PolicyDecision",
    "JournalAppend",
    "JournalHead",
    "JournalRecord",
    "DutyDefinition",
    "DutyEvidence",
    "WorkloadActor",
    "DueJob",
    "Gateway_continuation_rotate",
    "Gateway_continuation_recover",
    "Gateway_operation_status",
    "Gateway_session_create",
    "Gateway_session_read",
    "Gateway_session_disclosure",
    "Gateway_session_turns",
    "Gateway_session_assertions",
    "Gateway_session_choices",
    "Gateway_session_human_request",
    "Gateway_session_end",
    "Gateway_session_events",
    "Gateway_messages_read",
    "Gateway_message_send",
    "Gateway_queue_list",
    "Gateway_workforce_reserve",
    "Gateway_workforce_accept",
    "Gateway_workforce_prepare_transfer",
    "Gateway_workforce_confirm_transfer",
    "Gateway_workforce_transfer_failed",
    "Gateway_workforce_observe",
    "Gateway_workforce_takeover",
    "Gateway_control_change",
    "Gateway_channel_challenge_read",
    "Gateway_channel_ack",
    "MetadataRequest",
    "MetadataResult",
    "IdentityEvidence",
    "SignedDelegation",
    "PageQuery",
    "BackupView",
    "PlanCreate",
    "PlanFieldCreate",
    "PlanView",
    "ConsentGrant",
    "ConsentView",
    "DirectoryQuery",
    "DirectoryIngest",
    "DirectoryView",
    "DirectoryPage",
    "Gateway_plan_create",
    "Gateway_plan_read",
    "Gateway_plan_field_append",
    "Gateway_plan_retire",
    "Gateway_consent_grant",
    "Gateway_consent_read",
    "Gateway_consent_revoke",
    "Gateway_directory_search",
    "Gateway_directory_read",
    "Gateway_directory_ingest",
    "Gateway_directory_suspend",
    "ReferralDraftCreate",
    "ReferralView",
    "ReferralPayload",
    "ReviewCommand",
    "ReviewView",
    "DispatchRequest",
    "DispatchView",
    "ReceiptView",
    "ReceiverDecision",
    "ReceiverPackageQuery",
    "ReceiverPackagePage",
    "SimulatorSend",
    "Gateway_referral_draft",
    "Gateway_referral_read",
    "Gateway_referral_review",
    "Gateway_referral_dispatch",
    "Gateway_dispatch_read",
    "Gateway_receipt_read",
    "Gateway_dispatch_reconcile",
    "TaskCreate",
    "TaskView",
    "DraftView",
    "LeaseCommand",
    "LeaseView",
    "Proposal",
    "ToolInvoke",
    "Observation",
    "RuntimeInferenceRequest",
    "InferenceRequest",
    "InferenceResult",
    "Gateway_task_create",
    "Gateway_task_read",
    "Gateway_task_cancel",
    "Gateway_task_revise",
    "Gateway_draft_read",
    "Gateway_draft_review",
)


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
    # BFF transport metadata extensions; separate from reviewed LLD operations.
    for name, field, shape in (
        (
            "BrowserCsrf",
            "csrf_token",
            {"type": "string", "minLength": 32, "maxLength": 512, "pattern": "^[A-Za-z0-9_-]+$"},
        ),
        (
            "StepUpProof",
            "proof_intent_id",
            source["$defs"]["LoginIntent"]["properties"]["intent_id"],
        ),
    ):
        selected[name] = {
            "type": "object",
            "properties": {field: shape},
            "required": [field],
            "additionalProperties": False,
        }
    selected["HelpCreateIntent"] = {
        "type": "object",
        "properties": {"operation_id": source["$defs"]["LoginIntent"]["properties"]["intent_id"]},
        "required": ["operation_id"],
        "additionalProperties": False,
    }
    selected["Gateway_continuation_issue"] = {
        "type": "object",
        "properties": {
            "path_arguments": source["$defs"]["Path_session_read"],
            "arguments": source["$defs"]["RevisionCommand"],
            "delegation": source["$defs"]["SignedDelegation"],
            "decision": source["$defs"]["PolicyDecision"],
        },
        "required": ["path_arguments", "arguments", "delegation", "decision"],
        "additionalProperties": False,
    }
    # Internal IMP-03 HTTP cursor is part of the signed request body. A free
    # Last-Event-ID header must not alter the meaning of a signed delegation.
    selected["Gateway_session_events"] = {
        **selected["Gateway_session_events"],
        "properties": {
            **selected["Gateway_session_events"]["properties"],
            "arguments": {
                "type": "object",
                "properties": {"last_event_id": source["$defs"]["Revision"]},
                "required": ["last_event_id"],
                "additionalProperties": False,
            },
        },
    }
    selected["ContinuationRecoveryStart"] = {
        "type": "object",
        "properties": {
            "session_id": source["$defs"]["Id"],
            "family_id": source["$defs"]["Id"],
            "expected_revision": source["$defs"]["Revision"],
        },
        "required": ["session_id", "family_id", "expected_revision"],
        "additionalProperties": False,
    }
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
    # IMP-04 additive transport bindings: exact target discovery, multi-grant
    # policy evidence and actor-owned current reports. Canonical LLD unchanged.
    selected["StepUpStart"]["properties"]["purpose"]["enum"].append("follow_up_consent")
    planning_actions = (
        "plan_create",
        "plan_read",
        "plan_field_append",
        "plan_retire",
        "consent_grant",
        "consent_read",
        "consent_revoke",
        "directory_search",
        "directory_read",
        "directory_ingest",
        "directory_suspend",
    )
    # Referral context and receiver revision are additive transport projections.
    # They expose server authority without changing canonical actor operations.
    referral = json.loads((ROOT / "packages/contracts/referral.schema.json").read_text())
    selected.update(referral["$defs"])
    planning_actions += (
        "referral_draft",
        "referral_read",
        "referral_review",
        "referral_dispatch",
        "dispatch_read",
        "receipt_read",
        "dispatch_reconcile",
        "referral_context",
        "dispatcher_send",
        "referral_sources",
    )
    assistance = json.loads((ROOT / "packages/contracts/assistance.schema.json").read_text())
    selected.update(assistance["$defs"])
    planning_actions += (
        "task_create",
        "task_read",
        "task_cancel",
        "task_revise",
        "draft_read",
        "draft_review",
        "assistance_status",
        "assistance_task_context",
        "assistance_draft_context",
    )
    targets = []
    for action in planning_actions:
        gateway = selected["Gateway_" + action]["properties"]
        targets.append(
            {
                "type": "object",
                "properties": {
                    "action": {"const": action},
                    "operation_id": {"$ref": "#/$defs/Id"},
                    "arguments": gateway["arguments"],
                    "path_arguments": gateway["path_arguments"],
                },
                "required": ["action", "operation_id", "arguments", "path_arguments"],
                "additionalProperties": False,
            }
        )
    selected["MetadataRequest"]["properties"]["planning"] = {"oneOf": targets}
    bindings = {
        "resolved_scope": {"$ref": "#/$defs/Scope"},
        "consent_id": source["$defs"]["PolicyInput"]["properties"]["consent_id"],
        "review_id": source["$defs"]["PolicyInput"]["properties"]["review_id"],
        "disclosure_grants": {
            "type": "array",
            "items": {"$ref": "#/$defs/ConsentAuthority"},
            "maxItems": 32,
        },
        "artifact_digests": source["$defs"]["PolicyInput"]["properties"]["artifact_digests"],
    }
    selected["ConsentAuthority"]["properties"].update(
        {
            "subject_id": {"$ref": "#/$defs/Id"},
            "session_id": {"$ref": "#/$defs/Id"},
            "purpose": {"enum": ["plan", "referral"]},
        }
    )
    bindings["directory_bindings"] = {
        "type": "array",
        "maxItems": 100,
        "items": {
            "type": "object",
            "properties": {
                "service_id": {"$ref": "#/$defs/Id"},
                "revision": {"$ref": "#/$defs/Revision"},
                "artifact_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "suspended": {"type": "boolean"},
                "current": {"type": "boolean"},
            },
            "required": ["service_id", "revision", "artifact_digest", "suspended", "current"],
            "additionalProperties": False,
        },
    }
    selected["PolicyInput"]["properties"]["directory_bindings"] = bindings["directory_bindings"]
    selected["PolicyInput"]["properties"]["referral_payload_digest"] = {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    bindings["referral_payload_digest"] = selected["PolicyInput"]["properties"][
        "referral_payload_digest"
    ]
    selected["MetadataResult"]["properties"].update(bindings)
    selected["PolicyInput"]["properties"]["disclosure_grants"] = bindings["disclosure_grants"]
    selected["RevisionVector"]["properties"]["directory_set_digest"] = {
        "type": "string",
        "pattern": "^[0-9a-f]{64}$",
    }
    selected["OwnReportPage"] = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"$ref": "#/$defs/AssertionView"}, "maxItems": 100},
            "next_cursor": {"type": "null"},
        },
        "required": ["items", "next_cursor"],
        "additionalProperties": False,
    }
    selected["Gateway_own_reports_read"] = {
        "type": "object",
        "properties": {
            "arguments": source["$defs"]["Empty"],
            "path_arguments": source["$defs"]["Path_session_read"],
            "delegation": source["$defs"]["Gateway_session_read"]["properties"]["delegation"],
            "decision": source["$defs"]["Gateway_session_read"]["properties"]["decision"],
        },
        "required": ["arguments", "path_arguments", "delegation", "decision"],
        "additionalProperties": False,
    }
    review = json.loads((ROOT / "packages/contracts/manual-review.schema.json").read_text())
    selected.update(review["$defs"])
    plans_review = json.loads((ROOT / "packages/contracts/plans-review.schema.json").read_text())
    selected.update(plans_review["$defs"])
    include("Id")
    include("Revision")
    for name in ("BrowserSession", "IdentityEvidence"):
        selected[name] = {
            **selected[name],
            "properties": {
                **selected[name]["properties"],
                "review_run_id": {"$ref": "#/$defs/Id"},
                "review_slot_id": {
                    "enum": [
                        "participant",
                        "worker1",
                        "worker2",
                        "supervisor",
                        "pid",
                        "carer",
                        "professional",
                    ]
                },
                "review_origin": {"type": "string", "format": "uri", "pattern": "^https://"},
            },
        }
    selected["RevisionVector"] = {
        **selected["RevisionVector"],
        "properties": {
            **selected["RevisionVector"]["properties"],
            "review_run": {"$ref": "#/$defs/Revision"},
        },
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
    command = ["node", str(ROOT / "tools/generate_browser_validators.mjs")]
    if args.check:
        command.append("--check")
    subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603
    api = [sys.executable, str(ROOT / "tools/generate_agentic_api.py")]
    if args.check:
        api.append("--check")
    subprocess.run(api, cwd=ROOT, check=True)  # noqa: S603
    print("Contract snapshots match reviewed definitions.")


if __name__ == "__main__":
    main()
