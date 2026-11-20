"""Scoped administrative boundaries; mocks never assert live provider authority."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from tools.imp04_deployment import authority_case as case
from tools.imp04_deployment.config import MAIN, PREFIX, PROVIDER, REALM, load, write


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(case, "PRIVATE", tmp_path)
    actors = {
        slot: {
            "accountId": str(uuid4()),
            "role": "carer" if slot == "carer" else slot,
            "username": "synthetic-" + slot,
            "password": "original-test-password",
            "totpSecret": "original-test-otp",
        }
        for slot in [
            "pid",
            "pid-other",
            "carer",
            "professional",
            "worker1",
            "worker2",
            "supervisor",
            "operator",
            "security",
        ]
    }
    write(
        tmp_path / "browser.json",
        json.dumps(
            {
                "mainOrigin": MAIN,
                "oidcOrigin": PROVIDER,
                "actors": actors,
                "endpoint": "private-test-capability",
                "caFile": "/private-test-ca",
            }
        ),
    )
    write(tmp_path / "inputs.json", json.dumps({"provider_admin_password": "private-test-admin"}))
    return tmp_path, case.prepare()


def admitted() -> dict:
    value = case.case()
    value.update(
        phase="delegation_admitted",
        provider_subject=str(uuid4()),
        subject_id=str(uuid4()),
        delegation_id=str(uuid4()),
    )
    case.save(value)
    return value


def proof_document(value, *, expired=False):
    expiry = datetime.now(UTC) + timedelta(seconds=-1 if expired else 0.95)
    evidence = {
        "principal_id": value["operator_account_id"],
        "role": "operator",
        "action": case.ACTION,
        "request_digest": case.binding(value),
        "nonce": value["nonce"],
        "expires_at": expiry.isoformat().replace("+00:00", "Z"),
        "signature": "private-test-signed-proof",
    }
    return {
        "version": case.VERSION,
        **case.public(value),
        "operator_account_id": value["operator_account_id"],
        "expected_identity_revision": "1",
        "evidence": evidence,
    }


def test_prepare_creates_only_private_new_case_and_public_metadata(prepared):
    root, receipt = prepared
    before = load(root / "browser.json")
    value = case.case()
    assert receipt["phase"] == "prepared"
    assert receipt["account_id"] not in {x["accountId"] for x in before["actors"].values()}
    assert (root / case.CASE_NAME).stat().st_mode & 0o077 == 0
    assert not ({"password", "totp_secret", "signature", "evidence"} & receipt.keys())
    assert load(root / "browser.json") == before
    with pytest.raises(FileExistsError):
        case.prepare()
    assert case.case() == value


def test_existing_actor_substitution_is_refused_before_any_operator(prepared, monkeypatch):
    root, _receipt = prepared
    value = case.case()
    value["account_id"] = load(root / "browser.json")["actors"]["carer"]["accountId"]
    case.save(value)
    monkeypatch.setattr(case.docker, "exec", lambda *_a, **_k: pytest.fail("must not execute"))
    with pytest.raises(ValueError, match="separately created"):
        case.restrict()


def test_uncertain_provider_creation_is_not_retried_or_adopted(prepared, monkeypatch):
    def uncertain(_value):
        raise RuntimeError("mock provider outcome uncertain")

    monkeypatch.setattr(case, "create_provider", uncertain)
    monkeypatch.setattr(case, "operator", lambda *_a, **_k: pytest.fail("must not provision"))
    with pytest.raises(RuntimeError):
        case.setup()
    assert case.case()["phase"] == "provider_create_pending"
    with pytest.raises(ValueError, match="never adopted"):
        case.setup()


@pytest.mark.parametrize(
    "location",
    [
        "https://foreign.invalid/admin/realms/" + REALM + "/users/" + str(uuid4()),
        PROVIDER + "/admin/realms/another/users/" + str(uuid4()),
        "/admin/realms/" + REALM + "/users/not-an-issued-uuid",
        "/admin/realms/" + REALM + "/users/" + str(uuid4()) + "?target=other",
    ],
)
def test_provider_location_cannot_select_another_target(location):
    with pytest.raises(ValueError):
        case.issued_subject(location)


def test_provider_subject_is_verified_with_actual_location_and_user_read(prepared, monkeypatch):
    issued = str(uuid4())
    created = []

    def transport(request):
        assert request.url.host == "id.plans.localhost"
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "private-test-token"})
        assert request.headers["authorization"] == "Bearer private-test-token"
        if request.method == "POST":
            created.append(json.loads(request.content))
            return httpx.Response(
                201, headers={"location": PROVIDER + "/admin/realms/" + REALM + "/users/" + issued}
            )
        if request.url.path.endswith("/credentials"):
            return httpx.Response(200, json=[{"type": "password"}, {"type": "otp"}])
        return httpx.Response(
            200, json={"id": issued, "username": case.case()["username"], "enabled": True}
        )

    monkeypatch.setattr(
        case,
        "provider_client",
        lambda: httpx.Client(base_url=PROVIDER, transport=httpx.MockTransport(transport)),
    )
    assert case.create_provider(case.case()) == issued
    assert len(created) == 1
    assert {x["type"] for x in created[0]["credentials"]} == {"password", "otp"}
    assert "realmRoles" not in created[0]


def test_setup_clone_changes_only_case_carer_slot(prepared, monkeypatch):
    root, _receipt = prepared
    original = copy.deepcopy(load(root / "browser.json"))
    issued = str(uuid4())
    monkeypatch.setattr(case, "create_provider", lambda _value: issued)
    monkeypatch.setattr(
        case,
        "operator",
        lambda *_a: {"identity_binding_created": True, "business_principal_created": True},
    )
    result = case.setup()
    cloned = load(root / case.BROWSER_NAME)
    assert result["provider_subject"] == issued
    assert cloned["actors"]["carer"]["accountId"] == result["account_id"]
    assert cloned["actors"]["carer"]["role"] == "carer"
    for slot in original["actors"]:
        if slot != "carer":
            assert cloned["actors"][slot] == original["actors"][slot]
    assert load(root / "browser.json") == original


def test_native_operator_cookie_requires_exact_new_main_origin(prepared):
    root, _receipt = prepared
    state = root / "sessions"
    state.mkdir(mode=0o700)
    path = state / "operator.json"
    write(
        path,
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "__Host-care-link-session",
                        "domain": "another.localhost",
                        "path": "/",
                        "secure": True,
                        "value": "private-test-cookie",
                    }
                ]
            }
        ),
    )
    with pytest.raises(ValueError, match="main-origin"):
        case.operator_cookie(path)


def test_proof_scope_digest_covers_target_revision_operation_and_nonce(prepared):
    value = admitted()
    original = case.binding(value)
    for key in ["account_id", "operation_id", "nonce"]:
        changed = {**value, key: str(uuid4())}
        assert case.binding(changed) != original


def test_expired_proof_refuses_before_live_operation_and_is_never_renewed(prepared, monkeypatch):
    root, _receipt = prepared
    value = admitted()
    write(root / case.PROOF_NAME, json.dumps(proof_document(value, expired=True)))
    monkeypatch.setattr(case.docker, "exec", lambda *_a, **_k: pytest.fail("must not execute"))
    with pytest.raises(ValueError, match="expired"):
        case.restrict()
    with pytest.raises(ValueError, match="never renewed"):
        case.proof(root / "sessions/operator.json")
    assert case.case()["phase"] == "delegation_admitted"


def test_restriction_checks_exact_new_receipt_and_never_restores_it(prepared, monkeypatch):
    root, _receipt = prepared
    value = admitted()
    write(root / case.PROOF_NAME, json.dumps(proof_document(value)))
    calls = []

    def execute(name, argv, *, stdin):
        calls.append((name, json.loads(stdin)))
        return json.dumps(
            {
                "principal_revoked": True,
                "result": {
                    "operation_id": value["operation_id"],
                    "state": "committed",
                    "resource_id": value["account_id"],
                    "revision": "2",
                    "audit_ref": str(uuid4()),
                },
            }
        )

    monkeypatch.setattr(case.docker, "exec", execute)
    result = case.restrict()
    assert calls[0][0] == PREFIX + "-data-app"
    assert result["principal_id"] == value["account_id"]
    assert result["principal_revoked"] is result["revoked"] is True
    assert case.case()["phase"] == "restricted"
    with pytest.raises(ValueError, match="unmodified"):
        case.restrict()


def test_busy_operator_is_not_adopted_or_stopped(prepared, monkeypatch):
    monkeypatch.setattr(
        case.docker, "inspect_container", lambda _name: {"State": {"Status": "running"}}
    )
    monkeypatch.setattr(case.docker, "start", lambda _name: pytest.fail("must not start"))
    monkeypatch.setattr(case.docker, "stop", lambda _name: pytest.fail("must not stop"))
    with pytest.raises(ValueError, match="another operation"):
        case.operator("pass", {})


def test_failed_operator_always_stops_its_own_seed(prepared, monkeypatch):
    calls = []
    monkeypatch.setattr(
        case.docker, "inspect_container", lambda _name: {"State": {"Status": "exited"}}
    )
    monkeypatch.setattr(case.docker, "start", lambda name: calls.append(("start", name)))
    monkeypatch.setattr(case.docker, "stop", lambda name: calls.append(("stop", name)))

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("mock bounded operator failure")

    monkeypatch.setattr(case.docker, "exec", unavailable)
    with pytest.raises(RuntimeError):
        case.operator("pass", {})
    assert calls == [("start", PREFIX + "-operator-seed"), ("stop", PREFIX + "-operator-seed")]


def test_warm_channel_opens_before_proof_and_accepts_only_fixed_action(
    prepared, monkeypatch, capsys
):
    import io

    root, _receipt = prepared
    value = admitted()
    responses = []
    forwarded = []

    class Pipe(io.StringIO):
        def write(self, text):
            forwarded.append(text)
            return super().write(text)

    class Child:
        stdin = Pipe()
        stdout = io.StringIO()

        def wait(self, timeout=None):
            return 0

    def opened(argv, **_kwargs):
        assert not (root / case.PROOF_NAME).exists(), "Service is warmed before proof exists"
        assert argv[3] == "d" * 64
        assert value["password"] not in " ".join(argv)
        return Child()

    def line(_stream, timeout=15):
        if not responses:
            responses.append("ready")
            return json.dumps({"ready": True, "target": PREFIX, "account_id": value["account_id"]})
        if len(responses) == 1:
            responses.append("request")
            write(root / case.PROOF_NAME, json.dumps(proof_document(value)))
            return json.dumps({"action": "restrict"})
        return json.dumps(
            {
                "principal_revoked": True,
                "result": {
                    "operation_id": value["operation_id"],
                    "state": "committed",
                    "resource_id": value["account_id"],
                    "revision": "2",
                    "audit_ref": str(uuid4()),
                },
            }
        )

    monkeypatch.setattr(case.docker, "inspect_container", lambda _name: {"Id": "d" * 64})
    monkeypatch.setattr(case.shutil, "which", lambda _name: "/fixed-test-docker")
    monkeypatch.setattr(case.subprocess, "Popen", opened)
    monkeypatch.setattr(case, "line_from", line)
    case.channel()
    shown = capsys.readouterr().out
    assert "private-test-signed-proof" not in shown
    assert "private-test-signed-proof" in forwarded[0]
    assert json.loads(shown.splitlines()[-1])["principal_revoked"] is True
    assert case.case()["phase"] == "restricted"


def test_warm_channel_never_forwards_node_supplied_proof_or_other_target(prepared, monkeypatch):
    import io

    _root, _receipt = prepared
    value = admitted()
    responses = iter(
        [
            json.dumps({"ready": True, "target": PREFIX, "account_id": value["account_id"]}),
            json.dumps({"action": "restrict", "principal_id": str(uuid4()), "evidence": {}}),
        ]
    )
    writes = []

    class Pipe(io.StringIO):
        def write(self, text):
            writes.append(text)
            return super().write(text)

    class Child:
        stdin = Pipe()
        stdout = io.StringIO()

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(case.docker, "inspect_container", lambda _name: {"Id": "d" * 64})
    monkeypatch.setattr(case.shutil, "which", lambda _name: "/fixed-test-docker")
    monkeypatch.setattr(case.subprocess, "Popen", lambda *_a, **_k: Child())
    monkeypatch.setattr(case, "line_from", lambda *_a, **_k: next(responses))
    with pytest.raises(ValueError, match="fixed case restriction"):
        case.channel()
    assert writes == []
    assert case.case()["phase"] == "delegation_admitted"


@pytest.mark.parametrize("changed", ["pid", "floor", "missing_floor"])
def test_subject_guard_floor_and_original_pid_are_required_before_any_phase(prepared, changed):
    value = case.case()
    if changed == "pid":
        value["pid_account_id"] = str(uuid4())
    elif changed == "floor":
        value["guard_floor_at"] = "2026-11-16T00:00:00"
    else:
        del value["guard_floor_at"]
    case.save(value)
    with pytest.raises(ValueError):
        case.setup()
