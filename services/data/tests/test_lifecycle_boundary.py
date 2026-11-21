"""Populated rights through real ceremony, signed adapters, OPA and PostgreSQL.

The OIDC provider, identity storage and mesh connection are synthetic fixtures;
ceremony logic, identity evidence signatures, policy and business database are real.
"""

import base64
import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from care_link_core.lifecycle_http import HttpLifecycleGateway
from care_link_core.manual_envelopes import SignedEnvelopeFactory
from care_link_core.manual_identity import HttpManualIdentity
from care_link_data.app import SignedGatewaySecurity, create_app
from care_link_domain import ManualError
from care_link_identity import Custody, IdentityService, ReceiptSigner, stepup
from care_link_identity.manual_runtime import create_manual_identity_app
from care_link_policy_input import DelegationVerifier, OpaPolicy
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from services.identity.tests.conftest import Clock, FakeProvider, MemoryStore, signed_in

ROOT = Path(__file__).resolve().parents[3]


def confirm(service, ceremony):
    state = parse_qs(urlsplit(ceremony["authorization_url"]).query)["state"][0]
    _view, raw, proof = service.callback(state, "synthetic-second-factor", "test-binding")
    assert raw is not None and proof is not None
    result = stepup.confirm(
        service,
        raw,
        {
            "ceremony_id": ceremony["ceremony_id"],
            "proof_intent_id": proof,
            "expected_revision": "1",
        },
    )
    return raw, result


def test_populated_export_through_real_mfa_signed_identity_opa_and_gateway(harness):
    binary = os.environ.get("CARE_LINK_OPA_BINARY")
    if not binary:
        pytest.skip("Explicit pinned OPA required for integrated signed rights verification")
    h = harness
    session = h.create()
    own = h.service.session_assertions(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": session["revision"],
            "subject_id": session["subject_id"],
            "field": "needs",
            "supersedes_id": None,
            "effective_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "value": {"kind": "text", "text": "Synthetic own report"},
        },
        session["id"],
    )
    current_session = h.service.session_read(h.participant, session["id"])
    other = h.service.session_assertions(
        h.participant,
        str(uuid4()),
        {
            "expected_revision": current_session["revision"],
            "subject_id": session["subject_id"],
            "field": "observations",
            "supersedes_id": None,
            "effective_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "value": {"kind": "text", "text": "Synthetic other author private report"},
        },
        session["id"],
    )
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE core.assertion SET author_id=%s WHERE id=%s", (h.worker.account_id, other["id"])
        )
    clock, storage = Clock(), MemoryStore()
    clock.now -= timedelta(seconds=301)
    provider = FakeProvider(clock)
    identity_key, core_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    identity = IdentityService(
        storage,
        provider,
        Custody(Fernet.generate_key()),
        ReceiptSigner(identity_key, "synthetic"),
        "https://issuer.test",
        "https://app.test",
        clock,
    )
    identity.provision(provider.subject, h.participant.account_id, ["pid"])
    raw = signed_in(identity)
    request = {"purpose": "export", "resource_id": session["subject_id"], "expected_revision": "1"}
    first = stepup.start(identity, raw, "test-binding", request)
    raw, cooling = confirm(identity, first)
    assert cooling["state"] == "cooling_off"
    clock.advance(301)
    second = stepup.start(identity, raw, "test-binding", request)
    raw, proof = confirm(identity, second)
    assert proof["state"] == "verified" and first["ceremony_id"] == second["ceremony_id"]
    # Wall-clock security resumes after the explicit synthetic ceremony timeline.
    identity.clock = lambda: datetime.now(UTC)
    identity_client = TestClient(
        create_manual_identity_app(identity, lambda r, p: r.headers.get("x-peer") == p)
    )

    def identity_transport(request):
        name = request.url.path.rsplit("/", 1)[-1]
        peer = "core" if name in {"authenticate", "evidence", "csrf"} else "data"
        result = identity_client.post(
            request.url.path,
            content=request.content,
            headers={"Content-Type": "application/json", "x-peer": peer},
        )
        return httpx.Response(result.status_code, json=result.json())

    remote_identity = HttpManualIdentity(
        httpx.Client(transport=httpx.MockTransport(identity_transport)),
        "https://identity.test",
        identity_key.public_key(),
    )
    actor = replace(remote_identity.authenticate(raw), transport_generation=1)
    source = (ROOT / "config/demo/imp07/policy/manual.rego").read_bytes()
    signing = Ed25519PrivateKey.generate()
    policy = OpaPolicy(
        Path(binary),
        hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        source,
        base64.b64encode(signing.sign(source)).decode(),
        signing.public_key(),
    )
    h.service.authority, h.service.policy = remote_identity, policy
    with psycopg.connect(h.database.admin) as connection:
        connection.execute(
            "UPDATE control.guard SET bundle_digest=%s WHERE key='demo'", (policy.bundle_digest,)
        )
    verifier = DelegationVerifier(
        core_key.public_key(), identity_key.public_key(), remote_identity.resolve
    )
    gateway_client = TestClient(
        create_app(
            h.service, SignedGatewaySecurity(verifier, lambda r, p: r.headers.get("x-peer") == p)
        )
    )
    captured = []

    def data_transport(request):
        captured.append((request.url.path, json.loads(request.content)))
        result = gateway_client.post(
            request.url.path,
            content=request.content,
            headers={
                "Content-Type": "application/json",
                "x-peer": "core",
                "Idempotency-Key": request.headers["idempotency-key"],
            },
        )
        return httpx.Response(result.status_code, json=result.json())

    client = httpx.Client(transport=httpx.MockTransport(data_transport))
    envelopes = SignedEnvelopeFactory(
        client, "https://data.test", remote_identity, policy, core_key
    )
    gateway = HttpLifecycleGateway(client, "https://data.test", envelopes)
    context = gateway.session_read(actor, session["id"])
    revision = context["subject_revision"]
    assert isinstance(revision, str)
    rights = gateway.rights_create(
        actor,
        str(uuid4()),
        {
            "expected_revision": str(revision),
            "subject_id": session["subject_id"],
            "kind": "export",
            "ceremony_id": second["ceremony_id"],
        },
    )
    assert rights["state"] == "completed"
    exported = gateway.export_download(actor, rights["id"])
    assert [row["id"] for row in exported["assertions"]] == [own["id"]]
    assert "other author private" not in json.dumps(exported)
    assert any(path.endswith("authority") for path, _body in captured)
    assert any(path.endswith("rights_create") for path, _body in captured)
    with pytest.raises(ManualError):
        gateway.export_download(actor, rights["id"])
    assert h.read("SELECT count(*) FROM core.assertion") == [(2,)]


