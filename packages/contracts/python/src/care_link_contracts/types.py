"""Typed developer transport results; shared contracts contain no authority."""

from typing import Literal, TypedDict


class DemoTags(TypedDict):
    environment: Literal["demo"]
    population: Literal["synthetic"]


class DeveloperCapability(TypedDict):
    contract_version: Literal["dev-1"]
    status: Literal["developer_only"]
    tags: DemoTags
    participant_admission: Literal[False]
    business_operations: Literal["unavailable"]
    contract_validation: Literal[True]


class ErrorEnvelope(TypedDict):
    code: Literal["INVALID_REQUEST", "CAPABILITY_DISABLED", "NOT_FOUND"]
    request_id: str
    retryable: bool
    message_key: str
    operation_id: None
    retry_after_ms: None
