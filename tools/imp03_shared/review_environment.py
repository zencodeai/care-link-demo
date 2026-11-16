"""Owned continuation operator, public-context publisher and trust steward.

This composition root performs effects only when explicitly constructed/served
by the authorized coordinator. Importing it selects no operator profile.
"""

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx
from care_link_data import ReviewRunAdmin

from tools.demo.models import Environment, Record, record, text
from tools.demo.secrets import credential
from tools.demo.storage import Registry, private_directory, private_read, private_write
from tools.imp02_application.tls import PinnedAddressTransport

from .review_operator import OperatorServer, ReviewOperator
from .review_provider import BASE, LEGACY_ORIGIN, ProviderAdmin, ReviewProviderError
from .review_provider_group import ProviderGroup, provider_admin


def require_profile() -> None:
    if os.environ.get("CARE_LINK_IMP03_PROFILE") != "continuation-001":
        raise ValueError("Explicit continuation-001 profile required")
    from .profiles import ACTIVE

    if ACTIVE.name != "continuation-001":
        raise ValueError("Operator profile was imported under a different scope")


def load_private(path: Path) -> Record:
    return record(json.loads(private_read(path)))


def _canonical(value: Record) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class ContextPublisher:
    def __init__(
        self,
        environment: Environment,
        targets: list[Record],
        *,
        inspect: Callable[[str], Record] | None = None,
        execute: Callable[[list[str], str], str] | None = None,
    ) -> None:
        self.environment, self.targets = environment, targets
        self.inspect = inspect or self._inspect
        self.execute = execute or self._execute
        if len(targets) != 2 or {item.get("uid") for item in targets} != {22011, 22012}:
            raise ValueError("Exact core/identity public context custodians required")
        for target in targets:
            if set(target) != {"container", "container_id", "path", "uid"}:
                raise ValueError("Exact public-context target fields required")
            uid = target["uid"]
            role = "identity" if uid == 22011 else "core"
            if (
                target["container"] != f"care-link-imp03-003-cont1-{role}-app"
                or target["path"]
                != f"/run/care-link-imp03-002/configuration/{role}/review-contexts.json"
                or not re.fullmatch(r"[0-9a-f]{64}", text(target, "container_id"))
            ):
                raise ValueError("Context target outside exact continuation binding")

    @staticmethod
    def _inspect(name: str) -> Record:
        require_profile()
        from .docker import inspect_container

        return inspect_container(name)

    @staticmethod
    def _execute(args: list[str], payload: str) -> str:
        require_profile()
        try:
            result = subprocess.run(  # noqa: S603 - exact inspected ID/UID, no shell
                ["docker", "container", "exec", "--interactive", *args],  # noqa: S607
                input=payload,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Public-context publication unavailable") from None
        if result.returncode:
            raise ValueError("Public-context publication unconfirmed")
        return result.stdout.strip()

    def check_targets(self) -> None:
        for target in self.targets:
            value = self.inspect(text(target, "container"))
            if (
                value.get("Id") != target["container_id"]
                or record(value["Config"]).get("User") != f"{target['uid']}:{target['uid']}"
            ):
                raise ValueError("Public-context container identity changed")

    def __call__(self, contexts: Record) -> None:
        payload = _canonical(contexts).decode()
        # Both runtime readers enforce this bound. Refuse before either target
        # is changed, preserving the last usable registry and retained history.
        if len(payload.encode()) > 262144:
            raise ValueError("Public context registry capacity exceeded")
        actors = record(self.environment.value["actors"])
        for origin, raw in contexts.items():
            context = record(raw)
            if set(context) != {
                "run_id",
                "slot_id",
                "account_id",
                "provider_subject",
                "role",
                "state",
            }:
                raise ValueError("Public context has unknown fields")
            run_id, slot = text(context, "run_id"), text(context, "slot_id")
            if slot not in actors or self.environment.origins(run_id)[slot] != origin:
                raise ValueError("Public context origin changed")
            expected = record(actors[slot])
            if any(
                context[key] != expected[key] for key in ("account_id", "provider_subject", "role")
            ) or context["state"] not in {"active", "closing", "closed"}:
                raise ValueError("Public context actor/state changed")
        self.check_targets()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        script = (
            "import hashlib,os,stat,sys;from pathlib import Path;from uuid import uuid4;"
            "p=Path(sys.argv[1]);u=int(sys.argv[2]);d=p.parent.lstat();"
            "assert d.st_uid==u and stat.S_ISDIR(d.st_mode) and d.st_mode&0o077==0;"
            "s=p.lstat() if p.exists() or p.is_symlink() else None;"
            "assert s is None or (s.st_uid==u and stat.S_ISREG(s.st_mode) "
            "and s.st_mode&0o777==0o600);"
            "v=sys.stdin.buffer.read();t=p.with_name('.review-'+uuid4().hex);"
            "f=os.open(t,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);"
            "o=os.fdopen(f,'wb');o.write(v);o.flush();os.fsync(o.fileno());o.close();"
            "os.replace(t,p);f=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY);os.fsync(f);os.close(f);"
            "print(hashlib.sha256(p.read_bytes()).hexdigest())"
        )
        for target in self.targets:
            # Exec by inspected immutable ID and original configured UID; a name
            # replacement between inspection and execution cannot redirect writes.
            observed = self.execute(
                [
                    "--user",
                    f"{target['uid']}:{target['uid']}",
                    text(target, "container_id"),
                    "python",
                    "-c",
                    script,
                    text(target, "path"),
                    str(target["uid"]),
                ],
                payload,
            )
            if observed != digest:
                raise ValueError("Public-context publication digest mismatch")


class TrustSteward:
    def __init__(self, refresh: Callable[[], object], status_path: Path) -> None:
        self.refresh, self.status_path = refresh, status_path
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.last_success: float | None = None
        self.failed = True
        self.thread = threading.Thread(target=self._run, name="review-trust-steward", daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            result: Record = {"checked_at": time.time(), "state": "unavailable"}
            try:
                self.refresh()
                with self.lock:
                    self.last_success, self.failed = time.monotonic(), False
                result["state"] = "current"
            except Exception as error:
                with self.lock:
                    self.failed = True
                result["error_class"] = type(error).__name__
            try:
                private_write(self.status_path, _canonical(result))
            except (OSError, ValueError):
                with self.lock:
                    self.failed = True
                self.stop.set()
            self.stop.wait(30)

    def current(self) -> bool:
        with self.lock:
            return (
                not self.failed
                and not self.stop.is_set()
                and self.thread.is_alive()
                and self.last_success is not None
                and time.monotonic() - self.last_success < 65
            )

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=30)


class CredentialRotation:
    def __init__(
        self,
        environment: Environment,
        state_path: Path,
        password_path: Path,
        ca_file: Path,
        receipts: Path,
    ) -> None:
        self.environment, self.state_path = environment, state_path
        self.password_path, self.ca_file, self.receipts = password_path, ca_file, receipts
        private_directory(receipts, create=True)

    def _provider(self, state: Record) -> ProviderAdmin | ProviderGroup:
        password = private_read(self.password_path).decode().strip()
        return provider_admin(state, password, self.ca_file)

    def __call__(self, request: Record) -> Record:
        with Registry(self.receipts).lock("credential-rotation"):
            return self._locked(request)

    def _locked(self, request: Record) -> Record:
        if (
            set(request)
            != {
                "environment_id",
                "slot",
                "account_id",
                "operation_id",
                "previous_revision",
                "credential_revision",
                "credential",
            }
            or request["environment_id"] != self.environment.id
        ):
            raise ValueError("Exact credential rotation request required")
        operation_id, slot = text(request, "operation_id"), text(request, "slot")
        if str(UUID(operation_id)) != operation_id:
            raise ValueError("Canonical rotation operation required")
        actors = record(self.environment.value["actors"])
        if slot not in actors or record(actors[slot])["account_id"] != request["account_id"]:
            raise ValueError("Exact issued rotation account required")
        value = credential(json.dumps(request["credential"]))
        previous, revision = (
            text(request, "previous_revision"),
            text(request, "credential_revision"),
        )
        if (
            not previous.isdigit()
            or str(int(previous) + 1) != revision
            or value["revision"] != revision
        ):
            raise ValueError("Exact next credential revision required")
        payload_digest = hashlib.sha256(_canonical(request)).hexdigest()
        receipt_path = self.receipts / (operation_id + ".json")
        prior = load_private(receipt_path) if receipt_path.exists() else None
        if prior and prior.get("payload_digest") != payload_digest:
            raise ValueError("Credential rotation identity conflict")
        latest_revision = 1
        other_pending = False
        for file in self.receipts.glob("*.json"):
            other = load_private(file)
            if other.get("account_id") != request["account_id"]:
                continue
            if other.get("state") == "confirmed":
                latest_revision = max(latest_revision, int(text(other, "credential_revision")))
            elif file != receipt_path:
                other_pending = True
        if (not prior or prior.get("state") != "confirmed") and (
            other_pending or int(previous) != latest_revision
        ):
            raise ValueError("Credential revision changed or another rotation pending")
        state = load_private(self.state_path)
        users = record(state["users"])
        matches = [
            record(raw)
            for raw in users.values()
            if record(raw).get("account_id") == request["account_id"]
        ]
        if len(matches) != 1 or matches[0].get("totp_secret") != value["totp_secret"]:
            raise ValueError("Credential seed/account binding changed")
        actor = matches[0]
        expected_actor = record(actors[slot])
        if (
            actor.get("id") != expected_actor["provider_subject"]
            or actor.get("username") != expected_actor["username"]
            or actor.get("roles") != [expected_actor["role"]]
        ):
            raise ValueError("Persisted provider actor binding changed")
        if prior and prior.get("state") == "confirmed":
            # Repair a confirmation/state-file crash gap only for the newest
            # confirmed revision. Historical retries must never rewind secrets.
            if int(revision) == latest_revision and not other_pending:
                actor["password"] = value["password"]
                private_write(self.state_path, _canonical(state))
            return record(prior["result"])
        intent: Record = {
            key: request[key]
            for key in ("operation_id", "environment_id", "account_id", "credential_revision")
        }
        intent.update(payload_digest=payload_digest, state="pending")
        private_write(receipt_path, _canonical(intent))
        provider = self._provider(state)
        verified: Record | None = None
        if prior:
            try:
                verified = provider.verify_password(
                    text(request, "account_id"), text(value, "password"), text(value, "totp_secret")
                )
            except ReviewProviderError as error:
                if str(error) in {
                    "provider_actor_outside_lease",
                    "provider_rotation_parameters_invalid",
                    "provider_subject_mismatch",
                    "provider_actor_binding_changed",
                    "provider_realm_binding_changed",
                    "provider_client_binding_changed",
                }:
                    raise
                # Same operation, same payload, same intended password revision.
                # Keycloak has no operation ID, so repeat only this state-idempotent
                # declared update; never generate a new secret after uncertainty.
        if verified is None:
            verified = provider.rotate(
                text(request, "account_id"), text(value, "password"), text(value, "totp_secret")
            )
        if (
            verified.get("account_id") != request["account_id"]
            or verified.get("provider_subject") != actor["id"]
            or verified.get("verified") is not True
        ):
            raise ValueError("Credential proof identity/outcome mismatch")
        result = {
            "operation_id": operation_id,
            "account_id": request["account_id"],
            "credential_revision": revision,
            "verified": True,
            "rotated_fields": ["password"],
        }
        intent.update(state="confirmed", result=result)
        private_write(receipt_path, _canonical(intent))
        actor["password"] = value["password"]
        private_write(self.state_path, _canonical(state))
        return result


class ReviewEnvironment:
    def __init__(self, config_path: Path) -> None:
        require_profile()
        config = load_private(config_path)
        if (
            set(config) - {"credential_receipts"}
            != {
                "environment_manifest",
                "admin_config",
                "provider_state",
                "provider_admin_password_file",
                "ca_file",
                "registry_path",
                "socket",
                "contexts_targets",
                "maintenance_profile",
            }
            or config["maintenance_profile"] != "continuation-001"
        ):
            raise ValueError("Exact continuation operator configuration required")
        self.config, self.config_path = config, config_path
        self.environment = Environment.parse(
            load_private(Path(text(config, "environment_manifest")))
        )
        admin = load_private(Path(text(config, "admin_config")))
        if (
            set(admin) != {"dsn", "environment_id", "expected_database", "expected_journal_id"}
            or admin["environment_id"] != self.environment.id
        ):
            raise ValueError("Exact owned review admin binding required")
        self.admin = ReviewRunAdmin(**cast(dict[str, str], admin))
        self.provider_state = Path(text(config, "provider_state"))
        self.admin_password = Path(text(config, "provider_admin_password_file"))
        self.ca_file = Path(text(config, "ca_file"))
        self.registry_path = Path(text(config, "registry_path"))
        private_directory(self.registry_path.parent)
        if self.registry_path.exists() or self.registry_path.is_symlink():
            load_private(self.registry_path)
        self.socket = Path(text(config, "socket"))
        if (
            record(self.environment.value["lifecycle"])["socket"] != str(self.socket)
            or record(self.environment.value["lifecycle"])["peer_uid"] != os.geteuid()
        ):
            raise ValueError("Manifest/operator socket custody mismatch")
        targets = config["contexts_targets"]
        if not isinstance(targets, list):
            raise ValueError("Exact context targets required")
        self.publisher = ContextPublisher(
            self.environment, [record(x) for x in cast(list[object], targets)]
        )
        from .trust_refresh import refresh

        self.steward = TrustSteward(refresh, config_path.parent / "trust-steward.json")
        provider = provider_admin(
            load_private(self.provider_state),
            private_read(self.admin_password).decode().strip(),
            self.ca_file,
        )
        self.provider_issuers = (
            [item.issuer for item in provider.providers.values()]
            if isinstance(provider, ProviderGroup)
            else [provider.issuer]
        )
        rotation = CredentialRotation(
            self.environment,
            self.provider_state,
            self.admin_password,
            self.ca_file,
            Path(text(config, "credential_receipts"))
            if "credential_receipts" in config
            else config_path.parent / "credential-operations",
        )
        self.operator = ReviewOperator(
            self.environment,
            self.admin,
            provider,
            self.registry_path,
            self.publisher,
            self.ready,
            rotate=rotation,
        )

    def ready(self) -> bool:
        if not self.steward.current():
            return False
        try:
            self.publisher.check_targets()
            contexts = load_private(self.registry_path) if self.registry_path.exists() else {}
            active = {
                origin: record(raw)
                for origin, raw in contexts.items()
                if record(raw).get("state") == "active"
            }
            for origin in [LEGACY_ORIGIN, *active]:
                with httpx.Client(
                    transport=PinnedAddressTransport(origin, "127.0.0.1", str(self.ca_file)),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    response = client.get(origin + "/v1/auth/session", timeout=3)
                    if response.status_code != 401:
                        return False
                    if origin in active:
                        response = client.get(origin + "/v1/review/context", timeout=3)
                        if response.status_code != 200:
                            return False
                        actual = record(response.json())
                        expected = active[origin]
                        if (
                            actual.get("enabled") is not True
                            or any(
                                actual.get(key) != expected[key]
                                for key in ("run_id", "slot_id", "account_id", "role")
                            )
                            or actual.get("run_state") != "active"
                        ):
                            return False
            with httpx.Client(
                transport=PinnedAddressTransport(BASE, "127.0.0.1", str(self.ca_file)),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                for issuer in self.provider_issuers:
                    response = client.get(issuer + "/.well-known/openid-configuration", timeout=3)
                    if (
                        response.status_code != 200
                        or record(response.json()).get("issuer") != issuer
                    ):
                        return False
            return True
        except (ValueError, OSError, httpx.HTTPError):
            return False

    def serve(self) -> None:
        server = OperatorServer(self.socket, self.operator)
        socket_inode = self.socket.lstat().st_ino
        stop = threading.Event()
        original_handlers: dict[int, object] = {}

        def terminate(_signal: int, _frame: object) -> None:
            stop.set()

        for number in (signal.SIGINT, signal.SIGTERM):
            original_handlers[number] = signal.signal(number, terminate)
        birth = subprocess.run(  # noqa: S603 - current process birth metadata only
            ["ps", "-p", str(os.getpid()), "-o", "lstart="],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
        private_write(
            self.config_path.parent / "operator-receipt.json",
            _canonical(
                {
                    "pid": os.getpid(),
                    "process_birth": birth,
                    "socket_inode": socket_inode,
                    "environment_id": self.environment.id,
                    "state": "running",
                }
            ),
        )
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        self.steward.start()
        serving.start()
        try:
            stop.wait()
        finally:
            server.shutdown()
            server.server_close()
            self.steward.close()
            serving.join(timeout=5)
            if self.socket.exists() and self.socket.lstat().st_ino == socket_inode:
                self.socket.unlink()
            for number, handler in original_handlers.items():
                signal.signal(number, cast(Callable[[int, object], None], handler))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    options = parser.parse_args()
    try:
        ReviewEnvironment(options.config).serve()
    except (ValueError, OSError, RuntimeError):
        raise SystemExit(
            "Review operator unavailable; inspect its owner-only configuration/state"
        ) from None


if __name__ == "__main__":
    main()