@pytest.mark.parametrize("action", ["participant_inbox", "inbox_message_read", "export_download"])
def test_external_journal_advance_during_disclosure_audit_releases_no_bytes(
    harness, monkeypatch, action
):
    from services.data.tests.test_imp07_lifecycle import (
        execute,
        followup,
        grant,
        make_due,
        rights,
    )
    from services.data.tests.test_imp07_lifecycle import (
        life as configured_life,
    )

    h = configured_life.__wrapped__(harness, monkeypatch)
    session = h.create()
    if action == "export_download":
        _operation, _body, request = rights(h, session, "export")

        def disclose():
            return h.service.export_download(h.participant, request["id"])
    else:
        contact = grant(h, session)
        scheduled = followup(h, session, contact)
        make_due(h, scheduled)
        execute(h)
        message = str(h.read("SELECT id FROM care.inbox_message")[0][0])

        def disclose():
            if action == "participant_inbox":
                return h.service.participant_inbox(h.participant)
            return h.service.inbox_message_read(h.participant, message)

    original = h.service._audit

    def advance(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[2] == action:
            h.journal.state = replace(
                h.journal.state, restriction_barrier=h.journal.state.restriction_barrier + 1
            )
        return result

    monkeypatch.setattr(h.service, "_audit", advance)
    with pytest.raises(ManualError, match="journal_barrier"):
        disclose()
    if action == "export_download":
        assert h.read(
            "SELECT downloaded_at,export_ciphertext IS NOT NULL FROM rights.request WHERE id=%s",
            (request["id"],),
        ) == [(None, True)]
    else:
        assert h.read("SELECT read_at FROM care.inbox_message WHERE id=%s", (message,)) == [(None,)]
