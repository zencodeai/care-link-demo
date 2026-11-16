"""Selected schema bindings with strict wire parsing and decimal semantics."""

import json
import math
import re
from collections.abc import Callable, Iterator, Mapping
from functools import cache
from importlib.resources import files
from typing import Literal, Protocol, cast

from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
from jsonschema.protocols import Validator

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type KeywordValidator = Callable[[object, str, object, object], Iterator[ValidationError]]


class _ValidatorFactories(Protocol):
    """Typed seam for jsonschema's dynamically constructed extension factory."""

    def extend(
        self, validator: type[Validator], validators: Mapping[str, KeywordValidator]
    ) -> type[Validator]: ...


ContractName = Literal[
    "SessionCreate",
    "RevisionCommand",
    "Error",
    "DeveloperCapability",
    "BrowserCsrf",
    "ContinuationRecoveryStart",
    "Gateway_continuation_issue",
    "StepUpProof",
    "HelpCreateIntent",
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
    "ReviewIntentCancel",
    "Gateway_review_intent_cancel",
    "ReviewWorkspaceQuery",
    "ReviewDraftSave",
    "ReviewIntentPrepare",
    "ReviewDraftView",
    "ReviewIntentView",
    "ReviewHandshakeView",
    "ReviewWorkspace",
    "Gateway_review_workspace",
    "Gateway_review_draft_save",
    "Gateway_review_intent_prepare",
]
CONTRACT_NAMES: tuple[ContractName, ...] = (
    "SessionCreate",
    "RevisionCommand",
    "Error",
    "DeveloperCapability",
    "BrowserCsrf",
    "ContinuationRecoveryStart",
    "Gateway_continuation_issue",
    "StepUpProof",
    "HelpCreateIntent",
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
    "ReviewIntentCancel",
    "Gateway_review_intent_cancel",
    "ReviewWorkspaceQuery",
    "ReviewDraftSave",
    "ReviewIntentPrepare",
    "ReviewDraftView",
    "ReviewIntentView",
    "ReviewHandshakeView",
    "ReviewWorkspace",
    "Gateway_review_workspace",
    "Gateway_review_draft_save",
    "Gateway_review_intent_prepare",
)


class ContractError(ValueError):
    """Safe contract failure; never includes submitted content."""

    def __init__(self, kind: Literal["malformed", "invalid", "unknown_contract"]) -> None:
        self.kind = kind
        super().__init__(kind)


def _decimal_maximum(
    _validator: object, maximum: str, instance: object, _schema: object
) -> Iterator[ValidationError]:
    if isinstance(instance, str):
        if re.fullmatch(r"0|[1-9][0-9]*", instance) is None:
            yield ValidationError("Noncanonical decimal")
        elif len(instance) > len(maximum) or (len(instance) == len(maximum) and instance > maximum):
            yield ValidationError("Decimal maximum exceeded")


@cache
def _validator(name: str) -> Validator:
    schema = cast(
        dict[str, object],
        json.loads(files("care_link_contracts").joinpath("schema.json").read_text()),
    )
    schema["$ref"] = f"#/$defs/{name}"
    extended = cast(_ValidatorFactories, validators).extend(
        Draft202012Validator, {"x-decimalMaximum": _decimal_maximum}
    )
    return extended(schema, format_checker=FormatChecker())


def _check_json_value(value: object) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeError as error:
            raise ContractError("malformed") from error
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("malformed")
    elif isinstance(value, dict):
        for key, item in cast(Mapping[object, object], value).items():
            if not isinstance(key, str):
                raise ContractError("malformed")
            _check_json_value(key)
            _check_json_value(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            _check_json_value(item)
    elif value is not None and not isinstance(value, (bool, int)):
        raise ContractError("malformed")


def validate_contract(name: str, value: object) -> None:
    """Validate selected closed shapes without granting runtime authority."""
    if name not in CONTRACT_NAMES:
        raise ContractError("unknown_contract")
    try:
        _check_json_value(value)
        if not _validator(name).is_valid(cast(JsonValue, value)):
            raise ContractError("invalid")
    except RecursionError as error:
        raise ContractError("malformed") from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("malformed")
        result[key] = value
    return result


def _reject_constant(_value: str) -> object:
    raise ContractError("malformed")


def parse_contract(name: str, raw: str) -> object:
    """Reject ambiguous JSON before structural and semantic validation."""
    try:
        value: object = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (ValueError, RecursionError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError("malformed") from error
    validate_contract(name, value)
    return value
