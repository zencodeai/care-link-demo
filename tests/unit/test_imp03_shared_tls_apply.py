"""Mock-runner apply boundaries; no Docker/Kubernetes/TLS service is contacted."""

import base64
import json
import tempfile
from pathlib import Path

import pytest

from tools.imp02_application.prepare import prepare as initial_pki
from tools.imp03_shared import tls_apply, tls_renewal


def save(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)


class LabRunner:
    def __init__(
        self,
        root,
        *,
        wrong_cluster=False,
        patch_conflict=False,
        postgres_changed=False,
        fail_node=False,
    ):
        self.calls = []
        self.wrong_cluster = wrong_cluster
        self.patch_conflict = patch_conflict
        self.postgres_changed = postgres_changed
        self.reloaded = False
        self.patch = None
        self.created = 0
        self.fail_node = fail_node
        self.root = root
        self.secret = {
            "metadata": {
                "name": tls_apply.PKI_NAME,
                "namespace": tls_apply.NAMESPACE,
                "resourceVersion": "initial-version",
            },
            "data": {
                name: base64.b64encode((root / "secrets" / name).read_bytes()).decode()
                for name in [
                    *tls_apply.SECRET_CERT_KEYS,
                    *(name + ".key" for name in ("postgres", "keycloak")),
                ]
            },
        }
        self.secret["data"]["unchanged-extra"] = base64.b64encode(b"opaque-private-state").decode()
        self.node_files = {
            path: (root / "secrets" / name).read_bytes()
            for name, (path, _) in tls_apply.NODE_FILES.items()
        }
        self.volumes = {
            name: self.volume((root / "secrets" / (name + ".crt")).read_bytes())
            for name in ("help", "static")
        }

    def volume(self, pem):
        return {
            "pem": base64.b64encode(pem).decode(),
            "sha256": tls_apply._digest(pem),
            "uid": 21002,
            "gid": 21002,
            "mode": 0o600,
        }

    def container(self, name):
        value = {
            "Name": "/" + name,
            "Id": "fixed-" + name,
            "State": {"Running": True, "StartedAt": "unchanged-start"},
            "RestartCount": 0,
            "Config": {"Labels": {}},
            "Mounts": [],
        }
        if name == tls_apply.NODE:
            value["Config"]["Labels"] = {
                "io.x-k8s.kind.cluster": "wrong" if self.wrong_cluster else tls_apply.CLUSTER
            }
        for target, volume in (
            (tls_apply.HOST_PROXY, tls_apply.HELP_VOLUME),
            (tls_apply.STATIC, tls_apply.STATIC_VOLUME),
        ):
            if name == target:
                value["Mounts"] = [{"Type": "volume", "Name": volume, "Destination": "/config"}]
        return value

    def __call__(self, arguments, *, input=None, timeout=30):
        self.calls.append(arguments)
        if arguments[:2] == ["docker", "inspect"]:
            return json.dumps([self.container(name) for name in arguments[2:]]).encode()
        if arguments[:2] == ["docker", "create"]:
            self.created += 1
            return ("a" * 60 + f"{self.created:04x}").encode()
        if arguments[:2] == ["docker", "start"]:
            command = json.loads(input)
            if command["action"] == "write":
                for name, values in command["certificates"].items():
                    assert self.volumes[name]["sha256"] == values["expected_old_sha256"]
                    self.volumes[name] = self.volume(base64.b64decode(values["pem"]))
            return json.dumps(self.volumes).encode()
        if arguments[:2] == ["docker", "rm"]:
            return arguments[-1].encode()
        if arguments[:2] == ["docker", "cp"]:
            raise AssertionError("Node renewal must not use Docker archive staging")
        if arguments[:4] == ["docker", "exec", "--interactive", tls_apply.NODE]:
            if self.fail_node:
                raise RuntimeError("fixture node stage failure")
            target = next(
                path
                for path, _ in tls_apply.NODE_FILES.values()
                if "'" + path + "'" in arguments[-1]
            )
            assert input is not None
            self.node_files[target] = input
            return b""
        if arguments[:3] == ["docker", "exec", tls_apply.NODE]:
            if arguments[3] == "cat":
                return self.node_files[arguments[4]]
            if arguments[3] == "stat":
                uid = next(
                    uid for path, uid in tls_apply.NODE_FILES.values() if path == arguments[-1]
                )
                return f"{uid}:{uid}:600\n".encode()
            return b""
        if arguments[:2] == ["docker", "restart"]:
            assert arguments[-1] in (tls_apply.HOST_PROXY, tls_apply.STATIC)
            return arguments[-1].encode()
        assert arguments[0] == "kubectl"
        assert arguments[arguments.index("--context") + 1] == tls_apply.CONTEXT
        assert arguments[arguments.index("--kubeconfig") + 1] == str(
            self.root / "cluster/kubeconfig"
        )
        if "get" in arguments:
            kind = arguments[arguments.index("get") + 1]
            if kind == "secret":
                return json.dumps(self.secret).encode()
            assert kind == "pods"
            return json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"uid": "same-postgres-pod"},
                            "status": {
                                "phase": "Running",
                                "containerStatuses": [
                                    {"name": "postgres", "ready": True, "restartCount": 0}
                                ],
                            },
                        }
                    ]
                }
            ).encode()
        if "patch" in arguments:
            if self.patch_conflict:
                raise RuntimeError("fixture resourceVersion conflict")
            self.patch = json.loads(
                Path(arguments[arguments.index("--patch-file") + 1]).read_text()
            )
            assert self.patch["metadata"]["resourceVersion"] == "initial-version"
            self.secret["data"].update(self.patch["data"])
            self.secret["metadata"]["resourceVersion"] = "updated-version"
            return json.dumps(self.secret).encode()
        if "sha256sum" in arguments:
            return "\n".join(
                tls_apply._digest(base64.b64decode(self.secret["data"][Path(path).name]))
                + "  "
                + path
                for path in arguments[arguments.index("sha256sum") + 1 :]
            ).encode()
        if "exec" in arguments:
            if arguments[-1] == "SELECT pg_reload_conf();":
                self.reloaded = True
                return b"t\n"
            assert arguments[-1] == "SELECT pg_postmaster_start_time();"
            return (
                b"changed-start\n" if self.reloaded and self.postgres_changed else b"same-start\n"
            )
        assert "rollout" in arguments
        return b"ready\n"


