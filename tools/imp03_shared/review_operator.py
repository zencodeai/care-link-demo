"""Owner-only operator socket for review namespace lifecycle and exact credentials.

The toolkit receives no admin DSN. This process configures demo namespaces only;
actor business actions remain protected gateway operations.
"""

import json
import os
import socketserver
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID

from tools.demo.lifecycle import peer_uid
from tools.demo.models import Environment, Record, record, text
from tools.demo.storage import private_directory, private_read, private_write


class RunAdmin(Protocol):
    def create(
        self, run_id: str, scenario: str, operation_id: str, scenario_version: str = "1"
    ) -> Record: ...
    def inspect(self, run_id: str) -> Record: ...
    def close(self, run_id: str, operation_id: str) -> Record: ...


class Provider(Protocol):
    def install_origins(self, origins: list[str]) -> Record: ...
    def rotate(self, account_id: str, newpassword: str, totp_secret: str) -> Record: ...


class ReviewOperator:
    def __init__(
        self,
        environment: Environment,
        admin: RunAdmin,
        provider: Provider,
        registry_path: Path,
        publish: Callable[[Record], None],
        ready: Callable[[], bool],
        rotate: Callable[[Record], Record] | None = None,
    ) -> None:
        self.environment, self.admin, self.provider = environment, admin, provider
        self.registry_path, self.publish, self.ready = registry_path, publish, ready
        self.lock = threading.RLock()
        self.rotate = rotate

    def _contexts(self, run: Record) -> None:
        state = (
            record(json.loads(private_read(self.registry_path)))
            if self.registry_path.exists() or self.registry_path.is_symlink()
            else {}
        )
        origins: list[str] = []
        run_id = text(run, "run_id")
        prefix = "r" + UUID(run_id).hex + "-"
        for slot, raw_actor in record(self.environment.value["actors"]).items():
            actor = record(raw_actor)
            origin = (
                "https://"
                + prefix
                + slot
                + "."
                + text(self.environment.value, "base_domain")
                + ":"
                + str(self.environment.value["port"])
            )
            origins.append(origin)
            context: Record = {
                "run_id": run_id,
                "slot_id": slot,
                "account_id": actor["account_id"],
                "provider_subject": actor["provider_subject"],
                "role": actor["role"],
                "state": run["state"],
            }
            previous = state.get(origin)
            if previous and any(
                record(previous).get(k) != v for k, v in context.items() if k != "state"
            ):
                raise ValueError("Existing review origin has a different binding")
            state[origin] = context
        # Each step is idempotent. A partial provider/publication failure leaves
        # the original durable run intent available for an exact resume.
        self.provider.install_origins(origins)
        self.publish(state)
        private_write(self.registry_path, json.dumps(state).encode())

    def call(self, path: str, request: Record) -> Record:
        if request.get("environment_id") != self.environment.id:
            raise ValueError("Exact owned environment required")
        with self.lock:
            if path == "/v1/credentials/rotate":
                if self.rotate is None:
                    raise ValueError("Credential rotation is not configured")
                return self.rotate(request)
            if path == "/v1/runs/doctor":
                if set(request) != {"environment_id"}:
                    raise ValueError("Exact doctor request required")
                return {
                    "environment_id": self.environment.id,
                    "core_protocol": "care.review.v1",
                    "ready": self.ready(),
                }
            if path in {"/v1/runs/create", "/v1/runs/inspect", "/v1/runs/close"}:
                if set(request) != {
                    "environment_id",
                    "run_id",
                    "scenario",
                    "scenario_version",
                    "operation_id",
                }:
                    raise ValueError("Exact run request required")
                run_id, operation_id = text(request, "run_id"), text(request, "operation_id")
                if str(UUID(run_id)) != run_id or str(UUID(operation_id)) != operation_id:
                    raise ValueError("Canonical run/operation required")
                if path.endswith("/create"):
                    result = self.admin.create(
                        run_id,
                        text(request, "scenario"),
                        operation_id,
                        text(request, "scenario_version"),
                    )
                elif path.endswith("/close"):
                    result = self.admin.close(run_id, operation_id)
                else:
                    return self.admin.inspect(run_id)
                self._contexts(result)
                return result
            raise ValueError("Unknown operator command")


class OperatorServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path: Path, operator: ReviewOperator) -> None:
        private_directory(path.parent)
        if path.exists() or path.is_symlink():
            raise ValueError("Existing operator socket must be inspected, not adopted")
        self.operator = operator
        self.owner_uid = os.geteuid()
        super().__init__(str(path), OperatorHandler)
        path.chmod(0o600)


class OperatorHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        # Requests can contain credentials; never use the default HTTP log.
        del format, args

    def do_POST(self) -> None:
        server = cast(OperatorServer, self.server)
        try:
            if peer_uid(self.connection) != server.owner_uid:
                raise ValueError("Operator peer mismatch")
            length = int(self.headers.get("content-length", "-1"))
            if not 0 <= length <= 65536 or self.headers.get("content-encoding"):
                raise ValueError("Bounded request required")
            if self.headers.get("content-type") != "application/json":
                raise ValueError("JSON required")
            payload = record(json.loads(self.rfile.read(length)))
            result = server.operator.call(self.path, payload)
            status = 200
        except Exception as error:
            result = {"state": "operator_unconfirmed", "error_class": type(error).__name__}
            status = 503
        raw = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
