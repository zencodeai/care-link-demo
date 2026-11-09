"""Cross-custodian restriction ordering with signed events and durable-port fixtures."""

import base64
import copy
import hashlib
from dataclasses import dataclass
from uuid import uuid4

import pytest
from care_link_identity import IdentityError, SignalReceiver
from care_link_identity.crypto import canonical
from care_link_identity.domain import stamp
from care_link_identity.workload_signals import WorkloadBindings, WorkloadSignals

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class Snapshot:
    generation: int


@dataclass(frozen=True)
class Receipt:
    command_id: str
    peer: str
    generation: int
    durable: bool


class Fences:
    def __init__(self):
        self.commands = {}
        self.generation = 0
        self.fail_before = False
        self.fail_after = False
        self.nondurable = False

    def current(self):
        return Snapshot(self.generation)

    def receipt(self, command_id):
        return self.commands.get(command_id)

    def restrict(self, peer, command_id, expected_generation):
        if self.fail_before:
            raise OSError("fixture unavailable")
        if expected_generation != self.generation:
            raise ValueError("fixture conflict")
        self.generation += 1
        receipt = Receipt(command_id, peer, self.generation, not self.nondurable)
        self.commands[command_id] = receipt
        if self.fail_after:
            raise TimeoutError("fixture lost reply after fsync")
        return receipt


def configured(identity, subjects=None):
    service, store, _provider, clock, key = identity
    subject = str(uuid4())
    mapping = subjects or {subject: "spiffe://care-link.demo/lab/runtime"}
    fences = Fences()
    workloads = WorkloadSignals(store, WorkloadBindings("provider-signals", mapping), fences)
    receiver = SignalReceiver(
        store,
        "provider-signals",
        "care-link-identity",
        key.public_key(),
        service.issuer,
        clock,
        workloads,
    )
    return receiver, workloads, fences, next(iter(mapping))


def signal(identity, subject, sequence="1", previous="0" * 64, jti=None):
    _service, _store, _provider, clock, key = identity
    event = {
        "issuer_id": "provider-signals",
        "audience": "care-link-identity",
        "jti": jti or str(uuid4()),
        "subject_id": subject,
        "event_type": "workload_compromised",
        "source_sequence": sequence,
        "previous_digest": previous,
        "event_at": stamp(clock()),
    }
    event["digest"] = hashlib.sha256(canonical(event)).hexdigest()
    event["signature"] = base64.urlsafe_b64encode(key.sign(canonical(event))).rstrip(b"=").decode()
    return event


def test_signed_workload_is_durable_before_sequence_ack_and_idempotent(identity):
    _service, store, _provider, _clock, _key = identity
    receiver, _workloads, fences, subject = configured(identity)
    event = signal(identity, subject)
    account_before = copy.deepcopy(
        [row for (kind, _key), row in store.records.items() if kind == "account"]
    )
    result = receiver.ingest(event)
    assert result["state"] == "applied" and result["accepted_sequence"] == "1"
    assert fences.generation == 1 and all(receipt.durable for receipt in fences.commands.values())
    assert receiver.ingest(event)["state"] == "duplicate" and fences.generation == 1
    assert account_before == [
        row for (kind, _key), row in store.records.items() if kind == "account"
    ]


def test_unknown_or_forged_workload_mapping_has_zero_store_mutation(identity):
    _service, store, _provider, _clock, _key = identity
    receiver, _workloads, fences, _subject = configured(identity)
    before = copy.deepcopy(store.records)
    with pytest.raises(IdentityError):
        receiver.ingest(signal(identity, str(uuid4())))
    assert store.records == before and fences.generation == 0
    event = signal(identity, _subject)
    event["signature"] = "forged"
    with pytest.raises(IdentityError):
        receiver.ingest(event)
    assert store.records == before


@pytest.mark.parametrize("failure", ["before", "after", "nondurable"])
def test_uncertain_fence_never_acknowledges_and_reconciles_same_command(identity, failure):
    _service, store, _provider, _clock, _key = identity
    receiver, workloads, fences, subject = configured(identity)
    event = signal(identity, subject)
    fences.fail_before = failure == "before"
    fences.fail_after = failure == "after"
    fences.nondurable = failure == "nondurable"
    with pytest.raises(IdentityError):
        receiver.ingest(event)
    assert not list(row for (kind, _), row in store.records.items() if kind == "head")
    pending = next(
        key
        for (kind, key), row in store.records.items()
        if kind == "operation" and row.get("state") == "pending"
    )
    fences.fail_before = fences.fail_after = False
    if failure == "nondurable":
        fences.commands = {
            key: Receipt(row.command_id, row.peer, row.generation, True)
            for key, row in fences.commands.items()
        }
    result = workloads.reconcile(pending)
    assert (
        result["state"] == "applied"
        and result["accepted_sequence"] == "1"
        and fences.generation == 1
    )


