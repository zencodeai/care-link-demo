"""Real PostgreSQL+OPA+journal+BFF composition; identity remains an explicit fixture."""

import base64
import hashlib
import json
import os
import secrets
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from care_link_core.manual_app import create_manual_app
from care_link_core.manual_channels import ManualChannels
from care_link_policy_input import OpaPolicy
from care_link_recovery_control import EncryptedCaptures, FileJournal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp03_verification.capture import capture_database, drop_target, restore_database

ROOT = Path(__file__).resolve().parents[3]


def integrated(harness, tmp_path):
    executable = os.environ.get("CARE_LINK_OPA_BINARY")
    if not executable:
        pytest.skip("explicit pinned OPA verification binary required")
    source = (ROOT / "config/demo/imp03/policy/manual.rego").read_bytes()
    manifest = json.loads((ROOT / "config/demo/imp03/policy/bootstrap.json").read_text())
    policy = OpaPolicy(
        Path(executable),
        hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
        source,
        manifest["signature"],
        Ed25519PublicKey.from_public_bytes(base64.b64decode(manifest["public_key"])),
    )
    journal = FileJournal.provision(
        tmp_path / "journal", Ed25519PrivateKey.generate(), "test-journal"
    )
    head = journal.head()
    with psycopg.connect(harness.database.admin) as connection:
        connection.execute(
            "UPDATE control.guard SET bundle_digest=%s,journal_id=%s,journal_generation=%s,"
            "restriction_barrier=0,journal_tip_seen=0",
            (policy.bundle_digest, head.journal_id, head.generation),
        )
    harness.service.policy = policy
    harness.service.journal = journal
    channels = ManualChannels()
    harness.service.channel = channels
    return channels, journal, policy


class FixtureSecurity:
    """Declared authentication seam: not live OIDC/workload qualification."""

    def __init__(self, actor):
        self.actor = actor

    def authenticate(self, _request):
        return self.actor

    def csrf(self, request, _actor):
        from care_link_domain import ManualError

        if (
            request.headers.get("origin") != "https://manual.test"
            or request.headers.get("x-csrf-token") != "fixture-csrf"
        ):
            raise ManualError("manual.csrf_denied")


