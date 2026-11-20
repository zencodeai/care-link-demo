"""Exact-scope absence classification; mocks never substitute for live DB evidence."""

import copy
import json
from uuid import uuid4

import pytest

from tools.imp04_verification import live_database as db


def scenario(*, rejected=False):
    identifiers = {
        key: str(uuid4())
        for key in ["operation", "subject", "recipient", "prior_grant", "session", "grantor"]
    }
    prior = {
        "grant_id": identifiers["prior_grant"],
        "subject_id": identifiers["subject"],
        "recipient_id": identifiers["recipient"],
        "recipient_kind": "account",
        "purpose": "plan",
        "fields": ["plan.strategies"],
        "session_id": identifiers["session"],
        "grantor_id": identifiers["grantor"],
        "revoked_at": "2026-11-16T00:00:00Z",
    }
    operation = {"row_count": 0, "record": None}
    if rejected:
        operation = {
            "row_count": 1,
            "record": {
                "operation_id": identifiers["operation"],
                "operation_name": "consent_grant",
                "state": "rejected",
                "resource_id": None,
                "session_id": identifiers["session"],
                "principal_id": identifiers["grantor"],
            },
        }
    selected = {
        "absent_operation": operation,
        "absent_scope": {
            "subject_id": identifiers["subject"],
            "recipient_id": identifiers["recipient"],
            "prior_grant_id": identifiers["prior_grant"],
            "purpose": "plan",
            "prior_grant": {"row_count": 1, "record": prior},
            "prior_grant_created_event_count": 1,
            "prior_grant_revoked_event_count": 1,
            "other_scope_grant_count": 0,
            "other_subject_grant_event_count": 0,
            "pending_operation_grant_count": 0,
            "pending_operation_grant_event_count": 0,
            "pending_operation_permit_audit_count": 0,
        },
    }
    return identifiers, selected


@pytest.mark.parametrize("rejected", [False, True])
def test_exact_scope_proof_accepts_preflight_absence_or_rejected_command(rejected):
    identifiers, selected = scenario(rejected=rejected)
    assert (
        db.absent_scope_failures(
            selected,
            **{
                key: identifiers[key]
                for key in ["operation", "subject", "recipient", "prior_grant"]
            },
        )
        == []
    )


@pytest.mark.parametrize(
    "counter",
    [
        "other_scope_grant_count",
        "other_subject_grant_event_count",
        "pending_operation_grant_count",
        "pending_operation_grant_event_count",
        "pending_operation_permit_audit_count",
    ],
)
def test_missing_operation_does_not_hide_an_actual_scope_or_correlated_effect(counter):
    identifiers, selected = scenario()
    selected["absent_scope"][counter] = 1
    assert db.absent_scope_failures(
        selected,
        **{key: identifiers[key] for key in ["operation", "subject", "recipient", "prior_grant"]},
    )


@pytest.mark.parametrize(
    "change",
    [
        "committed",
        "resource",
        "operation",
        "principal",
        "session",
        "not_revoked",
        "prior_missing",
        "prior_subject",
        "prior_recipient",
        "broader_prior",
        "grant_event_missing",
        "revoke_event_missing",
    ],
)
def test_no_committed_or_mismatched_record_can_qualify_as_absence(change):
    identifiers, selected = scenario(rejected=True)
    operation = selected["absent_operation"]["record"]
    scope = selected["absent_scope"]
    prior = scope["prior_grant"]["record"]
    if change == "committed":
        operation["state"] = "committed"
    elif change == "resource":
        operation["resource_id"] = str(uuid4())
    elif change in {"operation", "principal", "session"}:
        operation[
            {"operation": "operation_id", "principal": "principal_id", "session": "session_id"}[
                change
            ]
        ] = str(uuid4())
    elif change == "not_revoked":
        prior["revoked_at"] = None
    elif change == "prior_missing":
        scope["prior_grant"] = {"row_count": 0, "record": None}
    elif change in {"prior_subject", "prior_recipient"}:
        prior[{"prior_subject": "subject_id", "prior_recipient": "recipient_id"}[change]] = str(
            uuid4()
        )
    elif change == "broader_prior":
        prior["fields"] = ["plan.strategies", "plan.medication_report"]
    else:
        scope[
            {
                "grant_event_missing": "prior_grant_created_event_count",
                "revoke_event_missing": "prior_grant_revoked_event_count",
            }[change]
        ] = 0
    assert db.absent_scope_failures(
        selected,
        **{key: identifiers[key] for key in ["operation", "subject", "recipient", "prior_grant"]},
    )