def test_stale_and_gapped_authenticated_workload_signals_fence_without_advancing(identity):
    _service, _store, _provider, clock, _key = identity
    receiver, _workloads, fences, subject = configured(identity)
    event = signal(identity, subject)
    clock.advance(61)
    assert receiver.ingest(event)["state"] == "gap_blocked" and fences.generation == 1
    result = receiver.ingest(signal(identity, subject, sequence="4"))
    assert (
        result["state"] == "gap_blocked"
        and result["accepted_sequence"] == "0"
        and fences.generation == 2
    )


def test_changed_digest_quarantines_source_and_fences_all_mapped_workloads(identity):
    subjects = {
        str(uuid4()): "spiffe://care-link.demo/lab/runtime",
        str(uuid4()): "spiffe://care-link.demo/lab/help",
    }
    receiver, _workloads, fences, subject = configured(identity, subjects)
    first = signal(identity, subject)
    assert receiver.ingest(first)["state"] == "applied"
    changed = signal(identity, subject, sequence="2", previous=first["digest"], jti=first["jti"])
    result = receiver.ingest(changed)
    assert result["state"] == "quarantined" and result["accepted_sequence"] == "1"
    assert {row.peer for row in fences.commands.values()} == set(subjects.values())


def test_mapping_is_copied_and_immutable(identity):
    source = {str(uuid4()): "spiffe://care-link.demo/lab/runtime"}
    bound = WorkloadBindings("issuer", source)
    source.clear()
    assert len(bound.subjects) == 1
    with pytest.raises(TypeError):
        bound.subjects["bad"] = "bad"


def test_host_fsync_then_identity_finalize_failure_recovers_without_second_append(
    identity, monkeypatch
):
    _service, store, _provider, _clock, _key = identity
    receiver, _workloads, fences, subject = configured(identity)
    event = signal(identity, subject)
    original = store.put
    failed = [False]

    def fail_head(kind, key, record):
        if kind == "head" and not failed[0]:
            failed[0] = True
            raise OSError("fixture database commit boundary failed")
        original(kind, key, record)

    monkeypatch.setattr(store, "put", fail_head)
    with pytest.raises(OSError):
        receiver.ingest(event)
    assert fences.generation == 1
    assert receiver.ingest(event)["accepted_sequence"] == "1"
    assert fences.generation == 1


@pytest.mark.parametrize("first_kind", ["account", "workload"])
def test_same_signed_source_cross_kind_jti_collision_quarantines_humans_and_all_workloads(
    identity, first_kind
):
    from conftest import signed_in

    service, store, provider, _clock, key = identity
    receiver, _workloads, fences, workload = configured(identity)
    account = next(
        row["account_id"] for (kind, _), row in store.records.items() if kind == "account"
    )
    service.provision("unaffected-human", str(uuid4()), ["pid"])
    original_subject = provider.subject
    provider.subject = "unaffected-human"
    human = signed_in(service)
    provider.subject = original_subject
    jti = str(uuid4())
    account_event = signal(identity, account, jti=jti)
    account_event["event_type"] = "credential_revoked"
    content = {k: v for k, v in account_event.items() if k not in {"digest", "signature"}}
    account_event["digest"] = hashlib.sha256(canonical(content)).hexdigest()
    account_event["signature"] = (
        base64.urlsafe_b64encode(
            key.sign(canonical({k: v for k, v in account_event.items() if k != "signature"}))
        )
        .rstrip(b"=")
        .decode()
    )
    workload_event = signal(identity, workload, jti=jti)
    first, second = (
        (account_event, workload_event)
        if first_kind == "account"
        else (workload_event, account_event)
    )
    assert receiver.ingest(first)["state"] == "applied"
    assert service.current(human)
    fences.fail_before = True
    with pytest.raises(IdentityError):
        receiver.ingest(second)
    with pytest.raises(IdentityError):
        service.current(human)
    assert store.get("issuer", service.issuer)["fence_state"] == "pending"
    fences.fail_before = False
    assert receiver.ingest(second)["state"] == "quarantined"
    assert {receipt.peer for receipt in fences.commands.values()} == set(
        _workloads.bindings.subjects.values()
    )
    assert store.get("issuer", service.issuer)["fence_state"] == "durable"
