"""Public origin metadata never reveals unauthenticated scenario handles."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_core.plans_review_context import PlansReviewContexts
from care_link_domain import Actor, ManualError


@pytest.fixture
def context(tmp_path):
    now = datetime(2026, 11, 17, tzinfo=UTC)
    run = str(uuid4())
    host = f"r{run.replace('-', '')}-pid.plans.localhost:30443"
    row = {
        "mode": "plans",
        "authentication_mode": "automatic_review",
        "environment": "synthetic-review",
        "run_id": run,
        "slot_id": "pid",
        "account_id": str(uuid4()),
        "role": "pid",
        "provider_subject": str(uuid4()),
        "state": "active",
        "started_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "session_id": str(uuid4()),
        "plan_id": str(uuid4()),
        "recipient_id": str(uuid4()),
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"https://" + host: row}))
    reader = PlansReviewContexts(path, "https://legacy.localhost", clock=lambda: now)
    actor = Actor(
        account_id=row["account_id"],
        role="pid",
        identity_revision=1,
        role_revision=1,
        auth_time=now,
        mfa=True,
        browser_session_digest="0" * 64,
        transport_generation=1,
        credential_ref="not-a-real-credential",
        expires_at=now + timedelta(hours=2),
        identity_evidence_id=str(uuid4()),
        review_run_id=run,
        review_slot_id="pid",
        review_origin="https://" + host,
    )
    return reader, path, row, actor, host


def test_public_context_hides_handles_and_selection_requires_exact_actor(context):
    reader, _path, row, actor, host = context
    public = reader.context(host)
    assert public["authentication_mode"] == "automatic_review"
    assert public["mode"] == "plans"
    assert not {"session_id", "plan_id", "recipient_id", "provider_subject"} & public.keys()
    assert reader.selection(host, actor) == {
        key: row[key] for key in ("session_id", "plan_id", "recipient_id")
    }
    for change in (
        {"account_id": str(uuid4())},
        {"role": "worker"},
        {"review_run_id": str(uuid4())},
        {"review_origin": "https://foreign.localhost"},
        {"review_slot_id": "carer"},
    ):
        with pytest.raises(ManualError):
            reader.selection(host, replace(actor, **change))
    assert reader.context("legacy.localhost") == {"enabled": False}


@pytest.mark.parametrize(
    "change",
    [
        {"state": "closing"},
        {"state": "closed"},
        {"expires_at": "2026-11-17T00:00:00Z", "started_at": "2026-11-16T23:00:00Z"},
    ],
)
def test_nonactive_context_never_selects(context, change):
    reader, path, row, actor, host = context
    row.update(change)
    path.write_text(json.dumps({"https://" + host: row}))
    with pytest.raises(ManualError):
        reader.selection(host, actor)


@pytest.mark.parametrize(
    "change",
    [
        {"extra": "authority"},
        {"environment": "live"},
        {"role": "operator"},
        {"authentication_mode": "provider"},
        {"provider_subject": "not-a-uuid"},
        {"expires_at": "2026-11-17T04:00:01Z"},
    ],
)
def test_malformed_registry_is_rejected(context, change):
    reader, path, row, _actor, host = context
    row.update(change)
    path.write_text(json.dumps({"https://" + host: row}))
    with pytest.raises(ManualError):
        reader.context(host)


@pytest.mark.parametrize(
    "bad",
    [
        "https://evil.test",
        "https://rwrong-pid.plans.localhost",
        "https://{host}/",
        "https://{host}:0",
        "https://{host}?x=1",
    ],
)
def test_origin_cannot_be_substituted(context, bad):
    reader, path, row, _actor, host = context
    origin = bad.format(host=host)
    path.write_text(json.dumps({origin: row}))
    with pytest.raises(ManualError):
        reader.entries()
