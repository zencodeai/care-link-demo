"""Real PG/OPA/journal and signed remote-port composition.

HTTP uses TestClient; provider/workload provenance are explicit fixtures. This
proves adapter compatibility, not deployed SVID or live browser qualification.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_http import HttpManualGateway
from care_link_core.manual_identity import HttpManualIdentity
from care_link_data.app import SignedGatewaySecurity, create_app
from care_link_domain import ManualError
from care_link_identity import Custody, IdentityService, ReceiptSigner
from care_link_identity.manual_runtime import create_manual_identity_app
from care_link_policy_input import DelegationVerifier
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from services.data.tests.test_composition import integrated
from services.identity.tests.conftest import FakeProvider, MemoryStore, signed_in


def test_real_signed_metadata_and_final_gateway_with_current_identity(harness, tmp_path):
    h = harness
    _channels, _journal, policy = integrated(h, tmp_path)
    key, core_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    provider = FakeProvider(lambda: datetime.now(UTC))
    service = IdentityService(
        MemoryStore(),
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(key, "runtime-test"),
        "https://issuer.test",
        "https://manual.test",
    )
    service.provision(provider.subject, h.participant.account_id, ["pid"])
    raw = signed_in(service)
    # Workload seam is deliberately named/labelled; only the live listener
    # qualification can establish actual kernel UID/proxy/SVID/fence provenance.
    with TestClient(
        create_manual_identity_app(service, lambda _request, _peer: True),
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
            gateway = HttpManualGateway(data_client, "https://data.test", factory)
            session = gateway.session_create(
                actor,
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
            sid = str(session["id"])
            assert gateway.session_read(actor, sid)["id"] == sid
            queue = gateway.session_human_request(
                actor,
                str(uuid4()),
                {
                    "expected_revision": session["revision"],
                    "reason": "user_requested",
                },
                sid,
            )
            assert queue["state"] == "pending"
            assert gateway.messages_read(actor, sid) == {"items": [], "next_cursor": None}
            assert (
                h.read("SELECT count(*) FROM audit.event WHERE action='authority_metadata'")[0][0]
                == 4
            )
            assert h.read("SELECT count(*) FROM workforce.queue_entry")[0][0] == 1
            assert gateway.session_events(actor, sid, 0)
            event_key = str(uuid4())
            event_envelope = factory.build(
                actor,
                "session_events",
                event_key,
                {"last_event_id": "0"},
                {"session_id": sid},
            )
            mismatched_cursor = data_client.post(
                "https://data.test/internal/v1/data/session_events",
                json=event_envelope,
                headers={"Idempotency-Key": event_key, "Last-Event-ID": "1"},
            )
            assert mismatched_cursor.status_code == 400
            event_envelope["arguments"]["last_event_id"] = "1"
            tampered_cursor = data_client.post(
                "https://data.test/internal/v1/data/session_events",
                json=event_envelope,
                headers={"Idempotency-Key": event_key},
            )
            assert tampered_cursor.status_code == 403
            # Each new protected request rechecks the actual adapter's provider
            # callback; a prior receipt never keeps a disabled session current.
            provider.is_active = False
            with pytest.raises(ManualError):
                gateway.session_read(actor, sid)
            assert h.read("SELECT count(*) FROM workforce.queue_entry")[0][0] == 1
