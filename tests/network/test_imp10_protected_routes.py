"""Exact protected route grants for opt-in IMP-10 workloads."""

from contextlib import ExitStack
from uuid import uuid4

import pytest
from care_link_workload_trust import SOCKET_PEER_SCOPE_KEY, SocketPeer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi.testclient import TestClient

from tools.imp03_runtime.config import protected_routes, routes, spiffe
from tools.imp06_runtime.routes import inbound, outbound
from tools.imp10_runtime.routes import (
    EVALUATION_ROUTES,
    HELP_AUTH_ROUTES,
    HELP_IDENTITY_ROUTES,
    TRAINING_IDENTITY_ROUTES,
    TRAINING_ROUTES,
)
from tools.imp10_runtime.serve import application


def test_manual_and_assisted_data_share_only_opted_in_replay_paths():
    for enabled in (False, True):
        manual = protected_routes({"training_enabled": enabled}, "data")["core"]
        assisted = {
            peer.spiffe_id: peer.routes for peer in inbound("data", training_enabled=enabled)
        }
        core = outbound("core", training_enabled=enabled)
        expected = EVALUATION_ROUTES if enabled else frozenset()
        assert manual & EVALUATION_ROUTES == expected
        assert assisted[spiffe("core")] & EVALUATION_ROUTES == expected
        assert core["data"] == assisted[spiffe("core")]
        assert core.get("training") == (TRAINING_ROUTES if enabled else None)
        assert not assisted["spiffe://care-link.demo/demo/inference"] & EVALUATION_ROUTES


def test_training_peer_only_resolves_and_rechecks_current_trainer_identity():
    assert protected_routes({}, "identity") == routes("identity")
    configured = protected_routes({"training_enabled": True}, "identity")
    assert configured["training"] == TRAINING_IDENTITY_ROUTES
    assert configured["core"] == routes("identity")["core"]
    assert configured["data"] == routes("identity")["data"]
    assert protected_routes({"training_enabled": True}, "training") == {"core": TRAINING_ROUTES}
    assert "training" not in outbound("runtime", training_enabled=True)
    with pytest.raises(ValueError, match="Training process"):
        protected_routes({}, "training")
    with pytest.raises(ValueError, match="Explicit boolean"):
        protected_routes({"training_enabled": "true"}, "data")


def test_private_help_is_exact_and_separate_from_manual_identity():
    configured = protected_routes({"help_identity": {}}, "identity")
    assert configured["help"] == HELP_AUTH_ROUTES | HELP_IDENTITY_ROUTES
    assert all(
        not path.startswith("/internal/v1/manual-identity/") for _, path in configured["help"]
    )
    assert configured["help"].isdisjoint(configured["core"] | configured["data"])
    with pytest.raises(ValueError, match="Configuration object"):
        protected_routes({"help_identity": True}, "identity")


def test_protected_launcher_rejects_legacy_profiles_and_wrong_role_credentials(monkeypatch):
    monkeypatch.setattr("tools.imp10_runtime.serve.os.geteuid", lambda: 22031)
    config = {"session": "imp10-protected", "role": "training", "uid": 22031, "proxy_uid": 22002}
    with pytest.raises(ValueError, match="explicit IMP-10"):
        application("training", {**config, "session": "imp03-002"})
    with pytest.raises(ValueError, match="independent proxy"):
        application("data", config)
    with pytest.raises(ValueError, match="independent proxy"):
        application("training", {**config, "proxy_uid": 22031})


def test_core_startup_exposes_only_the_explicitly_enabled_training_surface(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.imp10_runtime.serve.os.geteuid", lambda: 22031)
    identity_public = tmp_path / "identity.pem"
    identity_public.write_bytes(
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    core_private = tmp_path / "core.pem"
    core_private.write_bytes(
        Ed25519PrivateKey.generate().private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )
    )
    (tmp_path / "index.html").write_text("Synthetic training shell")
    config = {
        "session": "imp10-protected",
        "role": "core",
        "uid": 22031,
        "proxy_uid": 22002,
        "fence_uid": 22000,
        "fence_socket": str(tmp_path / "fence.sock"),
        "identity_public_key": str(identity_public),
        "core_signing_key": str(core_private),
        "web_directory": str(tmp_path),
        "outbound": {
            role: {"socket": str(tmp_path / (role + ".sock")), "origin": f"https://{role}:8443"}
            for role in ("identity", "data", "pdp", "training")
        },
    }

    def through_proxy(app):
        async def dispatch(scope, receive, send):
            await app({**scope, SOCKET_PEER_SCOPE_KEY: SocketPeer(22002)}, receive, send)

        return dispatch

    path = f"/v1/evaluation/replays/{uuid4()}"
    with ExitStack() as stack:
        ordinary = stack.enter_context(TestClient(through_proxy(application("core", config))))
        enabled = application("core", {**config, "training_enabled": True})
        admitted = stack.enter_context(TestClient(through_proxy(enabled)))
        assert TestClient(enabled).get("/training").status_code == 403
        assert ordinary.get("/training").status_code == ordinary.get(path).status_code == 404
        assert admitted.get("/training").text == "Synthetic training shell"
        assert admitted.get(path).status_code == 401

    missing = {
        **config,
        "training_enabled": True,
        "outbound": {k: v for k, v in config["outbound"].items() if k != "training"},
    }
    with pytest.raises((KeyError, ValueError), match="training"):
        application("core", missing)


def test_help_accepts_only_the_configured_kernel_peer(monkeypatch):
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/dev/health")
    def health():
        return {"state": "ready"}

    monkeypatch.setattr("tools.imp10_runtime.serve.os.geteuid", lambda: 22031)
    monkeypatch.setattr("tools.imp02_application.__main__.compose", lambda *_: app)
    composition = application(
        "help", {"session": "imp10-protected", "role": "help", "uid": 22031, "proxy_uid": 22002}
    )

    def browser(uid):
        async def observed(scope, receive, send):
            await composition({**scope, SOCKET_PEER_SCOPE_KEY: SocketPeer(uid)}, receive, send)

        return TestClient(observed)

    path = "/dev/health"
    assert TestClient(composition).get(path).status_code == 403
    assert browser(22031).get(path).status_code == 403
    assert browser(22002).get(path).json() == {"state": "ready"}
