"""Protected runtime seams; no claims of deployed SPIRE/OIDC qualification."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from care_link_contracts import ContractError
from care_link_domain import ManualError
from care_link_recovery_control import FileJournal
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from tools.imp03_runtime.authority_apps import journal_app
from tools.imp03_runtime.compose import Composition
from tools.imp03_runtime.config import ROLES, load, routes, spiffe
from tools.imp03_runtime.mesh import render
from tools.imp03_runtime.prepare import prepare, validate_binding
from tools.imp03_runtime.remote import HttpJournal, HttpPolicy

ROOT = Path(__file__).resolve().parents[2]


def binding(tmp_path):
    value = json.loads((ROOT / "tools/imp03_runtime/bindings.example.json").read_text())
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("Synthetic verification bundle")
    value["web_directory"] = str(web)
    return value


def test_preparation_splits_credentials_and_refuses_existing_target(tmp_path):
    value = binding(tmp_path)
    root = tmp_path / "runtime"
    prepare(value, root)
    core = load(root / "core/config.json")
    data = load(root / "data/config.json")
    identity = load(root / "identity/config.json")
    assert "store_dsn" not in core and "core_signing_key" in core
    assert "content_key" in data and "custody_key" not in data
    assert "custody_key" in identity and "content_key" not in identity
    assert not (root / "data/signing.key").exists()
    assert not (root / "pdp/signing.key").exists()
    assert core["core_public_key"] != identity["core_public_key"]
    for role in ROLES:
        assert (root / role).stat().st_mode & 0o077 == 0
        assert (root / role / "config.json").stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        prepare(value, root)


@pytest.mark.parametrize(
    "mutation",
    [
        "cross_proxy",
        "cross_fence",
        "same_uid",
        "wrong_db",
        "wrong_role",
        "extra",
        "imp02_path",
        "shared_fence_group",
        "reused_password",
    ],
)
def test_binding_custody_and_scope_fail_closed(tmp_path, mutation):
    value = binding(tmp_path)
    if mutation == "reused_password":
        value["data"]["store_dsn"] = value["data"]["store_dsn"].replace(
            "ISSUED_DATA_DB_PASSWORD", "ISSUED_IDENTITY_DB_PASSWORD"
        )
    elif mutation == "shared_fence_group":
        value["roles"]["core"]["uid"] = 22999
    elif mutation == "cross_proxy":
        value["roles"]["data"]["uid"] = value["roles"]["identity"]["proxy_uid"]
    elif mutation == "cross_fence":
        value["roles"]["data"]["uid"] = value["roles"]["identity"]["fence_uid"]
    elif mutation == "same_uid":
        value["roles"]["data"]["uid"] = value["roles"]["identity"]["uid"]
    elif mutation == "wrong_db":
        value["data"]["store_dsn"] = value["identity"]["store_dsn"]
    elif mutation == "wrong_role":
        value["actors"][1]["roles"] = ["pid"]
    elif mutation == "extra":
        value["allow_unverified"] = True
    else:
        value["roles"]["core"]["backend_socket"] = "/run/care-link-imp02-002/app.sock"
    with pytest.raises(ValueError):
        validate_binding(value)


def test_config_rejects_duplicate_fields_and_world_readable_secret(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"a":1,"a":2}')
    config.chmod(0o600)
    with pytest.raises(ValueError, match="Duplicate"):
        load(config)
    config.write_text("{}")
    config.chmod(0o644)
    with pytest.raises(ValueError, match="Owner-only"):
        load(config)


def test_mesh_generation_has_exact_routes_and_independent_trust_configs(tmp_path):
    value = binding(tmp_path)
    destination = tmp_path / "mesh"
    render(value, destination)
    for role in ROLES:
        proxy = json.loads((destination / (role + "-envoy.json")).read_text())
        assert proxy["node"]["cluster"] == "care-link-imp03-002"
        authorizer = json.loads((destination / (role + "-authorization.json")).read_text())
        assert authorizer["local_spiffe_id"] == spiffe(role)
        assert {item["spiffe_id"] for item in authorizer["rules"]} == {
            spiffe(peer) for peer in routes(role)
        }
        names = [item["name"] for item in proxy["static_resources"]["clusters"]]
        assert len(names) == len(set(names))
    fence = json.loads((destination / "fence.json").read_text())
    assert fence["allowed"] == sorted(spiffe(role) for role in ROLES)
    assert fence["restrict_uid"] not in fence["read_uids"]
    assert fence["restrict_uid"] != fence["uid"]
    assert fence["restrict_uid"] == 22001
    assert fence["access_gid"] == 22999


def test_journal_response_is_fresh_signed_nonce_bound_and_reports_serving_fence(tmp_path):
    key = Ed25519PrivateKey.generate()
    journal = FileJournal.provision(tmp_path / "journal", key, "test-runtime")
    app = journal_app(journal, key, lambda _request, role: role == "data")
    client = TestClient(app, base_url="https://journal.imp03.mesh")
    remote = HttpJournal(client, "https://journal.imp03.mesh", key.public_key())
    state = remote.head()
    assert state.journal_id == journal.journal_id and state.serving_generation == 1
    operation = str(uuid4())
    state = remote.append(
        {
            "command_id": operation,
            "expected_tip": "0",
            "kind": "serving_fence",
            "scope": {
                "session_id": None,
                "subject_id": None,
                "purpose": "security",
                "fields": [],
                "recipient_id": None,
            },
            "restriction": {
                "kind": "serving_fence",
                "generation": "1",
                "target_id": str(uuid4()),
                "promotion_id": str(uuid4()),
            },
            "binding_digest": "a" * 64,
            "db_operation_id": operation,
            "relaxation_evidence_digest": None,
        }
    )
    assert state.serving_generation == 0 and state.restriction_barrier == 1
    captured = client.post(
        "/internal/v1/journal/head", json={"nonce": str(uuid4()), "command": None}
    ).json()
    replay = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=captured))
    )
    with pytest.raises(ManualError, match="journal_unavailable"):
        HttpJournal(replay, "https://journal.imp03.mesh", key.public_key()).head()


def test_journal_transport_requires_authenticated_data_peer(tmp_path):
    key = Ed25519PrivateKey.generate()
    journal = FileJournal.provision(tmp_path / "journal", key, "test-runtime")
    client = TestClient(journal_app(journal, key, lambda *_: False))
    assert client.post("/internal/v1/journal/head", json={}).status_code == 403


def test_unprotected_listener_and_spoofed_headers_never_reach_composed_app():
    composition = object.__new__(Composition)
    composition.config = {"proxy_uid": 22002}
    called = []

    async def inner(scope, receive, send):
        called.append(True)
        await JSONResponse({})(scope, receive, send)

    composition.app = inner
    client = TestClient(composition)
    reply = client.get(
        "/v1/sessions",
        headers={
            "x-care-link-verified-spiffe": spiffe("core"),
            "x-care-link-fence-generation": "0",
        },
    )
    assert reply.status_code == 403 and not called


def test_policy_remote_refuses_redirect_or_non_json_reply():
    # Validation rejects malformed input before contacting any upstream.
    calls = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: calls.append(request)
            or httpx.Response(302, headers={"location": "https://elsewhere.invalid"})
        )
    )
    with pytest.raises(ContractError):
        HttpPolicy(client, "https://pdp.imp03.mesh").evaluate({})
    assert not calls


def test_identity_runtime_schedules_expired_credential_cleanup():
    composition = object.__new__(Composition)
    composition.clients = []
    called = []

    async def exercise():
        stop = asyncio.Event()
        done = asyncio.Event()
        loop = asyncio.get_running_loop()

        class Cleanup:
            def expire_credentials(self):
                called.append(True)
                loop.call_soon_threadsafe(done.set)
                return 1

        composition.retention = Cleanup()
        task = asyncio.create_task(composition.maintain(stop))
        await asyncio.wait_for(done.wait(), timeout=2)
        stop.set()
        await task

    asyncio.run(exercise())
    assert called and composition.maintenance_state == "current"


@pytest.mark.parametrize("stale", [False, True])
def test_fault_barrier_holds_pidfd_and_refuses_changed_process_birth(tmp_path, monkeypatch, stale):
    from types import SimpleNamespace

    from tools.imp03_runtime import __main__ as launcher

    root = tmp_path / "runtime"
    receipt = {
        "pid": 123,
        "role": "pdp",
        "uid": 22014,
        "root": str(root),
        "session": "imp03-002",
        "starttime": "111",
    }
    monkeypatch.setattr(
        launcher,
        "load",
        lambda path, **_: receipt if path.name == "process.json" else {"uid": 22014},
    )
    monkeypatch.setattr(launcher, "process_start", lambda _: "222" if stale else "111")
    command = b"\0".join(
        [
            b"python",
            b"-m",
            b"tools.imp03_runtime",
            b"serve",
            b"--root",
            str(root).encode(),
            b"--role",
            b"pdp",
        ]
    )

    class ProcessPath:
        def __truediv__(self, _):
            return self

        def stat(self):
            return SimpleNamespace(st_uid=22014)

        def read_bytes(self):
            return command

    monkeypatch.setattr(launcher, "Path", lambda _: ProcessPath())
    opened, sent, closed = [], [], []
    monkeypatch.setattr(
        launcher.os, "pidfd_open", lambda pid: opened.append(pid) or 77, raising=False
    )
    monkeypatch.setattr(
        launcher.signal, "pidfd_send_signal", lambda fd, sig: sent.append((fd, sig)), raising=False
    )
    monkeypatch.setattr(launcher.os, "close", closed.append)
    if stale:
        with pytest.raises(ValueError, match="birth"):
            launcher.fault(root, "pdp", "pause")
        assert not sent
    else:
        launcher.fault(root, "pdp", "pause")
        assert sent == [(77, launcher.signal.SIGSTOP)]
    assert opened == [123] and closed == [77]


def test_generated_fence_contract_passes_real_constructor_custody_validation(tmp_path, monkeypatch):
    import os
    import tempfile

    from care_link_workload_trust import FenceServer, FenceStore

    value = binding(tmp_path)
    destination = tmp_path / "mesh"
    render(value, destination)
    config = json.loads((destination / "fence.json").read_text())
    assert config["uid"] != config["restrict_uid"]
    # Map only owner/group/socket paths to the available test custodian. Retain
    # generated restriction/read UID separation through the real constructor.
    with tempfile.TemporaryDirectory(prefix="cl03-fence-", dir="/tmp") as name:
        directory = Path(name).resolve()
        ledger = directory / "ledger"
        ledger.mkdir(mode=0o700)
        socket_directory = directory / "socket"
        socket_directory.mkdir(mode=0o710)
        socket_directory.chmod(0o710)
        os.chown(socket_directory, -1, os.getegid())
        store = FenceStore(ledger, os.geteuid())
        store.initialize(frozenset(config["allowed"]))

        def before_bind(_server):
            raise RuntimeError("test reached OS bind after custody validation")

        # Avoid a sandbox-dependent actual socket bind; the real constructor
        # must pass every custody check before reaching this exact sentinel.
        monkeypatch.setattr(FenceServer, "server_bind", before_bind)
        with pytest.raises(RuntimeError, match="reached OS bind"):
            FenceServer(
                socket_directory / "f.sock",
                store,
                owner_uid=os.geteuid(),
                access_gid=os.getegid(),
                restrict_uid=config["restrict_uid"],
                read_uids=frozenset(config["read_uids"]),
            )
