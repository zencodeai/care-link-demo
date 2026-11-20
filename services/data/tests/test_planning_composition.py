"""Real PostgreSQL/OPA/journal and signed HTTP ports; provider/mesh are fixtures."""

import base64
import copy
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
import pytest
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_identity import HttpManualIdentity
from care_link_core.planning_http import HttpPlanningGateway
from care_link_data import PostgresStore
from care_link_data.app import SignedGatewaySecurity, create_app
from care_link_data.directory_admission import VerifiedDirectoryAdmission
from care_link_data.values import stamp
from care_link_domain import ManualError
from care_link_identity import Custody, IdentityService, ReceiptSigner, stepup
from care_link_identity.manual_runtime import create_manual_identity_app
from care_link_policy_input import DelegationVerifier, OpaPolicy
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi.testclient import TestClient

from services.data.tests.test_composition import FixtureSecurity, integrated
from services.data.tests.test_directory import feed
from services.data.tests.test_directory_admission import envelope
from services.identity.tests.conftest import FakeProvider, MemoryStore, signed_in

ROOT = Path(__file__).resolve().parents[3]


def policy_for(h, tmp_path):
    channels, _journal, _old_policy = integrated(h, tmp_path)
    executable = Path(os.environ["CARE_LINK_OPA_BINARY"])
    directory = ROOT / "config/demo/imp04/policy"
    manifest = json.loads((directory / "bootstrap.json").read_text())
    policy = OpaPolicy(
        executable,
        hashlib.sha256(executable.read_bytes()).hexdigest(),
        (directory / "manual.rego").read_bytes(),
        manifest["signature"],
        Ed25519PublicKey.from_public_bytes(base64.b64decode(manifest["public_key"])),
    )
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE control.guard SET bundle_digest=%s", (policy.bundle_digest,))
    h.service.policy = policy
    return channels, policy


@contextmanager
def runtime(h, tmp_path):
    channels, policy = policy_for(h, tmp_path)
    key, core_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    provider = FakeProvider(lambda: datetime.now(UTC))
    identity_service = IdentityService(
        MemoryStore(),
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(key, "planning-test"),
        "https://issuer.test",
        "https://manual.test",
    )
    identity_service.provision(provider.subject, h.participant.account_id, ["pid"])
    raw = signed_in(identity_service)
    with TestClient(
        create_manual_identity_app(identity_service, lambda _r, _p: True),
        base_url="https://identity.test",
    ) as identity_client:
        identity = HttpManualIdentity(identity_client, "https://identity.test", key.public_key())
        h.service.authority = identity
        actor = identity.authenticate(raw)
        verifier = DelegationVerifier(core_key.public_key(), key.public_key(), identity.resolve)
        with TestClient(
            create_app(h.service, SignedGatewaySecurity(verifier, lambda _r, _p: True)),
            base_url="https://data.test",
        ) as data_client:
            factory = SignedEnvelopeFactory(
                data_client, "https://data.test", identity, policy, core_key
            )
            gateway = HttpPlanningGateway(data_client, "https://data.test", factory)
            security = FixtureSecurity(actor)
            with TestClient(
                create_manual_app(gateway, security, channels, planning=gateway),
                base_url="https://manual.test",
            ) as bff:
                yield bff, security, identity, identity_service, provider, gateway, factory


def post(client, path, body, key=None):
    return client.post(
        path,
        json=body,
        headers={
            "Origin": "https://manual.test",
            "X-CSRF-Token": "fixture-csrf",
            "Idempotency-Key": key or str(uuid4()),
        },
    )