def mocked_docker(monkeypatch, selected):
    metadata = {
        "flags": [False] * 4,
        "counts": {},
        "anchors": [0, 0, 0],
        "rls": [[name, True, True] for name in ["current_grant", "field", "plan"]],
        "plan_copy_metadata": [],
        "pending_review_counts": [],
        "control_metadata": [],
        "selected_effect_metadata": selected,
    }
    scripts = []
    calls = []
    selector_calls = []

    def execute(name, argv, **_kwargs):
        scripts.append(argv[2])
        compile(argv[2], "remote-selector-probe", "exec")
        if name.endswith("-data-app"):
            return json.dumps(
                [{"probe": item[0], "permission_denied": True} for item in json.loads(argv[3])]
            )
        assert name == "care-link-imp04-002-operator-seed"
        selectors = json.loads(argv[3])
        selector_calls.append(selectors)
        return json.dumps(metadata)

    monkeypatch.setattr(db.docker, "exec", execute)
    monkeypatch.setattr(db.docker, "start", lambda name: calls.append(("start", name)))
    monkeypatch.setattr(db.docker, "stop", lambda name: calls.append(("stop", name)))
    return calls, scripts, selector_calls


def test_new_selector_combination_proves_scope_while_old_strict_mode_is_unchanged(monkeypatch):
    identifiers, selected = scenario()
    calls, scripts, selector_calls = mocked_docker(monkeypatch, selected)
    new = db.verify(
        absent_operation=identifiers["operation"],
        absent_subject=identifiers["subject"],
        absent_recipient=identifiers["recipient"],
        absent_prior_grant=identifiers["prior_grant"],
    )
    assert new["status"] == "passed"
    assert new["selected_effect_metadata"] == selected
    assert selector_calls[0] == {
        "operation": None,
        "field": None,
        "absent_operation": identifiers["operation"],
        "absent_subject": identifiers["subject"],
        "absent_recipient": identifiers["recipient"],
        "absent_prior_grant": identifiers["prior_grant"],
    }
    old = db.verify(absent_operation=identifiers["operation"])
    assert old["status"] == "failed"
    assert "absent_operation_not_rejected_without_resource" in old["failures"]
    assert calls == [
        (action, "care-link-imp04-002-operator-seed")
        for action in ["start", "stop", "start", "stop"]
    ]
    assert "SET TRANSACTION READ ONLY" in scripts[-1]
    assert "consent.event has no operation_id" in scripts[-1]


@pytest.mark.parametrize(
    "selectors",
    [
        {"absent_subject": str(uuid4())},
        {"absent_operation": str(uuid4()), "absent_subject": str(uuid4())},
        {
            "absent_operation": str(uuid4()),
            "absent_subject": str(uuid4()),
            "absent_recipient": str(uuid4()),
        },
        {
            "absent_subject": str(uuid4()),
            "absent_recipient": str(uuid4()),
            "absent_prior_grant": str(uuid4()),
        },
        {"absent_operation": "NOT-A-CANONICAL-UUID"},
        {"absent_operation": str(uuid4()), "absent_subject": "NOT-A-CANONICAL-UUID"},
    ],
)
def test_incomplete_or_noncanonical_selectors_fail_before_any_docker(monkeypatch, selectors):
    monkeypatch.setattr(db.docker, "exec", lambda *_a, **_k: pytest.fail("must not execute"))
    monkeypatch.setattr(db.docker, "start", lambda *_a, **_k: pytest.fail("must not start"))
    with pytest.raises(ValueError):
        db.verify(**selectors)


def test_selected_input_is_not_modified_by_absence_classification():
    identifiers, selected = scenario(rejected=True)
    before = copy.deepcopy(selected)
    assert (
        db.absent_scope_failures(
            selected,
            **{
                key: identifiers[key]
                for key in ["operation", "subject", "recipient", "prior_grant"]
            },
        )
        == []
    )
    assert selected == before
