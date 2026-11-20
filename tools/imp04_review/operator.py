"""Explicit private operator boundary; never launches a server or browser."""

import json
import os
import socketserver
import stat
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import cast

import httpx
from care_link_workload_trust import peer_uid

from .lifecycle import PlansReviewLifecycle
from .storage import private_directory, read_json
from .types import JsonRecord


def dispatch(manager: PlansReviewLifecycle, command: JsonRecord) -> JsonRecord:
    base = {"target_id", "environment_id", "command"}
    extra: set[str] = (
        {"lifetime_seconds", "run_id"} if command.get("command") == "start-fresh" else set()
    )
    if set(command) != base | extra:
        raise ValueError("Exact operator command fields required")
    if (
        command["target_id"] != manager.target_id
        or command["environment_id"] != manager.environment_id
    ):
        raise ValueError("Exact configured synthetic target required")
    if command["command"] == "start-fresh":
        return manager.start_fresh(
            lifetime_seconds=command["lifetime_seconds"], run_id=command["run_id"]
        )
    if command["command"] == "inspect":
        return manager.inspect()
    if command["command"] == "close":
        return manager.close()
    raise ValueError("Unknown review lifecycle command")


class OperatorServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path: Path, manager: PlansReviewLifecycle) -> None:
        if not path.is_absolute():
            raise ValueError("Absolute owner-private operator socket required")
        private_directory(path.parent)
        if path.exists() or path.is_symlink():
            raise ValueError("Existing operator socket cannot be adopted")
        self.manager, self.owner_uid = manager, os.geteuid()
        super().__init__(str(path), OperatorHandler)
        path.chmod(0o600)


class OperatorHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def do_POST(self) -> None:
        server = cast(OperatorServer, self.server)
        try:
            if peer_uid(self.connection) != server.owner_uid:
                raise ValueError("Operator peer mismatch")
            if self.path != "/internal/plans-review/operator":
                raise ValueError("Exact operator path required")
            length = int(self.headers.get("content-length", "-1"))
            if not 0 < length <= 16384 or self.headers.get("content-encoding"):
                raise ValueError("Bounded unencoded command required")
            if self.headers.get("content-type") != "application/json":
                raise ValueError("JSON command required")
            value: object = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError("Command object required")
            result = dispatch(server.manager, cast(JsonRecord, value))
            status = 200
        except Exception:
            result, status = {"state": "operator_unconfirmed"}, 503
        raw = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def request(
    config_path: Path,
    command: str,
    *,
    lifetime_seconds: int | None = None,
    run_id: str | None = None,
) -> JsonRecord:
    config = read_json(config_path)
    if (
        set(config) != {"environment", "environment_id", "target_id", "operator_socket"}
        or config["environment"] != "synthetic-review"
    ):
        raise ValueError("Explicit synthetic-only operator configuration required")
    socket = Path(config["operator_socket"])
    if not socket.is_absolute():
        raise ValueError("Absolute private operator socket required")
    parent_info, socket_info = socket.parent.lstat(), socket.lstat()
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or parent_info.st_uid != os.getuid()
        or parent_info.st_mode & 0o077
        or socket_info.st_uid != os.getuid()
        or not stat.S_ISSOCK(socket_info.st_mode)
        or socket_info.st_mode & 0o077
    ):
        raise ValueError("Owner-private operator socket custody required")
    body = {key: config[key] for key in ("environment_id", "target_id")}
    body["command"] = command
    if command == "start-fresh":
        body.update({"lifetime_seconds": lifetime_seconds, "run_id": run_id})
    with httpx.Client(
        transport=httpx.HTTPTransport(uds=str(socket)), timeout=60, trust_env=False
    ) as client:
        response = client.post("http://operator/internal/plans-review/operator", json=body)
        response.raise_for_status()
        result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Invalid operator response")
    checked = cast(JsonRecord, result)
    if checked.get("state") != "absent" and any(
        checked.get(key) != config[key] for key in ("target_id", "environment_id")
    ):
        raise ValueError("Operator response belongs to a different target")
    return checked
