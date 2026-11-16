"""Custody-checked Unix HTTP adapter. This client never receives a database DSN."""

import ctypes
import hashlib
import http.client
import json
import socket
import stat
import struct
import subprocess
import sys
from pathlib import Path
from typing import Protocol, cast

from .errors import DemoError
from .models import Environment, Record, record, text
from .storage import private_directory, private_read


class Lifecycle(Protocol):
    def call(self, environment: Environment, action: str, request: Record) -> Record: ...


def verify_ownership(environment: Environment) -> None:
    binding = record(environment.value["ownership"])
    if binding["kind"] == "receipt":
        try:
            raw = private_read(Path(text(binding, "receipt_path")))
            if hashlib.sha256(raw).hexdigest() != binding["receipt_sha256"]:
                raise DemoError("ownership_digest_changed")
            receipt = record(json.loads(raw))
            if (
                receipt.get("environment_id") != environment.id
                or receipt.get("resource_id") != binding["resource_id"]
            ):
                raise DemoError("ownership_binding_changed")
        except (ValueError, UnicodeError) as error:
            raise DemoError("ownership_receipt_invalid") from error
        return
    try:
        result = subprocess.run(  # noqa: S603 - inspected exact resource ID, no shell
            ["docker", "inspect", text(binding, "resource_id")],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode:
            raise DemoError("owned_resource_unavailable")
        raw_rows: object = json.loads(result.stdout)
        if not isinstance(raw_rows, list):
            raise DemoError("ownership_binding_changed")
        rows = cast(list[object], raw_rows)
        if len(rows) != 1:
            raise DemoError("ownership_binding_changed")
        observed = record(rows[0])
        labels = record(record(observed.get("Config", {})).get("Labels", {}))
        if observed.get("Id") != binding["resource_id"] or any(
            labels.get(k) != v for k, v in record(binding["labels"]).items()
        ):
            raise DemoError("ownership_binding_changed")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise DemoError("owned_resource_unavailable") from error


def peer_uid(connection: socket.socket) -> int:
    if sys.platform == "linux":
        return cast(
            int,
            struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[
                1
            ],
        )
    if sys.platform == "darwin":
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        if libc.getpeereid(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            raise DemoError("operator_peer_unverified")
        return uid.value
    raise DemoError("operator_peer_verification_unsupported")


class UnixLifecycle:
    def call(self, environment: Environment, action: str, request: Record) -> Record:
        if action not in {"create", "inspect", "close", "doctor", "rotate", "inspect-rotation"}:
            raise DemoError("unsupported_lifecycle_action")
        binding = record(environment.value["lifecycle"])
        path = Path(text(binding, "socket"))
        private_directory(path.parent)
        try:
            item = path.lstat()
            expected_uid = cast(int, binding["peer_uid"])
            if (
                not stat.S_ISSOCK(item.st_mode)
                or item.st_uid != expected_uid
                or stat.S_IMODE(item.st_mode) & 0o007
            ):
                raise DemoError("operator_socket_custody")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(75 if action in {"rotate", "inspect-rotation"} else 10)
                connection.connect(str(path))
                if peer_uid(connection) != expected_uid:
                    raise DemoError("operator_peer_changed")
                route = (
                    "/v1/credentials/" if action in {"rotate", "inspect-rotation"} else "/v1/runs/"
                )
                raw = json.dumps(request, separators=(",", ":")).encode()
                headers = (
                    f"POST {route}{action} HTTP/1.1\r\nHost: demo-operator.local\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n"
                ).encode()
                connection.sendall(headers + raw)
                response = http.client.HTTPResponse(connection)
                response.begin()
                payload = response.read(65537)
                if (
                    response.status != 200
                    or len(payload) > 65536
                    or not response.getheader("content-type", "").startswith("application/json")
                ):
                    raise DemoError("operator_request_unconfirmed")
                return record(json.loads(payload))
        except (OSError, ValueError, http.client.HTTPException) as error:
            raise DemoError("operator_unavailable") from error
