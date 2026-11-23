"""Read identifier-only workload evidence from the isolated G-10 Data store."""

from __future__ import annotations

import json
from collections.abc import Sequence
from time import monotonic, sleep
from uuid import UUID

from .deployed_fixtures import Record
from .deployed_load import IssuedTask, Peak
from .deployed_roles import k


def _ids(values: Sequence[str]) -> str:
    ids = tuple(str(UUID(v)) for v in values)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("Exact unique synthetic identifiers required")
    return ",".join(f"'{value}'::uuid" for value in ids)


def _select(query: str) -> list[Record]:
    result = k(
        "exec",
        "deployment/postgres",
        "--",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        "data",
        "-Atc",
        "BEGIN READ ONLY; " + query + "; COMMIT",
    )
    statements = result.splitlines()
    if statements[0] != "BEGIN" or statements[-1] != "COMMIT":
        raise RuntimeError("Read-only evidence transaction incomplete")
    return [json.loads(line) for line in statements[1:-1]]


def jobs(task_ids: Sequence[str]) -> list[Record]:
    targets = _ids(task_ids)
    return _select(
        "SELECT row_to_json(r) FROM ("  # noqa: S608 - fixed query and canonical UUIDs
        "SELECT j.task_id::text,j.created_at,j.state,j.result_digest IS NOT NULL AS result,"
        "s.state AS slot_state,(SELECT count(*) FROM assistance.draft d "
        "WHERE d.task_id=j.task_id) AS draft_count "
        "FROM assistance.inference_job j JOIN assistance.compute_slot s ON s.id=j.slot_id "
        f"WHERE j.task_id IN ({targets}) ORDER BY j.created_at,j.id) r"
    )


def peak(sessions: Sequence[str], tasks: Sequence[IssuedTask]) -> Peak:
    session_ids = _ids(sessions)
    task_ids = _ids(tuple(t.task_id for t in tasks))
    [result] = _select(
        "SELECT json_build_object("  # noqa: S608 - fixed query and canonical UUIDs
        "'sessions', (SELECT coalesce(json_agg(s.id::text ORDER BY s.id),'[]') "
        f"FROM core.session s WHERE s.id IN ({session_ids}) "
        "AND service_phase IN ('human_controlled','worker_assigned')),"
        "'occupied', (SELECT coalesce(json_agg(j.task_id::text ORDER BY j.task_id),'[]') "
        "FROM assistance.compute_slot s JOIN assistance.inference_job j ON s.job_id=j.id "
        f"WHERE s.state='occupied' AND j.state='running' AND j.task_id IN ({task_ids})),"
        "'pending', (SELECT coalesce(json_agg(t.id::text ORDER BY t.id),'[]') "
        f"FROM assistance.task t WHERE t.id IN ({task_ids}) AND NOT EXISTS "
        "(SELECT 1 FROM assistance.inference_job j WHERE j.task_id=t.id)))"
    )
    return Peak(tuple(result["sessions"]), tuple(result["occupied"]), tuple(result["pending"]))


def request_pair() -> None:
    k(
        "exec",
        "deployment/runtime",
        "-c",
        "app",
        "--",
        "python",
        "-c",
        "from pathlib import Path; Path('/state/dispatch-pair').touch(exist_ok=False)",
    )


def occupied(first: Sequence[IssuedTask], *, seconds: float = 12.0) -> list[Record]:
    identifiers = tuple(task.task_id for task in first)
    if len(identifiers) != 2:
        raise ValueError("Exact durable reservation pair required")
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        result = jobs(identifiers)
        if len(result) == 2 and all(
            job["slot_state"] == "occupied" and job["state"] == "running" for job in result
        ):
            return result
        sleep(0.25)
    raise RuntimeError("Both deployed reservations were not observed within their startup window")