@pytest.fixture
def proposal(monkeypatch):
    with tempfile.TemporaryDirectory(
        prefix="care-link-imp03-tls-unit-", dir="/private/tmp"
    ) as temp:
        directory = Path(temp)
        root = directory / "lab"
        root.mkdir(mode=0o700)
        initial_pki(root / "secrets")
        cluster = root / "cluster"
        cluster.mkdir(mode=0o700)
        save(cluster / "lease.json", {"session": "imp02-002", "cluster": tls_apply.CLUSTER})
        save(cluster / "kubeconfig", {"fixture": True})
        candidate = directory / "candidate"
        tls_renewal.prepare(root, candidate)
        monkeypatch.setattr(tls_apply, "ROOT", root)
        monkeypatch.setattr(tls_apply, "_verify_tls", lambda run, candidate: {"fixture_only": True})
        yield root, candidate, directory / "backup"


def test_apply_only_changes_certificate_entries_and_exact_reload_targets(proposal):
    root, candidate, backup = proposal
    run = LabRunner(root)
    old_other = {
        name: value
        for name, value in run.secret["data"].items()
        if name not in tls_apply.SECRET_CERT_KEYS
    }
    old_keys = {path.name: path.read_bytes() for path in (root / "secrets").glob("*.key")}
    result = tls_apply.apply(candidate, backup, runner=run)
    assert result["certificate_bindings_match"] is True
    assert set(run.patch) == {"metadata", "data"}
    assert set(run.patch["data"]) == set(tls_apply.SECRET_CERT_KEYS)
    assert old_other == {
        name: value
        for name, value in run.secret["data"].items()
        if name not in tls_apply.SECRET_CERT_KEYS
    }
    assert old_keys == {path.name: path.read_bytes() for path in (root / "secrets").glob("*.key")}
    for name in tls_apply.CERT_KEYS:
        assert (root / "secrets" / name).read_bytes() == (candidate / name).read_bytes()
    rollout = [args[-1] for args in run.calls if "rollout" in args and "restart" in args]
    assert rollout == ["deployment/keycloak", "deployment/identity", "deployment/main"]
    assert [args[-1] for args in run.calls if args[:2] == ["docker", "restart"]] == [
        tls_apply.HOST_PROXY,
        tls_apply.STATIC,
    ]
    assert all(
        args[args.index("-n") + 1] == tls_apply.NAMESPACE
        for args in run.calls
        if args[0] == "kubectl"
    )
    assert backup.stat().st_mode & 0o777 == 0o700
    assert (backup / "old-secret.json").stat().st_mode & 0o777 == 0o600
    assert all(
        "--network" in args
        and args[args.index("--network") + 1] == "none"
        and "--read-only" in args
        and "--cap-drop=ALL" in args
        for args in run.calls
        if args[:2] == ["docker", "create"]
    )


