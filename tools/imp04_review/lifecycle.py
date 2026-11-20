"""Serialized start-fresh/inspect/close with fail-closed readiness and retries."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4, uuid5

from care_link_core.plans_review_context import validate_entry

from .storage import exclusive, private_directory, read_json, write_json
from .types import JsonRecord

ROLES = {
    "pid": "pid",
    "carer": "carer",
    "professional": "professional_participant",
    "worker1": "worker",
}


def stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


def operation(run: JsonRecord, step: str) -> str:
    return str(uuid5(UUID(run["run_id"]), step))


class Adapter(Protocol):
    def prepare(self, run: JsonRecord, checkpoint: Callable[[], None]) -> JsonRecord: ...
    def close(self, run: JsonRecord, checkpoint: Callable[[], None]) -> None: ...


class PlansReviewLifecycle:
    def __init__(
        self,
        state_dir: Path,
        registry_path: Path,
        adapter: Adapter,
        *,
        environment_id: str,
        target_id: str,
        port: int | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (
            not environment_id
            or not target_id
            or (port is not None and (type(port) is not int or not 1 <= port <= 65535))
        ):
            raise ValueError("Explicit synthetic environment, target and valid port required")
        self.state_dir, self.registry_path, self.adapter = state_dir, registry_path, adapter
        self.environment_id, self.target_id, self.port, self.clock = (
            environment_id,
            target_id,
            port,
            clock,
        )
        private_directory(state_dir)
        private_directory(state_dir / "runs")
        private_directory(registry_path.parent)

    def _save(self, run: JsonRecord) -> None:
        write_json(self.state_dir / "runs" / (run["run_id"] + ".json"), run)

    def _current(self) -> JsonRecord | None:
        pointer = self.state_dir / "current.json"
        if not pointer.exists():
            return None
        run_id = read_json(pointer)["run_id"]
        if not isinstance(run_id, str) or str(UUID(run_id)) != run_id:
            raise ValueError("Invalid retained run identity")
        run = read_json(self.state_dir / "runs" / (run_id + ".json"))
        if (
            run.get("run_id") != run_id
            or run.get("environment_id") != self.environment_id
            or run.get("target_id") != self.target_id
        ):
            raise ValueError("Retained run belongs to another explicit target")
        return run

    def _publish(self, run: JsonRecord, state: str) -> None:
        existing = read_json(self.registry_path) if self.registry_path.exists() else {}
        for origin, entry in existing.items():
            validate_entry(origin, entry)
            retained = read_json(self.state_dir / "runs" / (entry["run_id"] + ".json"))
            if (
                retained["environment_id"] != self.environment_id
                or retained["target_id"] != self.target_id
            ):
                raise ValueError("Registry contains an unowned review run")
        entries: JsonRecord = {}
        for actor in run["actors"].values():
            selection = run.get("selections", {}).get(actor["slot_id"])
            if selection is None:
                continue  # No unprepared identity may become usable.
            entries[actor["origin"]] = {
                "mode": "plans",
                "authentication_mode": "automatic_review",
                "environment": "synthetic-review",
                "run_id": run["run_id"],
                **{
                    name: actor[name]
                    for name in ("slot_id", "account_id", "provider_subject", "role")
                },
                "state": state,
                "started_at": run["started_at"],
                "expires_at": run["expires_at"],
                **selection,
            }
        write_json(self.registry_path, entries)

    def _close(self, run: JsonRecord) -> JsonRecord:
        if run["state"] == "closed":
            return self._public(run)
        run["state"] = "closing"
        self._save(run)
        self._publish(run, "closing")
        self.adapter.close(run, lambda: self._save(run))
        self._publish(run, "closed")
        run["state"], run["closed_at"] = "closed", stamp(self.clock())
        self._save(run)
        return self._public(run)

    def close(self) -> JsonRecord:
        with exclusive(self.state_dir):
            run = self._current()
            return self._close(run) if run else {"state": "absent"}

    def inspect(self) -> JsonRecord:
        with exclusive(self.state_dir):
            run = self._current()
            return self._public(run) if run else {"state": "absent"}

    def _public(self, run: JsonRecord) -> JsonRecord:
        result = {
            key: run[key]
            for key in (
                "run_id",
                "state",
                "started_at",
                "expires_at",
                "target_id",
                "environment_id",
            )
        }
        if run["state"] == "ready" and self.clock() < datetime.fromisoformat(run["expires_at"]):
            result["actors"] = {
                slot: {
                    "origin": actor["origin"],
                    "url": actor["origin"] + "/plans-review",
                    "role": actor["role"],
                }
                for slot, actor in run["actors"].items()
            }
        return result

    def start_fresh(self, *, lifetime_seconds: int, run_id: str | None = None) -> JsonRecord:
        if type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= 14400:
            raise ValueError("Explicit review lifetime must be between one second and four hours")
        if run_id is not None and str(UUID(run_id)) != run_id:
            raise ValueError("Canonical run UUID required")
        with exclusive(self.state_dir):
            old = self._current()
            run: JsonRecord
            # A caller-supplied UUID is also the retry token; ready replay is read-only.
            if old and old["run_id"] == run_id and old["state"] == "ready":
                return self._public(old)
            if old and old["run_id"] == run_id and old["state"] == "preparing":
                run = old
            else:
                if old and old["state"] != "closed":
                    self._close(old)
                selected = run_id or str(uuid4())
                retained_path = self.state_dir / "runs" / (selected + ".json")
                if retained_path.exists():
                    run = read_json(retained_path)
                    if (
                        run.get("run_id") != selected
                        or run.get("state") != "preparing"
                        or run.get("target_id") != self.target_id
                        or run.get("environment_id") != self.environment_id
                    ):
                        raise ValueError("Historical runs cannot be revived")
                else:
                    now = self.clock()
                    run = {
                        "run_id": selected,
                        "state": "preparing",
                        "target_id": self.target_id,
                        "environment_id": self.environment_id,
                        "started_at": stamp(now),
                        "expires_at": stamp(now + timedelta(seconds=lifetime_seconds)),
                        "steps": {},
                        "actors": {},
                    }
                    for slot, role in ROLES.items():
                        run["actors"][slot] = {
                            "slot_id": slot,
                            "role": role,
                            "account_id": operation(run, "account:" + slot),
                            "provider_subject": operation(run, "provider-subject:" + slot),
                            "origin": f"https://r{UUID(selected).hex}-{slot}.plans.localhost"
                            + (f":{self.port}" if self.port else ""),
                        }
                    self._save(run)
                write_json(self.state_dir / "current.json", {"run_id": selected})
            if self.clock() >= datetime.fromisoformat(run["expires_at"]):
                raise ValueError("Expired preparation must be closed; never extended")
            selections = self.adapter.prepare(run, lambda: self._save(run))
            self._validate_selections(run, selections)
            if self.clock() >= datetime.fromisoformat(run["expires_at"]):
                raise ValueError("Preparation expired before readiness; close this run")
            run["selections"] = selections
            self._save(run)
            # Publication is the last serving change, after all adapters confirm readiness.
            self._publish(run, "active")
            run["state"] = "ready"
            self._save(run)
            return self._public(run)

    @staticmethod
    def _validate_selections(run: JsonRecord, selections: JsonRecord) -> None:
        if set(selections) != set(ROLES):
            raise ValueError("All four actor selections must be confirmed")
        for value in selections.values():
            if set(value) != {"session_id", "plan_id", "recipient_id"}:
                raise ValueError("Exact selection handles required")
            for key, handle in value.items():
                if handle is None and key != "session_id":
                    continue
                if not isinstance(handle, str) or str(UUID(handle)) != handle:
                    raise ValueError("Canonical server-issued resource handles required")
        if len({selections[slot]["session_id"] for slot in ("pid", "carer", "professional")}) != 3:
            raise ValueError("Participant sessions must be fresh and distinct")
        if selections["worker1"]["session_id"] != selections["pid"]["session_id"]:
            raise ValueError("Worker must target this run's PID session")
        if selections["pid"]["recipient_id"] != run["actors"]["worker1"]["account_id"]:
            raise ValueError("Sharing recipient must be this run's worker")
