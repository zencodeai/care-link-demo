"""Recovery routing uses current server identity and authorized gateway reads."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_core.plans_review_context import PlansReviewContexts
from care_link_domain import Actor
from fastapi.testclient import TestClient


def setup(tmp_path):
    now = datetime.now(UTC)
    run, account, sid, plan, recipient = (str(uuid4()) for _ in range(5))
    origin = f"https://r{run.replace('-', '')}-pid.plans.localhost"
    actor = Actor(
        account,
        "pid",
        1,
        1,
        now,
        False,
        "a" * 64,
        1,
        "opaque",
        now + timedelta(hours=1),
        str(uuid4()),
        review_run_id=run,
        review_slot_id="pid",
        review_origin=origin,
    )
    entry = {
        "mode": "plans",
        "authentication_mode": "automatic_review",
        "environment": "synthetic-review",
        "run_id": run,
        "slot_id": "pid",
        "account_id": account,
        "provider_subject": str(uuid4()),
        "role": "pid",
        "state": "active",
        "started_at": (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "session_id": sid,
        "plan_id": plan,
        "recipient_id": recipient,
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({origin: entry}))
    contexts = PlansReviewContexts(path, "https://legacy.test")
    security, gateway = Mock(), Mock()
    security.authenticate.return_value = actor
    conversation = {
        "id": sid,
        "revision": "1",
        "tags": {"environment": "demo", "population": "synthetic"},
        "participant_kind": "pid",
        "jurisdiction": None,
        "locale": "en-CA",
        "service_phase": "active",
        "transport": "connected",
        "control_epoch": "0",
        "owner_id": None,
        "degraded_reasons": ["ai_unavailable"],
        "tier": None,
        "unresolved": True,
        "persona_id": str(uuid4()),
        "subject_id": str(uuid4()),
    }
    gateway.review_workspace.return_value = {
        "run_id": run,
        "run_state": "active",
        "conversations": [conversation],
        "conversation": conversation,
        "assignment": None,
        "drafts": [],
        "pending_intents": [],
        "handshake": None,
        "disclosure_acknowledged": True,
        "intake_submitted": False,
        "interrupt_expires_at": None,
    }
    app = create_manual_app(
        gateway,
        security,
        ManualChannels(),
        review_contexts=contexts,
        plans_review_contexts=contexts,
    )
    return TestClient(app, base_url=origin), path, entry, actor, security, gateway


def test_default_off_public_context_contains_no_private_selection():
    gateway = Mock()
    client = TestClient(create_manual_app(gateway, Mock(), ManualChannels()))
    assert client.get("/v1/plans-review/context").json() == {"enabled": False}
    assert client.get("/v1/plans-review/workspace").status_code == 404
    gateway.review_workspace.assert_not_called()


def test_recovery_uses_registry_selection_and_current_gateway_projection(tmp_path):
    client, _path, entry, actor, security, gateway = setup(tmp_path)
    public = client.get("/v1/plans-review/context")
    assert public.status_code == 200
    assert public.json()["authentication_mode"] == "automatic_review"
    assert not {"session_id", "plan_id", "recipient_id", "provider_subject"} & public.json().keys()
    security.authenticate.assert_not_called()
    result = client.get("/v1/plans-review/workspace")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["selection"] == {
        key: entry[key] for key in ("session_id", "plan_id", "recipient_id")
    }
    called_actor, called_session = gateway.review_workspace.call_args.args
    assert called_session == entry["session_id"]
    assert called_actor.account_id == actor.account_id


@pytest.mark.parametrize("change", ["actor", "run", "projection", "closed", "query"])
def test_recovery_refuses_mismatched_or_stale_context(tmp_path, change):
    client, path, entry, actor, security, gateway = setup(tmp_path)
    if change == "actor":
        security.authenticate.return_value = replace(actor, account_id=str(uuid4()))
    elif change == "run":
        security.authenticate.return_value = replace(actor, review_run_id=str(uuid4()))
    elif change == "projection":
        gateway.review_workspace.return_value["conversation"]["id"] = str(uuid4())
    elif change == "closed":
        entry["state"] = "closed"
        path.write_text(json.dumps({actor.review_origin: entry}))
    response = client.get(
        "/v1/plans-review/workspace" + ("?session_id=" + str(uuid4()) if change == "query" else "")
    )
    assert response.status_code in {400, 403}
    assert "selection" not in response.json()
    if change != "projection":
        gateway.review_workspace.assert_not_called()