def test_signed_bff_plan_consent_proof_shared_view_and_revocation(harness, tmp_path):
    h = harness
    with runtime(h, tmp_path) as (client, security, identity, service, provider, gateway, _factory):
        session = gateway.session_create(
            security.actor,
            str(uuid4()),
            {
                "tags": {"environment": "demo", "population": "synthetic"},
                "participant_kind": "pid",
                "jurisdiction": None,
                "locale": "en-CA",
                "channel": "web",
                "persona_id": None,
                "fixture_id": None,
            },
        )
        no_csrf = client.post(
            "/v1/plans",
            json={"subject_id": session["subject_id"], "expected_revision": session["revision"]},
        )
        assert no_csrf.status_code == 403
        create_key = str(uuid4())
        create_body = {
            "subject_id": session["subject_id"],
            "expected_revision": session["revision"],
        }
        created = post(
            client,
            "/v1/plans",
            create_body,
            create_key,
        )
        assert created.status_code == 200, created.text
        plan = created.json()
        path = f"/v1/plans/{plan['id']}/fields"
        for field in ("plan.strategies", "plan.medication_report"):
            result = post(
                client,
                path,
                {
                    "expected_revision": plan["revision"],
                    "field": field,
                    "value": {"kind": "text", "text": "Fictional " + field},
                    "source": None,
                    "safety_relevant": False,
                },
            )
            assert result.status_code == 200, result.text
            plan = result.json()
        replayed = post(client, "/v1/plans", create_body, create_key)
        assert replayed.status_code == 200, replayed.text
        assert replayed.json() == plan
        gateway.session_create(
            security.actor,
            str(uuid4()),
            {
                "tags": {"environment": "demo", "population": "synthetic"},
                "participant_kind": "pid",
                "jurisdiction": None,
                "locale": "en-CA",
                "channel": "web",
                "persona_id": session["subject_id"],
                "fixture_id": None,
            },
        )
        anchored_replay = post(client, "/v1/plans", create_body, create_key)
        assert anchored_replay.status_code == 200, anchored_replay.text
        assert anchored_replay.json() == plan
        current_session = gateway.session_read(security.actor, session["id"])
        report = post(
            client,
            f"/v1/sessions/{session['id']}/assertions",
            {
                "expected_revision": current_session["revision"],
                "subject_id": session["subject_id"],
                "field": "observations",
                "value": {"kind": "text", "text": "Fictional self report"},
                "supersedes_id": None,
                "effective_at": stamp(datetime.now(UTC)),
            },
        )
        assert report.status_code == 200, report.text
        saved = client.get(f"/v1/sessions/{session['id']}/own-reports")
        assert saved.status_code == 200, saved.text
        assert saved.json()["items"][0]["author_id"] == security.actor.account_id
        assert client.get(f"/v1/sessions/{session['id']}/own-reports").json() == saved.json()
        proof = stepup.start(
            service,
            security.actor.credential_ref,
            "test-binding",
            {
                "purpose": "plan_edit",
                "resource_id": session["subject_id"],
                "expected_revision": "1",
            },
        )
        state = parse_qs(urlsplit(proof["authorization_url"]).query)["state"][0]
        _view, replacement, intent = service.callback(state, "fresh-code", "test-binding")
        stepup.confirm(
            service,
            replacement,
            {
                "ceremony_id": proof["ceremony_id"],
                "proof_intent_id": intent,
                "expected_revision": "1",
            },
        )
        security.actor = identity.authenticate(replacement)
        own = security.actor
        current = gateway.session_read(own, session["id"])
        now = datetime.now(UTC)
        result = post(
            client,
            "/v1/consents",
            {
                "subject_id": session["subject_id"],
                "session_id": session["id"],
                "expected_revision": current["revision"],
                "purpose": "plan",
                "recipient": {"kind": "account", "account_id": h.worker.account_id},
                "fields": ["plan.strategies"],
                "basis": "self",
                "authority_proof_id": proof["ceremony_id"],
                "effective_at": stamp(now - timedelta(seconds=1)),
                "expires_at": stamp(now + timedelta(minutes=10)),
            },
        )
        assert result.status_code == 200, result.text
        grant = result.json()
        provider.subject = "worker-subject"
        service.provision(provider.subject, h.worker.account_id, ["worker"])
        security.actor = identity.authenticate(signed_in(service, "worker"))
        shared = client.get(f"/v1/plans/{plan['id']}")
        assert shared.status_code == 200, shared.text
        assert [field["field"] for field in shared.json()["fields"]] == ["plan.strategies"]
        assert client.get(f"/v1/sessions/{session['id']}/own-reports").status_code == 403
        security.actor = own
        revoked = post(
            client, f"/v1/consents/{grant['id']}/revoke", {"expected_revision": grant["revision"]}
        )
        assert revoked.status_code == 200, revoked.text
        provider.subject = "worker-subject"
        security.actor = identity.authenticate(signed_in(service, "worker"))
        assert client.get(f"/v1/plans/{plan['id']}").status_code == 403
        assert h.read("SELECT count(*) FROM consent.event") == [(2,)]


