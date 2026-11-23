"""Supervise the real scoped Runtime workload and sample the durable Data boundary."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from time import monotonic, monotonic_ns, sleep
from typing import Literal

from .deployed_bridge import bridge_observations, pause_connector
from .deployed_fixtures import Record, write
from .deployed_load import IssuedTask, Peak
from .deployed_measurement_data import jobs, occupied, peak, request_pair

type Condition = Literal["warm", "error"]


def wait_receipt(path: Path, budget: float) -> object:
    deadline = monotonic() + budget
    while monotonic() < deadline:
        if path.is_file() and not path.is_symlink():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                pass
        sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {path.name}")


class Measurement:
    def __init__(self, directory: Path, output: Path) -> None:
        info = directory.lstat()
        if directory.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("Exact owned browser load controller required")
        self.directory, self.output = directory, output
        self.ready: Record = json.loads((directory / "ready.json").read_text())
        self.sessions: tuple[str, ...] = tuple(sorted(self.ready["session_ids"]))
        if len(set(self.sessions)) != 10 or self.ready["active_scoped_sessions"] != 10:
            raise ValueError("Ten exact ongoing scoped sessions required")
        self.results: list[Record] = []

    def phase(self, number: int, name: str, budget: float) -> object:
        marker = self.directory / f"round-{number:02d}-{name}"
        write(marker, b"")
        return wait_receipt(marker.with_suffix(".json"), budget)

    def cohort(self, number: int) -> tuple[Sequence[IssuedTask], Sequence[IssuedTask], int]:
        admitted = self.phase(number, "pair", 20)
        first = tuple(IssuedTask(**raw) for raw in admitted)
        dispatch_at = monotonic_ns()
        request_pair()
        occupied(first)
        waiting = tuple(IssuedTask(**raw) for raw in self.phase(number, "waiting", 16))
        return first, waiting, dispatch_at

    def at_load(
        self, number: int, first: Sequence[IssuedTask], waiting: Sequence[IssuedTask]
    ) -> Record:
        expected = Peak(
            self.sessions,
            tuple(sorted(t.task_id for t in first)),
            tuple(sorted(t.task_id for t in waiting)),
        )
        before = peak(self.sessions, [*first, *waiting])
        reads = self.phase(number, "sample", 12)
        after = peak(self.sessions, [*first, *waiting])
        if before != expected or after != expected:
            raise RuntimeError("Observed durable 10/2/8 was missing before or after scoped reads")
        return {
            "active_session_ids": list(self.sessions),
            "occupied_task_ids": list(after.occupied_task_ids),
            "pending_task_ids": list(after.pending_task_ids),
            "session_reads_ms": reads["session_reads_ms"],
            "active_scoped_sessions": 10,
            "connected_sessions": self.ready["connected_sessions"],
            "occupied_inference_slots": 2,
            "unique_pending_tasks": 8,
        }

    def follow(
        self, first: Sequence[IssuedTask], states: set[str], *, budget: float
    ) -> list[Record]:
        ids = tuple(task.task_id for task in first)
        deadline = monotonic() + budget
        while monotonic() < deadline:
            result = jobs(ids)
            if len(result) == 2 and all(job["state"] in states for job in result):
                return result
            sleep(0.2)
        raise RuntimeError("Durable inference did not reach its bounded terminal state")

    def run(self, number: int, condition: Condition) -> Record:
        observation: Record = {"number": number, "condition": condition, "phase": "queue"}
        self.results.append(observation)
        baseline = len(bridge_observations())
        try:
            first, waiting, scheduled_at = self.cohort(number)
            observation["phase"] = "peak"
            observation["arrivals"] = [asdict(task) for task in (*first, *waiting)]
            observation["workload"] = self.at_load(number, first, waiting)
            observation["phase"] = "completion"
            if condition == "warm":
                final = self.follow(first, {"completed", "compute_unknown", "fenced"}, budget=34)
            else:
                with pause_connector():
                    final = self.follow(
                        first, {"compute_unknown", "completed", "fenced"}, budget=40
                    )
            observation["observed_from_dispatch_ms"] = round(
                (monotonic_ns() - scheduled_at) / 1e6, 3
            )
            observation["jobs"] = final
            observation["bridge"] = bridge_observations()[baseline:]
            if condition == "warm":
                observation["browser"] = self.phase(number, "status", 14)
                # Job completion can precede the guarded draft transaction. The actor
                # read supplies current TaskView; retain both physical observations.
                observation["jobs_after_actor_view"] = jobs(tuple(task.task_id for task in first))
            observation["phase"] = "cancel"
            observation["cancel"] = self.phase(number, "cancel", 20)
            observation["phase"] = "recorded"
            return observation
        finally:
            self.output.write_text(json.dumps(self.results, indent=2) + "\n")
