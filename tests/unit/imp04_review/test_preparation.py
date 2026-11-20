"""Fresh-only boundaries; these checks never deploy or contact live services."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tools.imp04_review.preparation import NeverServedCore, replace_role_file, target_admin_dsn


def offline(tmp_path, monkeypatch):
    root = tmp_path / "configuration"
    root.mkdir()
    configs = {}
    for role in ("identity", "core", "data", "pdp", "journal"):
        (root / role).mkdir()
        configs[role] = {"backend_socket": str(root.parent / role / "backend" / "app.sock")}
    (root.parent / "core" / "backend").mkdir(parents=True)
    # Unit seam for the Linux mount check; no mounts or sockets are created.
    monkeypatch.setattr(os.path, "ismount", lambda path: path == root.parent / "core" / "backend")
    return NeverServedCore(root, configs, str(uuid4()))


def test_never_served_callback_performs_real_offline_checks_each_time(tmp_path, monkeypatch):
    guard = offline(tmp_path, monkeypatch)
    assert guard.retire_views(guard.run_id)["verified_never_served"] is True
    (guard.root / "identity" / "process.json").write_text("{}")
    with pytest.raises(ValueError, match="serving receipt"):
        guard.retire_views(guard.run_id)


def test_absent_unmounted_socket_path_is_not_offline_evidence(tmp_path, monkeypatch):
    guard = offline(tmp_path, monkeypatch)
    monkeypatch.setattr(os.path, "ismount", lambda _path: False)
    with pytest.raises(ValueError, match="mount"):
        guard.verify()


def test_stale_or_active_backend_and_foreign_run_are_refused(tmp_path, monkeypatch):
    guard = offline(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Exact fresh run"):
        guard.retire_views(str(uuid4()))
    Path(guard.configs["core"]["backend_socket"]).touch()
    with pytest.raises(ValueError, match="activated"):
        guard.verify()


def test_admin_database_derivation_preserves_only_exact_owned_tls_endpoint():
    common = {
        "host": "postgres.imp04.internal",
        "hostaddr": "127.0.0.1",
        "port": "5432",
        "sslmode": "verify-full",
        "sslrootcert": "/owned/shared-ca.crt",
    }
    runtime = make_conninfo(
        "",
        **common,
        dbname="imp04_runtime_002",
        user="imp04_data_runtime_002",
    )
    admin = make_conninfo("", **common, dbname="postgres", user="postgres")
    target = conninfo_to_dict(target_admin_dsn(admin, runtime, "data"))
    assert target["dbname"] == "imp04_runtime_002"
    assert target["user"] == "postgres" and target["sslmode"] == "verify-full"
    foreign = make_conninfo(admin, host="foreign.invalid")
    with pytest.raises(ValueError, match="pinned database endpoint"):
        target_admin_dsn(foreign, runtime, "data")


def test_role_publication_preserves_owner_private_mode_and_refuses_symlinks(tmp_path, monkeypatch):
    ownership = []
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: ownership.append((fd, uid, gid)))
    private = tmp_path / "role"
    private.mkdir(mode=0o700)
    path = private / "registry.json"
    replace_role_file(path, b"{}", os.geteuid())
    replace_role_file(path, b'{"run":"new"}', os.geteuid())
    assert path.stat().st_uid == os.geteuid() and path.stat().st_mode & 0o077 == 0
    target = private / "unrelated.json"
    target.write_text("unchanged")
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ValueError, match="private file"):
        replace_role_file(path, b"changed", os.geteuid())
    assert target.read_text() == "unchanged"
    assert len(ownership) == 2
    assert all((uid, gid) == (os.geteuid(), os.geteuid()) for _fd, uid, gid in ownership)


def test_missing_privileged_proof_and_automatic_provider_are_rejected_before_authentication():
    from types import SimpleNamespace

    from tools.imp04_review.preparation import authenticated_privileged

    identity = SimpleNamespace(review_context=None, interactive_policy=None, provider=object())
    with pytest.raises(ValueError, match="Both genuine"):
        authenticated_privileged(identity, {"operator_session": "test-only"}, {})
    with pytest.raises(ValueError, match="ordinary provider"):
        authenticated_privileged(
            identity, {"operator_session": "test-only", "security_session": "test-only"}, {}
        )