def test_actual_policy_binds_exact_shared_field_recipient_subject_and_grant(
    harness, tmp_path, monkeypatch
):
    from dataclasses import replace

    from services.data.tests.test_plans_consent import create_plan, grant_body

    h = harness
    h.participant = replace(h.participant, mfa=True)
    monkeypatch.setattr(h.authority, "consent_proof", lambda *_args: None, raising=False)
    session, plan = create_plan(h)
    plan = h.service.plan_field_append(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": plan["revision"],
            "field": "plan.strategies",
            "value": {"kind": "text", "text": "Fictional strategy"},
            "source": None,
            "safety_relevant": False,
        },
        plan["id"],
    )
    grant = h.service.consent_grant(h.participant, str(uuid4()), grant_body(h, {}, session))
    _channels, policy = policy_for(h, tmp_path)
    recorded = []
    original = policy.evaluate

    def evaluate(request):
        recorded.append(copy.deepcopy(request))
        return original(request)

    monkeypatch.setattr(policy, "evaluate", evaluate)
    h.service.plan_read(h.worker, plan["id"])
    request = recorded[-1]
    assert request["consent_id"] == grant["id"]
    assert request["scope"]["fields"] == ["plan.strategies"]
    assert request["scope"]["recipient_id"] == h.worker.account_id
    for key, value in [
        ("fields", ["plan.medication_report"]),
        ("recipient_id", str(uuid4())),
        ("subject_id", str(uuid4())),
    ]:
        bad = copy.deepcopy(request)
        bad["scope"][key] = value
        assert original(bad)["decision"] == "DENY"
    bad = copy.deepcopy(request)
    bad["consent_id"] = str(uuid4())
    assert original(bad)["decision"] == "DENY"
    updated = h.service.plan_field_append(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": plan["revision"],
            "field": "plan.contacts",
            "value": {"kind": "text", "text": "Fictional contact"},
            "source": None,
            "safety_relevant": False,
        },
        plan["id"],
    )
    emitted = {field["field"] for field in updated["fields"]}
    assert emitted == {"plan.strategies", "plan.contacts"}
    assert emitted.issubset(recorded[-1]["scope"]["fields"])


def test_actual_directory_policy_binds_source_and_suspension_target(harness, tmp_path):
    from dataclasses import replace

    h = harness
    _channels, policy = policy_for(h, tmp_path)
    data, manifest = feed(datetime.now(UTC))
    source_key = Ed25519PrivateKey.generate()
    h.service.directory_artifacts = VerifiedDirectoryAdmission(
        [envelope(source_key, manifest)], {"test-source-authority": source_key.public_key()}
    ).manifests
    version = h.service.directory_ingest(h.operator, str(uuid4()), data)
    with h.service.store.transaction(h.participant, None) as tx:
        snapshot = h.service._snapshot(tx, h.participant, None)
        request = h.service._policy_input(
            tx,
            h.participant,
            "directory_read",
            str(uuid4()),
            "a" * 64,
            snapshot,
            arguments={"service_id": version["id"]},
        )
    assert policy.evaluate(request)["decision"] == "PERMIT"
    bad = copy.deepcopy(request)
    bad["artifact_digests"] = ["f" * 64]
    assert policy.evaluate(bad)["decision"] == "DENY"
    bad = copy.deepcopy(request)
    bad["versions"]["directory"] = "99"
    assert policy.evaluate(bad)["decision"] == "DENY"
    security = replace(h.supervisor, account_id=str(uuid4()), role="security")
    PostgresStore(h.database.admin).provision_principal(security)
    key = str(uuid4())
    body = {"expected_revision": version["revision"], "reason": "security"}
    h.service.directory_suspend(security, key, body, version["id"])
    assert h.service.directory_read(h.participant, version["id"])["state"] == "suspended"
    data2, manifest2 = feed(datetime.now(UTC))
    data2["feed_artifact_digest"] = "c" * 64
    signed2 = envelope(source_key, manifest2)
    signed2["artifact_digest"] = "c" * 64
    from care_link_data.values import canonical

    signed2["signature"] = (
        base64.urlsafe_b64encode(
            source_key.sign(
                canonical({k: v for k, v in signed2.items() if k != "signature"}).encode()
            )
        )
        .rstrip(b"=")
        .decode()
    )
    h.service.directory_artifacts.update(
        VerifiedDirectoryAdmission(
            [signed2], {"test-source-authority": source_key.public_key()}
        ).manifests
    )
    second = h.service.directory_ingest(h.operator, str(uuid4()), data2)
    with pytest.raises(ManualError, match="idempotency_conflict"):
        h.service.directory_suspend(security, key, body, second["id"])
