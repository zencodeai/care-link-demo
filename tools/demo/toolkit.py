"""Durable operator use cases. Runtime and provider effects go through adapters."""

import hashlib
import json
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .errors import DemoError
from .lifecycle import Lifecycle, UnixLifecycle, verify_ownership
from .models import CORE_PROTOCOL, Environment, Record, identifier, record, text, uuid
from .secrets import KeychainSecrets, SecretStore, credential, totp
from .storage import Registry


def stamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DemoToolkit:
    def __init__(
        self,
        registry: Registry | None = None,
        *,
        secrets_store: SecretStore | None = None,
        lifecycle: Lifecycle | None = None,
        ownership: Callable[[Environment], None] = verify_ownership,
    ) -> None:
        self.registry = registry or Registry()
        self.secrets = secrets_store or KeychainSecrets()
        self.lifecycle = lifecycle or UnixLifecycle()
        self.ownership = ownership

    def environment(self, environment_id: str) -> Environment:
        with self.registry.lock():
            value = record(self.registry.read()["environments"]).get(identifier(environment_id))
            if value is None:
                raise DemoError("environment_not_registered")
            return Environment.parse(value)

    def register(self, raw: object) -> Record:
        environment = Environment.parse(raw)
        self.ownership(environment)
        with self.registry.lock():
            state = self.registry.read()
            environments = record(state["environments"])
            previous = environments.get(environment.id)
            if previous is not None and previous != environment.value:
                raise DemoError("environment_binding_changed")
            environments[environment.id] = environment.value
            self.registry.write(state)
        return {"environment_id": environment.id, "registered": True, "provisioned": False}

    def doctor(self, environment_id: str) -> Record:
        environment = self.environment(environment_id)
        checks: list[Record] = []
        try:
            self.ownership(environment)
            checks.append({"name": "ownership", "status": "ready"})
        except DemoError as error:
            checks.append({"name": "ownership", "status": "unavailable", "code": error.code})
        for slot, raw in record(environment.value["actors"]).items():
            try:
                credential(self.secrets.get(text(record(raw), "secret_ref")))
                checks.append({"name": "credential_" + slot, "status": "ready"})
            except DemoError as error:
                checks.append(
                    {"name": "credential_" + slot, "status": "unavailable", "code": error.code}
                )
        try:
            result = self.lifecycle.call(environment, "doctor", {"environment_id": environment.id})
            if (
                result.get("environment_id") != environment.id
                or result.get("core_protocol") != CORE_PROTOCOL
                or result.get("ready") is not True
            ):
                raise DemoError("runtime_not_ready_or_incompatible")
            checks.append({"name": "runtime_readiness", "status": "ready"})
        except DemoError as error:
            checks.append(
                {"name": "runtime_readiness", "status": "unavailable", "code": error.code}
            )
        return {
            "environment_id": environment.id,
            "ready": all(x["status"] == "ready" for x in checks),
            "checks": checks,
        }

    def _run(self, run_id: str) -> Record:
        value = record(self.registry.read()["runs"]).get(uuid(run_id))
        if value is None:
            raise DemoError("run_not_registered")
        return record(value)

    def inspect(self, run_id: str) -> Record:
        with self.registry.lock():
            return json.loads(json.dumps(self._run(run_id)))

    def list_runs(self, environment_id: str) -> Record:
        environment = self.environment(environment_id)
        with self.registry.lock():
            runs = [
                {
                    key: value
                    for key, value in record(raw).items()
                    if key in {"run_id", "state", "scenario", "created_at", "updated_at"}
                }
                for raw in record(self.registry.read()["runs"]).values()
                if record(raw).get("environment_id") == environment.id
            ]
        runs.sort(key=lambda run: text(run, "created_at"), reverse=True)
        return {
            "environment_id": environment.id,
            "current_run_id": next(
                (run["run_id"] for run in runs if run["state"] != "closed"), None
            ),
            "runs": runs,
        }

    @staticmethod
    def _receipt(expected: Record, observed: Record) -> Record:
        for key in ("environment_id", "run_id", "scenario", "scenario_version"):
            if observed.get(key) != expected[key]:
                raise DemoError("runtime_run_binding_changed")
        revision = observed.get("revision")
        if (
            observed.get("state") not in {"active", "closing", "closed"}
            or not isinstance(revision, str)
            or not revision.isdigit()
        ):
            raise DemoError("runtime_run_receipt_invalid")
        return {
            key: observed[key]
            for key in (
                "environment_id",
                "run_id",
                "scenario",
                "scenario_version",
                "state",
                "revision",
            )
        }

    def _request(
        self, environment: Environment, run: Record, action: str, operation_id: str
    ) -> Record:
        self.ownership(environment)
        request = {
            key: run[key] for key in ("environment_id", "run_id", "scenario", "scenario_version")
        }
        request["operation_id"] = operation_id
        result = self._receipt(run, self.lifecycle.call(environment, action, request))
        if action == "create" and result["state"] != "active":
            raise DemoError("run_creation_unconfirmed")
        if action == "close" and result["state"] != "closed":
            raise DemoError("run_close_pending")
        return result

    def create(
        self, environment_id: str, *, scenario: str = "manual-service", run_id: str | None = None
    ) -> Record:
        environment = self.environment(environment_id)
        # A run must be operable with the durable issued actor material; losing
        # the secret store must not silently start an unusable review namespace.
        for actor in record(environment.value["actors"]).values():
            credential(self.secrets.get(text(record(actor), "secret_ref")))
        if scenario != "manual-service":
            raise DemoError("scenario_unsupported")
        scenario_path = (
            Path(__file__).resolve().parents[2] / "config/demo/scenarios/manual-service.json"
        )
        definition = record(json.loads(scenario_path.read_text()))
        if (
            definition.get("scenario_version") != environment.value["scenario_version"]
            or definition.get("core_protocol") != CORE_PROTOCOL
        ):
            raise DemoError("scenario_incompatible")
        selected = uuid(run_id) if run_id else str(uuid4())
        lock = "env-" + hashlib.sha256(environment.id.encode()).hexdigest()
        with self.registry.lock(lock):
            with self.registry.lock():
                state = self.registry.read()
                runs = record(state["runs"])
                existing = runs.get(selected)
                if existing is not None:
                    previous = record(existing)
                    if (
                        previous.get("environment_id") != environment.id
                        or previous.get("scenario") != scenario
                    ):
                        raise DemoError("run_binding_changed")
                else:
                    if any(
                        record(x).get("environment_id") == environment.id
                        and record(x).get("state") != "closed"
                        for x in runs.values()
                    ):
                        raise DemoError("environment_has_active_or_partial_run")
                    operation_id = str(uuid4())
                    runs[selected] = {
                        "run_id": selected,
                        "environment_id": environment.id,
                        "scenario": scenario,
                        "scenario_version": definition["scenario_version"],
                        "state": "creating",
                        "revision": "0",
                        "origins": environment.origins(selected),
                        "created_at": stamp(),
                        "operation_id": operation_id,
                    }
                    record(state["operations"])[operation_id] = {
                        "operation_id": operation_id,
                        "environment_id": environment.id,
                        "run_id": selected,
                        "kind": "create",
                        "state": "pending",
                    }
                    self.registry.write(state)
            return self._resume_locked(environment, selected)

    def _resume_locked(self, environment: Environment, run_id: str) -> Record:
        with self.registry.lock():
            run = self._run(run_id)
            operation_id = text(run, "operation_id")
            operation = record(record(self.registry.read()["operations"])[operation_id])
            action = "inspect" if operation["state"] == "confirmed" else text(operation, "kind")
        try:
            result = self._request(environment, run, action, operation_id)
        except DemoError as error:
            with self.registry.lock():
                state = self.registry.read()
                record(record(state["operations"])[operation_id])["last_error"] = error.code
                self.registry.write(state)
            raise
        with self.registry.lock():
            state = self.registry.read()
            current = record(record(state["runs"])[run_id])
            if current.get("operation_id") != operation_id:
                raise DemoError("run_operation_changed")
            current.update(result)
            current["updated_at"] = stamp()
            active_operation = record(record(state["operations"])[operation_id])
            active_operation["state"] = "confirmed"
            active_operation.pop("last_error", None)
            self.registry.write(state)
        return self.inspect(run_id)

    def resume(self, run_id: str) -> Record:
        run = self.inspect(run_id)
        environment = self.environment(text(run, "environment_id"))
        with self.registry.lock("env-" + hashlib.sha256(environment.id.encode()).hexdigest()):
            return self._resume_locked(environment, run_id)

    def close(self, run_id: str) -> Record:
        run = self.inspect(run_id)
        environment = self.environment(text(run, "environment_id"))
        with self.registry.lock("env-" + hashlib.sha256(environment.id.encode()).hexdigest()):
            with self.registry.lock():
                state = self.registry.read()
                current = record(record(state["runs"])[run_id])
                if current["state"] == "creating":
                    raise DemoError("resume_partial_run_before_close")
                if current["state"] not in {"closing", "closed"}:
                    operation_id = str(uuid4())
                    current.update(state="closing", operation_id=operation_id)
                    record(state["operations"])[operation_id] = {
                        "operation_id": operation_id,
                        "environment_id": environment.id,
                        "run_id": run_id,
                        "kind": "close",
                        "state": "pending",
                    }
                    self.registry.write(state)
            return self._resume_locked(environment, run_id)

    def actors(self, run_id: str) -> Record:
        run = self.inspect(run_id)
        environment = self.environment(text(run, "environment_id"))
        actors = record(environment.value["actors"])
        return {
            "run_id": run_id,
            "state": run["state"],
            "actors": {
                slot: {
                    "account_id": record(actor)["account_id"],
                    "role": record(actor)["role"],
                    "username": record(actor)["username"],
                    "origin": record(run["origins"])[slot],
                }
                for slot, actor in actors.items()
            },
        }

    def actor_url(self, run_id: str, slot: str) -> str:
        run = self.inspect(run_id)
        if run["state"] != "active":
            raise DemoError("run_not_active")
        origins = record(run["origins"])
        if slot not in origins:
            raise DemoError("unknown_actor_slot")
        return text(origins, slot) + "/"

    def _actor(self, environment_id: str, slot: str) -> tuple[Environment, Record]:
        environment = self.environment(environment_id)
        actors = record(environment.value["actors"])
        if slot not in actors:
            raise DemoError("unknown_actor_slot")
        return environment, record(actors[slot])

    def import_credential(self, environment_id: str, slot: str, raw: str) -> Record:
        _environment, actor = self._actor(environment_id, slot)
        value = credential(raw)
        reference = text(actor, "secret_ref")
        # Import is deliberately explicit and is not a credential reset at provider.
        with self.registry.lock("env-" + hashlib.sha256(environment_id.encode()).hexdigest()):
            with self.registry.lock():
                pending = record(self.registry.read()["credential_operations"])
                if any(
                    record(item).get("account_id") == actor["account_id"]
                    and record(item).get("state") != "confirmed"
                    for item in pending.values()
                ):
                    raise DemoError("credential_rotation_pending_resume_original_operation")
            self.secrets.put(reference, json.dumps(value))
        return {
            "environment_id": environment_id,
            "slot": slot,
            "revision": value["revision"],
            "imported": True,
        }

    def reveal_password(self, environment_id: str, slot: str) -> str:
        _environment, actor = self._actor(environment_id, slot)
        return text(credential(self.secrets.get(text(actor, "secret_ref"))), "password")

    def otp(
        self,
        environment_id: str,
        slot: str,
        *,
        now: float | None = None,
        fresh: bool = False,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Record:
        _environment, actor = self._actor(environment_id, slot)
        value = credential(self.secrets.get(text(actor, "secret_ref")))
        instant = clock() if now is None else now
        if fresh:
            previous_window = int(instant) // 30
            sleep(30 - instant % 30 + 0.2)
            instant = clock()
            if int(instant) // 30 <= previous_window:
                raise DemoError("fresh_otp_clock_did_not_advance")
        code, expires_in = totp(text(value, "totp_secret"), now=instant)
        return {"code": code, "expires_in_seconds": expires_in, "slot": slot, "fresh_window": fresh}

    def rotate(self, environment_id: str, slot: str, *, operation_id: str | None = None) -> Record:
        environment, actor = self._actor(environment_id, slot)
        selected = uuid(operation_id) if operation_id else str(uuid4())
        with self.registry.lock("env-" + hashlib.sha256(environment.id.encode()).hexdigest()):
            with self.registry.lock():
                state = self.registry.read()
                operations = record(state["credential_operations"])
                raw_operation = operations.get(selected)
                if raw_operation is None:
                    if any(
                        record(x).get("account_id") == actor["account_id"]
                        and record(x).get("state") != "confirmed"
                        for x in operations.values()
                    ):
                        raise DemoError("credential_rotation_pending_resume_original_operation")
                    old = credential(self.secrets.get(text(actor, "secret_ref")))
                    pending_ref = "rotation-" + uuid4().hex
                    fresh = {
                        "password": secrets.token_urlsafe(32),
                        "totp_secret": old["totp_secret"],
                        "revision": str(int(text(old, "revision")) + 1),
                    }
                    self.secrets.put(pending_ref, json.dumps(fresh))
                    raw_operation = {
                        "operation_id": selected,
                        "environment_id": environment.id,
                        "slot": slot,
                        "account_id": actor["account_id"],
                        "state": "pending",
                        "pending_secret_ref": pending_ref,
                        "previous_revision": old["revision"],
                        "revision": fresh["revision"],
                    }
                    operations[selected] = raw_operation
                    self.registry.write(state)
                operation = record(raw_operation)
                if (
                    operation.get("environment_id") != environment.id
                    or operation.get("slot") != slot
                    or operation.get("account_id") != actor["account_id"]
                ):
                    raise DemoError("rotation_binding_changed")
                if operation["state"] == "confirmed":
                    return {
                        "operation_id": selected,
                        "slot": slot,
                        "revision": operation["revision"],
                        "verified": True,
                        "rotated_fields": ["password"],
                    }
            self.ownership(environment)
            fresh = credential(self.secrets.get(text(operation, "pending_secret_ref")))
            observed = self.lifecycle.call(
                environment,
                "rotate",
                {
                    "environment_id": environment.id,
                    "slot": slot,
                    "account_id": actor["account_id"],
                    "operation_id": selected,
                    "previous_revision": operation["previous_revision"],
                    "credential_revision": operation["revision"],
                    "credential": fresh,
                },
            )
            if (
                observed.get("operation_id") != selected
                or observed.get("account_id") != actor["account_id"]
                or observed.get("credential_revision") != operation["revision"]
                or observed.get("verified") is not True
            ):
                raise DemoError("credential_rotation_unverified")
            self.secrets.put(text(actor, "secret_ref"), json.dumps(fresh))
            with self.registry.lock():
                state = self.registry.read()
                record(record(state["credential_operations"])[selected])["state"] = "confirmed"
                self.registry.write(state)
            return {
                "operation_id": selected,
                "slot": slot,
                "revision": operation["revision"],
                "verified": True,
                "rotated_fields": ["password"],
            }
