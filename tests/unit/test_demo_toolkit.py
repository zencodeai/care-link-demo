"""Reference toolkit custody/restart/idempotency tests; no issued runtime claims."""

import base64
import hashlib
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from tools.demo import DemoError, DemoToolkit, Environment, Registry, VaultSecrets
from tools.demo.models import CORE_PROTOCOL, SLOTS, Record, record
from tools.demo.secrets import KeychainSecrets, credential, totp
from tools.demo.storage import private_write


def write_private(path: Path, raw: bytes) -> None:
    path.write_bytes(raw)
    path.chmod(0o600)


class OperatorHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        request_line = self.rfile.readline().decode()
        if not request_line:
            return  # A custody-rejected client closes before sending HTTP.
        headers: dict[str, str] = {}
        while (line := self.rfile.readline()) not in {b"\r\n", b""}:
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        request = record(json.loads(self.rfile.read(int(headers["content-length"]))))
        server = self.server
        assert isinstance(server, OperatorServer)
        action = request_line.split()[1].rsplit("/", 1)[-1]
        server.requests.append((action, request))
        if action == "doctor":
            result = {
                "environment_id": request["environment_id"],
                "core_protocol": CORE_PROTOCOL,
                "ready": server.ready,
            }
        elif action == "rotate":
            key = str(request["operation_id"])
            if key not in server.rotations:
                server.rotations[key] = {
                    "operation_id": key,
                    "account_id": request["account_id"],
                    "credential_revision": request["credential_revision"],
                    "verified": True,
                }
                server.rotation_effects += 1
            result = server.rotations[key]
        else:
            run_id = str(request["run_id"])
            if action == "create":
                if run_id not in server.runs:
                    server.runs[run_id] = {
                        key: request[key]
                        for key in ("run_id", "environment_id", "scenario", "scenario_version")
                    }
                    server.runs[run_id].update(state="active", revision="1")
                    server.create_effects += 1
            if action == "close":
                server.runs[run_id].update(state="closed", revision="2")
            result = server.runs[run_id]
        if server.drop_action == action:
            server.drop_action = None
            return  # Simulate a committed effect whose response never arrives.
        body = json.dumps(result).encode()
        self.wfile.write(
            (
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode()
            + body
        )


class OperatorServer(socketserver.UnixStreamServer):
    def __init__(self, path: Path) -> None:
        self.runs: dict[str, Record] = {}
        self.rotations: dict[str, Record] = {}
        self.requests: list[tuple[str, Record]] = []
        self.create_effects = 0
        self.rotation_effects = 0
        self.drop_action: str | None = None
        self.ready = True
        super().__init__(str(path), OperatorHandler)


@pytest.fixture
def lab(tmp_path: Path):
    tmp_path.chmod(0o700)
    key = tmp_path / "vault.key"
    write_private(key, os.urandom(32))
    receipt = tmp_path / "ownership.json"
    write_private(
        receipt,
        json.dumps({"environment_id": "review-lab", "resource_id": "owned-runtime"}).encode(),
    )
    socket_directory = tempfile.TemporaryDirectory(prefix="demo-test-", dir="/tmp")
    socket_path = Path(socket_directory.name).resolve() / "operator.sock"
    operator = OperatorServer(socket_path)
    socket_path.chmod(0o600)
    thread = threading.Thread(target=operator.serve_forever, daemon=True)
    thread.start()
    environment = {
        "schema_version": 1,
        "environment_id": "review-lab",
        "core_protocol": CORE_PROTOCOL,
        "scenario_version": "1",
        "base_domain": "qualification.localhost",
        "port": 29443,
        "actors": {
            slot: {
                "account_id": str(uuid4()),
                "provider_subject": str(uuid4()),
                "role": role,
                "username": "synthetic-" + slot,
                "secret_ref": "review-" + slot,
            }
            for slot, role in SLOTS.items()
        },
        "ownership": {
            "kind": "receipt",
            "resource_id": "owned-runtime",
            "receipt_path": str(receipt),
            "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        },
        "lifecycle": {"socket": str(socket_path), "peer_uid": os.geteuid()},
    }
    root = tmp_path / "durable"
    registry = Registry(root)
    vault = VaultSecrets(root / "vault", key)
    toolkit = DemoToolkit(registry, secrets_store=vault)
    toolkit.register(environment)
    raw_credential = json.dumps(
        {
            "password": "synthetic-password-never-logged",
            "totp_secret": base64.b32encode(b"12345678901234567890").decode(),
            "revision": "1",
        }
    )
    for slot in SLOTS:
        toolkit.import_credential("review-lab", slot, raw_credential)
    try:
        yield toolkit, environment, operator, key
    finally:
        operator.shutdown()
        operator.server_close()
        thread.join(timeout=3)
        socket_directory.cleanup()


def test_registered_environment_requires_exact_verified_binding(lab) -> None:
    toolkit, environment, _operator, _key = lab
    assert toolkit.register(environment)["provisioned"] is False
    changed = {**environment, "port": 30443}
    with pytest.raises(DemoError, match="environment_binding_changed"):
        toolkit.register(changed)
    changed = {**environment, "core_protocol": "unknown"}
    with pytest.raises(DemoError, match="environment_version_incompatible"):
        toolkit.register(changed)
    changed = {**environment, "password": "not-permitted-in-manifest"}
    with pytest.raises(DemoError, match="environment_schema_incompatible"):
        Environment.parse(changed)


def test_ownership_drift_is_not_adopted_and_readiness_is_real(lab) -> None:
    toolkit, environment, operator, _key = lab
    assert toolkit.doctor("review-lab")["ready"] is True
    operator.ready = False
    assert toolkit.doctor("review-lab")["ready"] is False
    operator.ready = True
    receipt = Path(environment["ownership"]["receipt_path"])
    write_private(receipt, b"changed")
    assert toolkit.doctor("review-lab")["ready"] is False
    with pytest.raises(DemoError, match="ownership_digest_changed"):
        toolkit.create("review-lab")
    assert operator.create_effects == 0


def test_create_commit_reply_loss_recovers_original_operation_after_restart(lab) -> None:
    toolkit, _environment, operator, key = lab
    run_id = str(uuid4())
    operator.drop_action = "create"
    with pytest.raises(DemoError, match="operator_unavailable"):
        toolkit.create("review-lab", run_id=run_id)
    previous = toolkit.inspect(run_id)
    assert previous["state"] == "creating"
    restarted = DemoToolkit(
        Registry(toolkit.registry.root),
        secrets_store=VaultSecrets(toolkit.registry.root / "vault", key),
    )
    discovered = restarted.list_runs("review-lab")
    assert discovered["current_run_id"] == run_id
    assert discovered["runs"][0]["state"] == "creating"
    assert "secret_ref" not in json.dumps(discovered)
    result = restarted.resume(run_id)
    assert result["state"] == "active"
    assert result["operation_id"] == previous["operation_id"]
    assert operator.create_effects == 1
    assert [x[1]["operation_id"] for x in operator.requests if x[0] == "create"] == [
        previous["operation_id"]
    ] * 2
    cli = subprocess.run(  # noqa: S603 - fixed interpreter and local toolkit module
        [
            sys.executable,
            "-m",
            "tools.demo",
            "--state-root",
            str(toolkit.registry.root),
            "--vault-key-file",
            str(key),
            "run",
            "inspect",
            "--run",
            run_id,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli.returncode == 0
    assert json.loads(cli.stdout)["run_id"] == run_id


def test_one_active_run_and_fresh_lifecycle_preserves_previous(lab) -> None:
    toolkit, _environment, operator, _key = lab
    first = toolkit.create("review-lab")
    with pytest.raises(DemoError, match="environment_has_active_or_partial_run"):
        toolkit.create("review-lab")
    assert toolkit.close(first["run_id"])["state"] == "closed"
    second = toolkit.create("review-lab")
    assert second["run_id"] != first["run_id"]
    assert second["origins"] != first["origins"]
    assert toolkit.inspect(first["run_id"])["state"] == "closed"
    assert operator.create_effects == 2
    assert len(operator.runs) == 2
    assert "qualification.localhost" in toolkit.actor_url(second["run_id"], "participant")
    with pytest.raises(DemoError, match="run_not_active"):
        toolkit.actor_url(first["run_id"], "participant")


def test_concurrent_creation_is_serialized_across_registry_instances(lab) -> None:
    toolkit, _environment, operator, key = lab

    def create() -> str:
        other = DemoToolkit(
            Registry(toolkit.registry.root),
            secrets_store=VaultSecrets(toolkit.registry.root / "vault", key),
        )
        try:
            return str(other.create("review-lab")["state"])
        except DemoError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: create(), range(2)))
    assert sorted(outcomes) == ["active", "environment_has_active_or_partial_run"]
    assert operator.create_effects == 1


def test_socket_owner_and_connected_peer_are_checked(lab, monkeypatch: pytest.MonkeyPatch) -> None:
    toolkit, _environment, operator, _key = lab
    monkeypatch.setattr("tools.demo.lifecycle.peer_uid", lambda _connection: os.geteuid() + 1)
    with pytest.raises(DemoError, match="operator_peer_changed"):
        toolkit.create("review-lab")
    assert operator.create_effects == 0


def test_secret_ciphertext_and_registry_never_contain_credential(lab) -> None:
    toolkit, _environment, _operator, key = lab
    root = toolkit.registry.root
    for p in root.rglob("*"):
        if p.is_file():
            assert b"synthetic-password-never-logged" not in p.read_bytes()
            assert b"GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ" not in p.read_bytes()
    write_private(key, os.urandom(32))
    wrong = DemoToolkit(Registry(root), secrets_store=VaultSecrets(root / "vault", key))
    assert wrong.doctor("review-lab")["ready"] is False
    assert wrong.registry.path.exists()


def test_rotation_reply_loss_reuses_pending_secret_and_effect(lab) -> None:
    toolkit, _environment, operator, key = lab
    operation_id = str(uuid4())
    old = toolkit.reveal_password("review-lab", "worker1")
    operator.drop_action = "rotate"
    with pytest.raises(DemoError, match="operator_unavailable"):
        toolkit.rotate("review-lab", "worker1", operation_id=operation_id)
    assert toolkit.reveal_password("review-lab", "worker1") == old
    with pytest.raises(DemoError, match="credential_rotation_pending_resume_original_operation"):
        toolkit.rotate("review-lab", "worker1")
    restarted = DemoToolkit(
        Registry(toolkit.registry.root),
        secrets_store=VaultSecrets(toolkit.registry.root / "vault", key),
    )
    result = restarted.rotate("review-lab", "worker1", operation_id=operation_id)
    assert result["verified"] is True
    assert result["revision"] == "2"
    assert restarted.reveal_password("review-lab", "worker1") != old
    assert restarted.reveal_password("review-lab", "worker2") == old
    assert operator.rotation_effects == 1
    payloads = [x[1]["credential"] for x in operator.requests if x[0] == "rotate"]
    assert payloads[0] == payloads[1]
    assert payloads[0]["totp_secret"] == base64.b32encode(b"12345678901234567890").decode()
    assert result["rotated_fields"] == ["password"]
    assert payloads[0]["password"] not in toolkit.registry.path.read_text()


def test_private_state_refuses_symlinks_loose_modes_and_unknown_schema(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    root = tmp_path / "state"
    registry = Registry(root)
    private_write(registry.path, b'{"schema_version":99}')
    with pytest.raises(DemoError, match="registry_version_incompatible"):
        registry.read()
    registry.path.chmod(0o644)
    with pytest.raises(DemoError, match="private_file_custody"):
        registry.read()
    registry.path.unlink()
    link = tmp_path / "alias"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(DemoError, match="private_path_symlink"):
        Registry(link)
    write_private(tmp_path / "short.key", b"short")
    with pytest.raises(DemoError, match="vault_key_must_be_32_bytes"):
        VaultSecrets(root / "vault", tmp_path / "short.key")


def test_keychain_adapter_keeps_secret_out_of_process_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], str | None]] = []
    encoded = base64.urlsafe_b64encode(b"private value with newline\nand shell $()`").decode()

    def run(args, **kwargs):
        calls.append((args, kwargs.get("input")))
        return subprocess.CompletedProcess(
            args, 0, encoded + "\n" if args[1] == "find-generic-password" else "", ""
        )

    monkeypatch.setattr("tools.demo.secrets.sys.platform", "darwin")
    monkeypatch.setattr("tools.demo.secrets.subprocess.run", run)
    store = KeychainSecrets()
    store.put("synthetic-account", "private value with newline\nand shell $()`")
    assert all(
        "private value" not in " ".join(args) and encoded not in " ".join(args) for args, _ in calls
    )
    assert calls[0][0] == ["/usr/bin/security", "-i"]
    assert encoded in calls[0][1]
    assert store.get("synthetic-account") == "private value with newline\nand shell $()`"


