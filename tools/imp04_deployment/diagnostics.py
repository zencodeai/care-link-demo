"""Default-off, owner-private timing observations for the new Core's own RPCs."""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx

from .config import CONFIG, PREFIX, load, record


def install(root: Path, role: str, clients: list[httpx.Client]) -> None:
    if str(root) != CONFIG or role != "core":
        return
    marker = root / role / "qualification-trace.json"
    if not marker.exists():
        return
    settings = load(marker)
    initial_marker = marker.lstat()
    if set(settings) != {"version", "target", "role", "expires_at"} or (
        settings["version"],
        settings["target"],
        settings["role"],
    ) != ("imp04.trace.v1", PREFIX, role):
        raise ValueError("Exact temporary new-Core trace marker required")
    expires = datetime.fromisoformat(str(settings["expires_at"]).replace("Z", "+00:00"))
    if expires.tzinfo is None or not datetime.now(UTC) < expires <= datetime.now(UTC) + timedelta(
        minutes=20
    ):
        raise ValueError("Bounded temporary observation lease required")
    destination = marker.with_suffix(".jsonl")
    mutex = threading.Lock()

    def before(request: httpx.Request) -> None:
        request.extensions["imp04_trace_started"] = time.monotonic()

    def after(response: httpx.Response) -> None:
        if datetime.now(UTC) >= expires:
            return
        try:
            current_marker = marker.lstat()
            if (
                current_marker.st_ino != initial_marker.st_ino
                or current_marker.st_dev != initial_marker.st_dev
                or current_marker.st_mtime_ns != initial_marker.st_mtime_ns
                or not stat.S_ISREG(current_marker.st_mode)
                or current_marker.st_uid != os.geteuid()
                or current_marker.st_mode & 0o077
            ):
                return
            request = response.request
            if request.url.host not in {
                "identity.imp04.mesh",
                "data.imp04.mesh",
                "pdp.imp04.mesh",
                "journal.imp04.mesh",
            } or not re.fullmatch(r"/internal/v1/[a-z_/-]+", request.url.path):
                return
            response.read()
            row: dict[str, object] = {
                "observed_at": datetime.now(UTC).isoformat(),
                "host": request.url.host,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": round(
                    1000 * (time.monotonic() - float(request.extensions["imp04_trace_started"]))
                ),
            }
            body = record(json.loads(request.content))
            operation: object = request.headers.get("idempotency-key")
            if body:
                planning = body.get("planning")
                if isinstance(planning, dict):
                    operation = cast(dict[str, object], planning).get("operation_id", operation)
                operation = body.get("operation_id", operation)
                delegation = body.get("delegation")
                deadline = body.get("request_deadline")
                if isinstance(delegation, dict):
                    deadline = cast(dict[str, object], delegation).get("expires_at", deadline)
                if isinstance(deadline, str):
                    instant = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                    row["deadline_remaining_ms"] = round(
                        (instant - datetime.now(UTC)).total_seconds() * 1000
                    )
            if isinstance(operation, str) and str(UUID(operation)) == operation:
                row["operation_id"] = operation
            if response.status_code >= 400 and len(response.content) <= 65536:
                try:
                    error = record(response.json())
                except ValueError:
                    error = {}
                    row["non_json_error"] = True
                    # Fixed classifications only; never emit the proxy body.
                    for phrase, category in (
                        (b"connection refused", "connection_refused"),
                        (b"certificate verify failed", "certificate_validation"),
                        (b"upstream connect error", "upstream_connect"),
                        (b"rbac: access denied", "proxy_rbac_denied"),
                    ):
                        if phrase in response.content.lower():
                            row["proxy_error_category"] = category
                            break
                if error:
                    for key, permitted in (
                        (
                            "code",
                            {
                                "AUTHORITY_UNAVAILABLE",
                                "DEPENDENCY_UNAVAILABLE",
                                "COMMIT_UNKNOWN",
                                "DEADLINE_EXCEEDED",
                                "REVISION_CONFLICT",
                                "INVALID_REQUEST",
                                "NOT_FOUND",
                                "NOT_AUTHORIZED",
                                "UNAUTHENTICATED",
                                "POLICY_UNAVAILABLE",
                                "AUDIT_UNAVAILABLE",
                            },
                        ),
                        (
                            "message_key",
                            {
                                "manual.deadline",
                                "manual.deadline_exceeded",
                                "manual.commit_unknown",
                                "manual.authority_unavailable",
                                "manual.db_unavailable",
                                "manual.journal_barrier",
                                "manual.policy_unavailable",
                                "manual.policy_denied",
                                "manual.stale_authority",
                                "manual.identity_evidence_expired",
                                "manual.identity_unavailable",
                                "manual.gateway_denied",
                            },
                        ),
                        ("state", {"dependency_unavailable", "denied"}),
                    ):
                        value = error.get(key)
                        if isinstance(value, str) and value in permitted:
                            row[key] = value
            encoded = (json.dumps(row, separators=(",", ":")) + "\n").encode()
            with mutex:
                fd = os.open(
                    destination, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
                )
                try:
                    metadata = os.fstat(fd)
                    if (
                        stat.S_ISREG(metadata.st_mode)
                        and metadata.st_uid == os.geteuid()
                        and not metadata.st_mode & 0o077
                        and metadata.st_size + len(encoded) <= 5 * 1024 * 1024
                    ):
                        os.write(fd, encoded)
                finally:
                    os.close(fd)
        except (OSError, ValueError, TypeError, KeyError, httpx.HTTPError):
            # Observations never grant authority or change the RPC result.
            return

    for client in clients:
        client.event_hooks["request"].append(before)
        client.event_hooks["response"].append(after)
