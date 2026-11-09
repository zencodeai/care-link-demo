"""Cross-custodian serialization and identity mapping, without forged kernel proof."""

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_workload_trust import FenceStore, TrustDenied, UnixFenceClient, WorkloadMap

pytestmark = pytest.mark.unit
PEER = "spiffe://care-link.demo/lab/help"


def test_uncertain_complete_append_gets_fresh_durable_confirmation(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    store = FenceStore(tmp_path, os.geteuid())
    store.initialize(frozenset({PEER}))
    command = hashlib.sha256(b"synthetic command").hexdigest()
    first = store.restrict(PEER, command, 0)
    confirmed = store.durable_read()
    assert confirmed == first
    assert confirmed.commands == ((command, PEER),)
    assert not confirmed.admits(PEER)
    assert store.restrict(PEER, command, 0) == confirmed


def test_mapping_is_canonical_immutable_and_unknown_subject_denies() -> None:
    subject = str(uuid4())
    values = {subject: PEER}
    mapping = WorkloadMap(values)
    values[subject] = "spiffe://care-link.demo/lab/other"
    assert mapping.resolve(subject) == PEER
    with pytest.raises(TrustDenied):
        mapping.resolve(str(uuid4()))
    with pytest.raises(ValueError):
        WorkloadMap({"caller-claimed-name": PEER})


def test_client_validates_closed_current_state_and_durable_receipt(monkeypatch, tmp_path) -> None:
    command = hashlib.sha256(b"synthetic command").hexdigest()
    client = UnixFenceClient(tmp_path / "not-connected.sock", 21000)
    state = {
        "generation": 1,
        "allowed": [PEER],
        "denied": [PEER],
        "commands": [[command, PEER]],
        "head": "0" * 64,
    }
    monkeypatch.setattr(client, "_call", lambda *_args: state)
    assert not client.current().admits(PEER)
    for changed in [
        state | {"generation": True},
        state | {"commands": []},
        state | {"allowed": []},
        state | {"unexpected": True},
    ]:
        monkeypatch.setattr(client, "_call", lambda *_args, value=changed: value)
        with pytest.raises(TrustDenied):
            client.current()
    receipt = {"command_id": command, "peer": PEER, "generation": 1, "durable": True}
    monkeypatch.setattr(client, "_call", lambda *_args: receipt)
    assert client.receipt(command).durable
    monkeypatch.setattr(client, "_call", lambda *_args: receipt | {"durable": False})
    with pytest.raises(TrustDenied):
        client.receipt(command)