def test_totp_uses_standard_algorithm_without_exposing_seed() -> None:
    seed = base64.b32encode(b"12345678901234567890").decode()
    assert totp(seed, now=59) == ("287082", 1)
    with pytest.raises(DemoError, match="invalid_credential_fields"):
        credential('{"password":"secret","totp_secret":"seed","revision":"1","admin_dsn":"secret"}')


def test_large_keychain_bootstrap_roundtrips_through_bounded_compressed_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = ""

    def command(_self, args, *, stdin=None):
        nonlocal encoded
        if stdin:
            assert len(stdin) < 4096
            encoded = stdin.strip().split(" -w ")[1]
            return ""
        return encoded

    monkeypatch.setattr(KeychainSecrets, "_command", command)
    store = KeychainSecrets()
    value = json.dumps({"private_bootstrap": "synthetic accented é value " * 2000})
    store.put("large-bootstrap", value)
    assert store.get("large-bootstrap") == value
    encoded = base64.urlsafe_b64encode(store.compressed_prefix.encode() + b"invalid").decode()
    with pytest.raises(DemoError, match="keychain_secret_invalid"):
        store.get("large-bootstrap")


def test_unmatched_runtime_receipt_stays_pending(lab) -> None:
    toolkit, _environment, operator, _key = lab

    class WrongReceipt:
        def call(self, environment: Environment, action: str, request: Record) -> Record:
            return {
                **request,
                "environment_id": "another-environment",
                "state": "active",
                "revision": "1",
            }

    other = DemoToolkit(toolkit.registry, secrets_store=toolkit.secrets, lifecycle=WrongReceipt())
    run_id = str(uuid4())
    with pytest.raises(DemoError, match="runtime_run_binding_changed"):
        other.create("review-lab", run_id=run_id)
    assert other.inspect(run_id)["state"] == "creating"
    assert operator.create_effects == 0


