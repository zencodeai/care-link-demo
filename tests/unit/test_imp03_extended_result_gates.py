"""Browser success alone cannot satisfy durable/control observation gates."""

import pytest

from tools.imp03_shared import continuation_browser, continuation_evidence, operations


@pytest.mark.parametrize("case", ["commit-ack", "revocation"])
@pytest.mark.parametrize("effects_ok", [False, True])
def test_case_result_requires_durable_observations(case, effects_ok):
    value = {"case": case, "exit_code": 0, "audit_valid": True}
    if case == "commit-ack":
        value["exactly_one_durable_effect"] = effects_ok
    else:
        value["effect_comparison"] = {"no_prohibited_observed_effect": effects_ok}
    assert continuation_browser.verified(value) is effects_ok
    value["audit_valid"] = False
    assert not continuation_browser.verified(value)


def test_operations_rejects_browser_success_with_live_backend_or_changed_rows():
    value = {
        "exit_code": 0,
        "stop_exit_code": 143,
        "core_container_id_preserved": True,
        "business_rows_preserved": True,
        "audit_chain_valid": True,
        "stopped_backend": {"backend_accepts_connection": False, "connect_errno": 111},
    }
    assert operations.verified(value)
    assert not operations.verified({**value, "stop_exit_code": 137})
    for field in ("core_container_id_preserved", "business_rows_preserved", "audit_chain_valid"):
        bad = {**value, field: False}
        assert not operations.verified(bad)
    assert not operations.verified(
        {
            **value,
            "stopped_backend": {
                "backend_accepts_connection": True,
                "connect_errno": 0,
            },
        }
    )


def test_capture_completion_requires_quarantine_and_unchanged_source():
    value = {
        "quarantine_import": {
            "state": "quarantined_unvalidated",
            "serving_allowed": False,
            "audit_chain_valid": True,
        },
        "source_unchanged": {"no_prohibited_observed_effect": True},
        "serving_promotion": False,
    }
    assert continuation_evidence.verified_capture(value)
    assert not continuation_evidence.verified_capture(
        {
            **value,
            "source_unchanged": {"no_prohibited_observed_effect": False},
        }
    )
    assert not continuation_evidence.verified_capture(
        {
            **value,
            "quarantine_import": {"state": "serving", "serving_allowed": True},
        }
    )
    assert not operations.verified(
        {
            **value,
            "stopped_backend": {
                "backend_accepts_connection": False,
                "connect_errno": 13,
            },
        }
    )