def test_wrong_node_cluster_label_refuses_before_shared_mutation(proposal):
    root, candidate, backup = proposal
    run = LabRunner(root, wrong_cluster=True)
    before = (root / "secrets/ca.crt").read_bytes()
    with pytest.raises(ValueError, match="exact running retained kind cluster"):
        tls_apply.apply(candidate, backup, runner=run)
    assert run.calls == [["docker", "inspect", tls_apply.NODE]]
    assert (root / "secrets/ca.crt").read_bytes() == before
    assert not (backup / "old-secret.json").exists()


def test_wrong_private_lease_refuses_even_before_docker_inspection(proposal):
    root, candidate, backup = proposal
    save(root / "cluster/lease.json", {"session": "wrong", "cluster": tls_apply.CLUSTER})
    run = LabRunner(root)
    with pytest.raises(ValueError, match="Wrong retained lab lease"):
        tls_apply.apply(candidate, backup, runner=run)
    assert not run.calls


def test_concurrent_secret_change_stops_before_local_file_mutation(proposal):
    root, candidate, backup = proposal
    run = LabRunner(root, patch_conflict=True)
    before = {path.name: path.read_bytes() for path in (root / "secrets").glob("*.crt")}
    with pytest.raises(RuntimeError, match="resourceVersion conflict"):
        tls_apply.apply(candidate, backup, runner=run)
    assert before == {path.name: path.read_bytes() for path in (root / "secrets").glob("*.crt")}
    assert (backup / "old-secret.json").exists()
    assert not any("restart" in args or "rollout" in args for args in run.calls)


def test_unexpected_postgres_restart_is_reported_without_automatic_restore(proposal):
    root, candidate, backup = proposal
    run = LabRunner(root, postgres_changed=True)
    with pytest.raises(ValueError, match="PostgreSQL process/pod identity changed"):
        tls_apply.apply(candidate, backup, runner=run)
    assert (backup / "old-secret.json").exists()
    assert (root / "secrets/ca.crt").read_bytes() == (candidate / "ca.crt").read_bytes()
    assert sum("patch" in args for args in run.calls) == 1


def test_verify_detects_extra_secret_entry_mutation(proposal):
    root, candidate, backup = proposal
    run = LabRunner(root)
    tls_apply.apply(candidate, backup, runner=run)
    run.secret["data"]["unchanged-extra"] = base64.b64encode(b"unexpected-change").decode()
    with pytest.raises(ValueError, match="outside exact certificate entries"):
        tls_apply.verify(candidate, backup, runner=run)


