"""Adverse wire cases that ordinary schema-only validation would miss."""

import json

import pytest
from care_link_contracts import ContractError, parse_contract, validate_contract

pytestmark = pytest.mark.contract


def test_revision_boundaries_stay_exact_decimal_strings() -> None:
    for revision in ("0", "1", "9223372036854775807"):
        validate_contract("RevisionCommand", {"expected_revision": revision})
    for revision in ("9223372036854775808", "9999999999999999999", "01", "-1", "1\n", 1, True):
        with pytest.raises(ContractError):
            validate_contract("RevisionCommand", {"expected_revision": revision})


def test_nested_closed_schema_prevents_authority_fields() -> None:
    session: dict[str, object] = {
        "tags": {"environment": "demo", "population": "synthetic"},
        "participant_kind": "pid",
        "jurisdiction": None,
        "locale": "en-CA",
        "channel": "web",
        "persona_id": None,
        "fixture_id": None,
    }
    assert parse_contract("SessionCreate", json.dumps(session)) == session
    session["tags"] = {"environment": "demo", "population": "synthetic", "is_admin": True}
    with pytest.raises(ContractError, match="invalid"):
        parse_contract("SessionCreate", json.dumps(session))


@pytest.mark.parametrize(
    "raw",
    [
        '{"expected_revision":"1","expected_revision":"2"}',
        '{"expected_revision":"1","nested":{"a":1,"\\u0061":2}}',
        '{"expected_revision":NaN}',
        '{"expected_revision":Infinity}',
        '{"expected_revision":1e999}',
        '{"expected_revision":"\\ud800"}',
        '{"\\udfff":"1"}',
        '{"expected_revision":"1"} trailing',
        '{"expected_revision":',
    ],
)
def test_ambiguous_or_non_json_wire_values_are_malformed(raw: str) -> None:
    with pytest.raises(ContractError, match="malformed"):
        parse_contract("RevisionCommand", raw)


def test_valid_surrogate_pair_is_preserved_but_unpaired_values_are_rejected() -> None:
    with pytest.raises(ContractError, match="invalid"):
        parse_contract("RevisionCommand", '{"expected_revision":"\\ud83d\\ude00"}')
    with pytest.raises(ContractError, match="malformed"):
        validate_contract("RevisionCommand", {"expected_revision": "\ud800"})


def test_unknown_contract_cannot_be_interpreted_as_an_operation() -> None:
    with pytest.raises(ContractError, match="unknown_contract"):
        parse_contract("ExecuteSql", "{}")


def test_non_json_python_values_are_rejected_without_serialization_coercion() -> None:
    for value in ({1: "revision"}, {"expected_revision": float("nan")}, ("1",)):
        with pytest.raises(ContractError, match="malformed"):
            validate_contract("RevisionCommand", value)


def test_boolean_constants_never_accept_equal_integer_values() -> None:
    capability: dict[str, object] = {
        "contract_version": "dev-1",
        "status": "developer_only",
        "tags": {"environment": "demo", "population": "synthetic"},
        "participant_admission": False,
        "business_operations": "unavailable",
        "contract_validation": True,
    }
    validate_contract("DeveloperCapability", capability)
    capability["participant_admission"] = 0
    with pytest.raises(ContractError, match="invalid"):
        validate_contract("DeveloperCapability", capability)
    capability["participant_admission"] = False
    capability["contract_validation"] = 1
    with pytest.raises(ContractError, match="invalid"):
        validate_contract("DeveloperCapability", capability)
