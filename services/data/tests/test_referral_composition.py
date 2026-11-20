"""Signed HTTP referral composition; real OPA/DB, provider and mesh are fixtures."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_identity import HttpManualIdentity
from care_link_core.referral_http import HttpReferralGateway
from care_link_data.app import SignedGatewaySecurity, create_app
from care_link_data.values import stamp
from care_link_domain import ManualError
from care_link_identity import Custody, IdentityService, ReceiptSigner
from care_link_identity.manual_runtime import create_manual_identity_app
from care_link_policy_input import DelegationVerifier
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from services.data.tests.test_referrals import opa_referral_case as base_opa_case
from services.data.tests.test_referrals import referral_harness as base_referral_harness
from services.identity.tests.conftest import FakeProvider, MemoryStore, signed_in

opa_referral_case = base_opa_case
referral_harness = base_referral_harness


def test_signed_referral_read_review_send_reconcile_and_tamper_denials(opa_referral_case):
    (
        h,
        receiver,
        receiver_actor,
        session,
        original_draft,
        _consent,
        _review,
        _enqueue,
        draft_body,
        _,
    ) = opa_referral_case
    identity_key, core_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    provider = FakeProvider(lambda: datetime.now(UTC))
    identity_service = IdentityService(
        MemoryStore(),
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(identity_key, "referral-composition-test"),
        "https://issuer.test",
        "https://manual.test",
    )
    identity_service.provision(provider.subject, h.worker.account_id, ["worker"])
    raw = signed_in(identity_service, "worker")
    with TestClient(
        create_manual_identity_app(identity_service, lambda _r, _p: True),
        base_url="https://identity.test",
    ) as identity_client:
        identity = HttpManualIdentity(
            identity_client, "https://identity.test", identity_key.public_key()
        )
        h.service.authority = identity
        actor = identity.authenticate(raw)
        verifier = DelegationVerifier(
            core_key.public_key(), identity_key.public_key(), identity.resolve
        )
        with TestClient(
            create_app(h.service, SignedGatewaySecurity(verifier, lambda _r, _p: True)),
            base_url="https://data.test",
        ) as data_client:
            factory = SignedEnvelopeFactory(
                data_client, "https://data.test", identity, h.service.policy, core_key
            )
            gateway = HttpReferralGateway(data_client, "https://data.test", factory)
            # Exact metadata targets and resolved scope cross real signed adapters.
            assert (
                gateway.referral_read(actor, original_draft["id"])["digest"]
                == original_draft["digest"]
            )
            context = gateway.referral_context(actor, original_draft["id"])
            assert context["review"]["reviewer_id"] == actor.account_id
            sources = gateway.referral_sources(actor, session["id"])
            assert {entry["selected"]["field"] for entry in sources["items"]} == {
                "needs",
                "preferences",
            }
            current = gateway.session_read(actor, session["id"])
            body = {**draft_body, "expected_revision": current["revision"]}
            draft = gateway.referral_draft(actor, str(uuid4()), body, session["id"])
            context = gateway.referral_context(actor, draft["id"])
            review = gateway.referral_review(
                actor,
                str(uuid4()),
                {
                    "expected_revision": draft["revision"],
                    "draft_id": draft["id"],
                    "exact_digest": draft["digest"],
                    "source_vector": context["versions"],
                    "decision": "accept",
                    "edited_text": None,
                    "expires_at": stamp(datetime.now(UTC) + timedelta(seconds=60)),
                },
                draft["id"],
            )
            draft = gateway.referral_read(actor, draft["id"])
            pending = gateway.referral_dispatch(
                actor,
                str(uuid4()),
                {
                    "expected_revision": draft["revision"],
                    "consent_id": draft["consent_id"],
                    "review_id": review["id"],
                    "exact_payload_digest": draft["digest"],
                    "generation": draft["generation"],
                },
                draft["id"],
            )
            assert pending["state"] == "pending"
            received = gateway.dispatcher_send(
                actor,
                str(uuid4()),
                {"expected_revision": pending["revision"]},
                pending["dispatch_id"],
            )
            assert received["state"] == "received"
            receiver.receiver_decide(
                receiver_actor,
                str(uuid4()),
                {
                    "expected_revision": "1",
                    "dispatch_id": received["dispatch_id"],
                    "payload_digest": draft["digest"],
                    "decision": "partial",
                    "accepted_fields": ["needs"],
                    "reason": "capacity",
                },
            )
            reconciled = gateway.dispatch_reconcile(
                actor,
                str(uuid4()),
                {"expected_revision": received["revision"]},
                received["dispatch_id"],
            )
            assert reconciled["state"] == "partial"
            assert gateway.receipt_read(actor, reconciled["dispatch_id"])["accepted_fields"] == [
                "needs"
            ]
            assert gateway.dispatch_read(actor, reconciled["dispatch_id"])["attempt_count"] == 1
            assert h.read("SELECT count(*) FROM referral.attempt") == [(1,)]
            assert h.read(
                "SELECT purpose,anchor_kind,state FROM lifecycle.copy "
                "WHERE aggregate_type='referral'"
            ) == [
                ("referral", "referral_terminal_parent", "anchor_pending"),
                ("referral", "referral_terminal_parent", "anchor_pending"),
            ]
            with receiver.connection() as connection:
                copies = connection.execute(
                    "SELECT purpose,anchor_kind,state,retention_days FROM receiver.copy"
                ).fetchall()
            assert [
                (row["purpose"], row["anchor_kind"], row["state"], row["retention_days"])
                for row in copies
            ] == [("referral", "parent_and_delivery_terminal", "anchor_pending", 7)]

            key = str(uuid4())
            signed = factory.build(actor, "referral_read", key, {}, {"referral_id": draft["id"]})
            # Same shape on another operation path still fails signed action/path binding.
            wrong_path = data_client.post(
                "/internal/v1/data/referral_context", json=signed, headers={"Idempotency-Key": key}
            )
            assert wrong_path.status_code == 403
            wrong_id = deepcopy(signed)
            wrong_id["path_arguments"]["referral_id"] = str(uuid4())
            forged_path = data_client.post(
                "/internal/v1/data/referral_read", json=wrong_id, headers={"Idempotency-Key": key}
            )
            assert forged_path.status_code == 403
            forged_key = str(uuid4())
            forged_fields = factory.build(
                actor, "referral_draft", forged_key, body, {"session_id": session["id"]}
            )
            forged_fields["arguments"]["selected"][0]["source"]["digest"] = "f" * 64
            denied = data_client.post(
                "/internal/v1/data/referral_draft",
                json=forged_fields,
                headers={"Idempotency-Key": forged_key},
            )
            assert denied.status_code == 403
            assert h.read("SELECT count(*) FROM referral.generation") == [(2,)]


def test_receiver_identity_expiring_during_final_write_rolls_back_decision(
    opa_referral_case, monkeypatch
):
    h, receiver, actor, _session, draft, _consent, _review, enqueue, *_ = opa_referral_case
    pending = h.service.referral_dispatch(h.worker, str(uuid4()), enqueue, draft["id"])
    received = h.service.dispatcher_send(
        h.worker, str(uuid4()), {"expected_revision": pending["revision"]}, pending["dispatch_id"]
    )
    original_connection, original_clock = receiver.connection, receiver.clock

    @contextmanager
    def delayed_connection():
        with original_connection() as connection:

            class DelayedWrite:
                def execute(self, statement, parameters=None):
                    result = connection.execute(statement, parameters)
                    if str(statement).startswith("INSERT INTO receiver.decision"):
                        receiver.clock = lambda: actor.auth_time + timedelta(minutes=5)
                    return result

            yield DelayedWrite()

    monkeypatch.setattr(receiver, "connection", delayed_connection)
    try:
        with pytest.raises(ManualError, match="service_authority_required"):
            receiver.receiver_decide(
                actor,
                str(uuid4()),
                {
                    "expected_revision": "1",
                    "dispatch_id": received["dispatch_id"],
                    "payload_digest": draft["digest"],
                    "decision": "reject",
                    "accepted_fields": [],
                    "reason": "capacity",
                },
            )
    finally:
        receiver.clock = original_clock
    with original_connection() as connection:
        assert (
            connection.execute("SELECT count(*) AS count FROM receiver.decision").fetchone()[
                "count"
            ]
            == 0
        )
        row = connection.execute("SELECT revision,receipt FROM receiver.package").fetchone()
    assert row["revision"] == 1 and row["receipt"]["status"] == "received"