def test_second_apply_cannot_adopt_existing_backup(proposal):
    root, candidate, backup = proposal
    backup.mkdir(mode=0o700)
    run = LabRunner(root)
    with pytest.raises(ValueError, match="existing backup refused"):
        tls_apply.apply(candidate, backup, runner=run)
    assert not run.calls


def test_missing_required_secret_certificate_fails_before_any_shared_write(proposal):
    root, candidate, backup = proposal
    run = LabRunner(root)
    run.secret["data"].pop("postgres.crt")
    before = (root / "secrets/ca.crt").read_bytes()
    with pytest.raises(ValueError, match="certificate entries missing"):
        tls_apply.apply(candidate, backup, runner=run)
    assert run.patch is None
    assert (root / "secrets/ca.crt").read_bytes() == before
    assert not any("restart" in args or "rollout" in args for args in run.calls)


def failed_node_stage(root, candidate, backup):
    run = LabRunner(root, fail_node=True)
    with pytest.raises(RuntimeError, match="fixture node stage failure"):
        tls_apply.apply(candidate, backup, runner=run)
    run.fail_node = False
    run.calls.clear()
    return run


def test_explicit_node_resume_preserves_original_backup_and_does_not_repeat_patch(proposal):
    root, candidate, backup = proposal
    run = failed_node_stage(root, candidate, backup)
    originals = {
        name: (backup / name).read_bytes()
        for name in ("old-secret.json", "before.json", "old-public-bindings.json")
    }
    file_times = {
        name: (root / "secrets" / name).stat().st_mtime_ns for name in tls_apply.CERT_KEYS
    }
    result = tls_apply.resume_after_node_stage(candidate, backup, runner=run)
    assert result["resumed_after_node_stage"] is True
    assert all((backup / name).read_bytes() == value for name, value in originals.items())
    assert file_times == {
        name: (root / "secrets" / name).stat().st_mtime_ns for name in tls_apply.CERT_KEYS
    }
    assert not any("patch" in arguments for arguments in run.calls)
    assert not any(arguments[:2] == ["docker", "cp"] for arguments in run.calls)
    assert (
        len(
            [
                args
                for args in run.calls
                if args[:4] == ["docker", "exec", "--interactive", tls_apply.NODE]
            ]
        )
        == 2
    )


def test_node_resume_refuses_a_later_partial_volume_stage(proposal):
    root, candidate, backup = proposal
    run = failed_node_stage(root, candidate, backup)
    run.volumes["help"] = run.volume((candidate / "help.crt").read_bytes())
    with pytest.raises(ValueError, match="later-stage resume refused"):
        tls_apply.resume_after_node_stage(candidate, backup, runner=run)
    assert not any(
        args[:4] == ["docker", "exec", "--interactive", tls_apply.NODE] for args in run.calls
    )
    assert not any("restart" in args or "patch" in args for args in run.calls)


def test_node_resume_refuses_unrelated_secret_drift(proposal):
    root, candidate, backup = proposal
    run = failed_node_stage(root, candidate, backup)
    run.secret["data"]["unchanged-extra"] = "changed"
    with pytest.raises(ValueError, match="outside exact certificate entries"):
        tls_apply.resume_after_node_stage(candidate, backup, runner=run)
    assert not any(
        args[:4] == ["docker", "exec", "--interactive", tls_apply.NODE] for args in run.calls
    )


def test_node_resume_cannot_replay_completed_maintenance(proposal):
    root, candidate, backup = proposal
    run = LabRunner(root)
    tls_apply.apply(candidate, backup, runner=run)
    run.calls.clear()
    with pytest.raises(ValueError, match="Completed maintenance cannot be resumed"):
        tls_apply.resume_after_node_stage(candidate, backup, runner=run)
    assert not run.calls