def test_missing_secret_prevents_namespace_mutation(lab) -> None:
    toolkit, _environment, operator, _key = lab
    (toolkit.registry.root / "vault/secrets.aesgcm").unlink()
    assert toolkit.doctor("review-lab")["ready"] is False
    with pytest.raises(DemoError, match="secret_missing"):
        toolkit.create("review-lab")
    assert operator.create_effects == 0
    assert toolkit.registry.read()["runs"] == {}


def test_close_unconfirmed_does_not_report_success(lab) -> None:
    toolkit, _environment, _operator, _key = lab
    run = toolkit.create("review-lab")

    class UnconfirmedClose:
        def call(self, environment: Environment, action: str, request: Record) -> Record:
            return {**request, "state": "active", "revision": "1"}

    other = DemoToolkit(
        toolkit.registry, secrets_store=toolkit.secrets, lifecycle=UnconfirmedClose()
    )
    with pytest.raises(DemoError, match="run_close_pending"):
        other.close(str(run["run_id"]))
    assert other.inspect(str(run["run_id"]))["state"] == "closing"


def test_explicit_fresh_otp_waits_once_for_a_new_window(lab) -> None:
    toolkit, _environment, _operator, _key = lab
    moment = [59.0]
    waits: list[float] = []

    def sleep(delay: float) -> None:
        waits.append(delay)
        moment[0] += delay

    value = toolkit.otp("review-lab", "worker1", fresh=True, clock=lambda: moment[0], sleep=sleep)
    assert waits == [1.2]
    assert value["fresh_window"] is True
    assert value["expires_in_seconds"] == 30
    assert value["code"] != "287082"
    with pytest.raises(DemoError, match="fresh_otp_clock_did_not_advance"):
        toolkit.otp(
            "review-lab", "worker1", fresh=True, clock=lambda: 59.0, sleep=lambda _delay: None
        )