def test_real_policy_journal_database_and_bff_manual_journey(harness, tmp_path):
    h = harness
    channels, _journal, _policy = integrated(h, tmp_path)
    security = FixtureSecurity(h.participant)
    client = TestClient(
        create_manual_app(h.service, security, channels), base_url="https://manual.test"
    )

    def post(path, body, key=None):
        response = client.post(
            path,
            json=body,
            headers={
                "Origin": "https://manual.test",
                "X-CSRF-Token": "fixture-csrf",
                "Idempotency-Key": key or str(uuid4()),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    session = post(
        "/v1/sessions",
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
    sid = session["id"]
    queue = post(
        f"/v1/sessions/{sid}/human-request",
        {"expected_revision": session["revision"], "reason": "user_requested"},
    )
    security.actor = h.supervisor
    observed = post(
        f"/v1/sessions/{sid}/workforce/observe",
        {
            "expected_revision": queue["revision"],
            "scope": "observe",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=1))
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )
    assert observed["state"] == "committed" and "audit_ref" in observed
    security.actor = h.worker
    reservation = post(
        f"/v1/sessions/{sid}/workforce/reserve",
        {"expected_revision": queue["revision"], "worker_id": h.worker.account_id},
    )
    assignment = post(
        f"/v1/sessions/{sid}/workforce/accept", {"expected_revision": reservation["revision"]}
    )
    assert client.get(f"/v1/sessions/{sid}").json()["service_phase"] == "worker_assigned"
    post(
        f"/v1/sessions/{sid}/workforce/prepare-transfer",
        {"expected_revision": assignment["revision"]},
    )
    with ExitStack() as stack:
        participant = stack.enter_context(channels.open(h.participant))
        worker = stack.enter_context(channels.open(h.worker))
        acks = {}
        keys = {}
        for party, actor in [("worker", worker), ("participant", participant)]:
            security.actor = actor
            challenge = client.get(f"/v1/sessions/{sid}/workforce/challenge").json()
            current = client.get(f"/v1/sessions/{sid}").json()
            keys[party] = str(uuid4())
            data = {
                "expected_revision": current["revision"],
                "challenge_id": challenge["challenge_id"],
                "nonce": challenge["nonce"],
                "transport_generation": challenge["transport_generation"],
                "expected_control_epoch": challenge["control_epoch"],
            }
            acks[party] = (
                post(f"/v1/sessions/{sid}/workforce/channel-acks", data, keys[party]),
                data,
            )
        security.actor = worker
        worker_ack = post(
            f"/v1/sessions/{sid}/workforce/channel-acks", acks["worker"][1], keys["worker"]
        )
        current = client.get(f"/v1/sessions/{sid}").json()
        connected = post(
            f"/v1/sessions/{sid}/workforce/confirm-transfer",
            {
                "expected_revision": current["revision"],
                "assignment_id": assignment["id"],
                "channel_evidence_id": worker_ack["evidence_id"],
                "worker_ack_id": worker_ack["ack_id"],
                "expected_control_epoch": current["control_epoch"],
            },
        )
        assert connected["service_phase"] == "human_controlled"
        message = post(
            f"/v1/sessions/{sid}/messages",
            {
                "expected_revision": connected["revision"],
                "expected_control_epoch": connected["control_epoch"],
                "text": "Fictional manual worker response.",
                "accepted_draft_id": None,
            },
        )
        assert message["kind"] == "human_authored"
        security.actor = participant
        assert (
            client.get(f"/v1/sessions/{sid}/messages").json()["items"][0]["text"]
            == "Fictional manual worker response."
        )
    assert h.read("SELECT count(*) FROM audit.event")[0][0] >= 15
    assert h.read("SELECT count(*) FROM lifecycle.copy")[0][0] >= 2


def test_actual_consistent_capture_and_role_quarantined_database_import(harness, tmp_path):
    if os.environ.get("CARE_LINK_IMP03_CAPTURE") != "1":
        pytest.skip("explicit owned Docker capture fixture required")
    h = harness
    _channels, journal, policy = integrated(h, tmp_path)
    session = h.create()
    h.service.continuation_bootstrap(h.participant, str(uuid4()), str(session["id"]))
    captures_path = tmp_path / "captures"
    EncryptedCaptures.provision(captures_path)
    captures = EncryptedCaptures(
        captures_path, secrets.token_bytes(32), Ed25519PrivateKey.generate(), "test-capture"
    )
    view, dump = capture_database(
        h.database.admin,
        captures,
        journal,
        ROOT / "services/data/migrations/001_manual.sql",
        policy.bundle_digest,
    )
    assert dump[:5] == b"PGDMP"
    staged = captures.restore_quarantine(str(view["id"]), tmp_path / "quarantine", journal.head())
    target = restore_database(h.database.admin, staged)
    try:
        settings = conninfo_to_dict(h.database.admin)
        with psycopg.connect(make_conninfo(**{**settings, "dbname": target})) as connection:
            assert connection.execute(
                "SELECT mode,serving_generation FROM control.guard"
            ).fetchone() == ("quarantine", 0)
            assert connection.execute(
                "SELECT count(*) FROM control.principal_guard WHERE NOT revoked"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM access.continuation_family WHERE status='active'"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT has_database_privilege('imp03_runtime_test',current_database(),'CONNECT')"
            ).fetchone() == (False,)
        assert not staged.serving_allowed
    finally:
        drop_target(h.database.admin, target)


def test_additive_public_continuation_issuance_is_once_only_and_own_session(harness, tmp_path):
    h = harness
    channels, _journal, _policy = integrated(h, tmp_path)
    session = h.create()
    security = FixtureSecurity(h.participant)
    client = TestClient(
        create_manual_app(h.service, security, channels), base_url="https://manual.test"
    )
    key = str(uuid4())
    path = f"/v1/sessions/{session['id']}/continuations"
    headers = {
        "Origin": "https://manual.test",
        "X-CSRF-Token": "fixture-csrf",
        "Idempotency-Key": key,
    }
    first = client.post(path, json={"expected_revision": session["revision"]}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["assurance"] == "AL0"
    replay = client.post(path, json={"expected_revision": session["revision"]}, headers=headers)
    assert replay.status_code == 409
    assert replay.json()["code"] == "REPLACEMENT_UNAVAILABLE"
    assert replay.json()["operation_id"] == key
    assert first.json()["token"] not in str(h.read("SELECT * FROM access.continuation_token"))
    assert first.json()["token"] not in str(h.read("SELECT * FROM durable.operation"))
    security.actor = h.worker
    denied = client.post(
        path,
        json={"expected_revision": session["revision"]},
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert denied.status_code in {403, 404}


def test_canonical_identity_duty_with_real_policy_journal_and_http_contract(harness, tmp_path):
    from care_link_data.duty_app import create_duty_app
    from care_link_domain import DutyScope

    from services.data.tests import test_duties as fixture_duties

    h = harness
    integrated(h, tmp_path)
    h.create()
    signer = Ed25519PrivateKey.generate()
    payload = fixture_duties.signal(h.participant.account_id, signer)
    operation = str(uuid4())
    commands, actor = fixture_duties.duty(
        h, "identity_revoke", operation, payload, DutyScope(None, None, "security")
    )
    commands = fixture_duties.configure_signal(commands, signer)

    class ExplicitFixturePeer:
        def verify(self, _request, data, action, key):
            assert data == payload and action == "identity_revoke" and key == operation
            return actor

    client = TestClient(
        create_duty_app(commands, ExplicitFixturePeer()), base_url="https://control.test"
    )
    result = client.post(
        "/internal/v1/control/identity-revoke", json=payload, headers={"Idempotency-Key": operation}
    )
    assert result.status_code == 200, result.text
    assert h.read(
        "SELECT revoked FROM control.principal_guard WHERE principal_id=%s",
        (h.participant.account_id,),
    ) == [(True,)]
    assert h.read(
        "SELECT actor_context->'actor'->>'kind' FROM audit.event WHERE operation_id=%s",
        (operation,),
    ) == [("workload",)]


def test_canonical_reservation_job_with_real_policy_and_current_fence(harness, tmp_path):
    from care_link_domain import DutyScope

    from services.data.tests import test_duties as fixture_duties

    h = harness
    integrated(h, tmp_path)
    payload = fixture_duties.reserved(h)
    sid = str(payload.pop("session_id"))
    with psycopg.connect(h.database.admin) as connection:
        connection.execute("UPDATE workforce.assignment SET expires_at=now()-interval '1 second'")
        connection.execute("UPDATE durable.due_job SET due_at=now()-interval '1 second'")
    subject = str(h.read("SELECT persona_id FROM core.session")[0][0])
    operation = str(uuid4())
    commands, actor = fixture_duties.duty(
        h, "job_execute", operation, payload, DutyScope(sid, subject, "support")
    )
    assert commands.job_execute(actor, operation, payload)["state"] == "committed"
    assert h.read("SELECT status FROM workforce.assignment") == [("expired",)]
    assert h.read("SELECT service_phase,unresolved FROM core.session") == [("queued", True)]


def test_real_database_commit_then_lost_ack_reconciles_one_operation(harness, monkeypatch):
    """The server really commits; only the adapter's acknowledgement is dropped."""
    from care_link_domain import ManualError

    h = harness
    session = h.create()
    key = str(uuid4())
    sid = str(session["id"])
    body = {"expected_revision": session["revision"], "reason": "user_requested"}
    original_connect = psycopg.Connection.connect
    calls = [0]

    class LostCommitAcknowledgement:
        def __init__(self, connection, number):
            self.connection, self.number = connection, number

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __exit__(self, kind, error, traceback):
            result = self.connection.__exit__(kind, error, traceback)
            if kind is None and self.number == 2:
                raise psycopg.OperationalError("fixture committed but acknowledgement lost")
            return result

    def connect(_cls, *args, **kwargs):
        calls[0] += 1
        return LostCommitAcknowledgement(original_connect(*args, **kwargs), calls[0])

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.Connection, "connect", classmethod(connect))
        with pytest.raises(ManualError, match="commit_unknown"):
            h.service.session_human_request(h.participant, key, body, sid)
    assert h.service.operation_status(h.participant, key)["state"] == "committed"
    ticket = h.service.session_human_request(h.participant, key, body, sid)
    assert h.read("SELECT count(*) FROM workforce.queue_entry") == [(1,)]
    assert h.read("SELECT count(*) FROM durable.operation WHERE operation_id=%s", (key,)) == [(1,)]
    assert str(h.read("SELECT id FROM workforce.queue_entry")[0][0]) == ticket["ticket_id"]


def test_disconnected_endpoint_is_not_reported_as_current_connection(harness):
    from services.data.tests.test_manual import connected

    h = harness
    session = connected(h)
    assert h.service.queue_list(h.worker)["items"][0]["connection_confirmed"] is True
    h.channels.closed.add(h.participant.account_id)
    current = h.service.session_read(h.worker, str(session["id"]))
    assert current["service_phase"] == "human_controlled"
    assert current["unresolved"] is True
    assert current["transport"] == "disconnected"
    assert "channel_disconnected" in current["degraded_reasons"]
    assert h.service.queue_list(h.worker)["items"][0]["connection_confirmed"] is False
