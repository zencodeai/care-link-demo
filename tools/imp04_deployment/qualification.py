"""Optional one-shot timing barrier for the isolated live qualification target.

The adapter changes timing only. It never changes time, identity, policy inputs,
rights, data, or the engine's final disclosure checks. Ordinary serving does not
construct it. Control files remain owner-only and are never browser endpoints.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

from care_link_domain import ManualError

from tools.imp03_runtime.config import Record

DIRECTORY = Path("/run/care-link-imp03-002/configuration/data/qualification")
_FIELDS = {"version", "target", "phase", "action", "actor_id", "nonce", "expires_at"}


def _instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Exact timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("UTC-aware timestamp required")
    return result


def _read(path: Path) -> Record:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("Qualification control requires owner-only regular file")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Qualification object required")
    return cast(Record, value)


def _write(path: Path, value: Record) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())


class TimingBarrier:
    def __init__(self, directory: Path) -> None:
        if directory != DIRECTORY or os.environ.get("CARE_LINK_IMP04_QUALIFICATION") != "plans-002":
            raise ValueError("Explicit isolated target qualification activation required")
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Private qualification directory required")
        self.directory = directory

    def enter(self, phase: str, action: str, actor_id: str, operation_id: str) -> None:
        marker = self.directory / "armed.json"
        if not marker.exists():
            return
        try:
            value = _read(marker)
            if set(value) != _FIELDS or value["version"] != "imp04.qualification.v1":
                raise ValueError("Exact barrier shape required")
            if (
                value["target"] != "care-link-imp04-002"
                or value["phase"] not in {"before_policy", "before_final_output"}
                or value["action"] not in {"plan_read", "consent_grant"}
            ):
                raise ValueError("Wrong qualification target/action/phase")
            for field in ("actor_id", "nonce"):
                if str(UUID(str(value[field]))) != value[field]:
                    raise ValueError("Canonical barrier identity required")
            now, expires = datetime.now(UTC), _instant(value["expires_at"])
            if not now < expires <= now + timedelta(seconds=10):
                raise ValueError("Barrier expired or exceeds bounded lease")
            if (value["phase"], value["action"], value["actor_id"]) != (phase, action, actor_id):
                return
            claimed = self.directory / ("claimed-" + str(value["nonce"]) + ".json")
            # Atomic rename consumes this one marker; another request cannot arm
            # itself or replace its action/identity after the claim.
            try:
                os.rename(marker, claimed)
            except FileNotFoundError:
                return
            fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            receipt = {
                "target": value["target"],
                "phase": phase,
                "action": action,
                "actor_id": actor_id,
                "nonce": value["nonce"],
                "operation_id": operation_id,
                "marker_sha256": fingerprint,
                "entered_at": datetime.now(UTC).isoformat(),
            }
            _write(self.directory / ("ready-" + str(value["nonce"]) + ".json"), receipt)
            release = self.directory / ("release-" + str(value["nonce"]) + ".json")
            deadline = min(
                time.monotonic() + 0.8, time.monotonic() + (expires - now).total_seconds()
            )
            while not release.exists():
                if time.monotonic() >= deadline:
                    raise ManualError("manual.qualification_barrier_timeout", 503)
                time.sleep(0.005)
            if _read(release) != {"nonce": value["nonce"]}:
                raise ValueError("Wrong barrier release identity")
            _write(
                self.directory / ("finished-" + str(value["nonce"]) + ".json"),
                {**receipt, "released_at": datetime.now(UTC).isoformat()},
            )
        except (ValueError, OSError, TypeError, KeyError) as error:
            raise ManualError("manual.qualification_control_invalid", 503) from error
