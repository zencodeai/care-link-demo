"""Durable data-owned compute slots; timeout/restart cannot create capacity.

The coordinator current callback rechecks and locks task/source/epoch guards in
this same transaction. It must use the established lock order. A job completion
is consumed once: repeated provider delivery cannot deliver the draft twice.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from .store import PostgresStore, Record, Transaction


@dataclass(frozen=True)
class _Broker:
    account_id: str = "inference-ledger"


@dataclass(frozen=True)
class InferenceAuthority:
    """Transaction-checked authority valid only up to the earliest retained deadline."""

    valid_until: datetime


def _current(authority: InferenceAuthority | bool, now: datetime) -> bool:
    return authority is True or (
        isinstance(authority, InferenceAuthority) and now < authority.valid_until
    )


class PostgresJobLedger:
    def __init__(
        self,
        store: PostgresStore,
        *,
        current: Callable[[Transaction, Record], InferenceAuthority | bool],
        completion_current: Callable[[Transaction, Record], InferenceAuthority | bool]
        | None = None,
        verified_stop_time: Callable[[str], datetime | None] = lambda _generation: None,
        bridge_generation: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store, self.current = store, current
        self.completion_current = completion_current or current
        self.verified_stop_time = verified_stop_time
        self.bridge_generation = bridge_generation
        self.clock = clock

    def reserve(self, record: Record) -> str | None:
        required = {
            "id",
            "task_id",
            "step_id",
            "fence",
            "revision",
            "model_digest",
            "prompt_digest",
            "request_digest",
            "deadline",
            "bridge_generation",
        }
        if set(record) != required or not isinstance(record["deadline"], datetime):
            raise ValueError("closed inference job record required")
        deadline = record["deadline"]
        if deadline.tzinfo is None or not 0 < (deadline - self.clock()).total_seconds() <= 30:
            raise ValueError("bounded absolute inference deadline required")
        for key in ("id", "task_id", "step_id"):
            UUID(str(record[key]))
        if (
            self.bridge_generation is not None
            and record["bridge_generation"] != self.bridge_generation
        ):
            return None
        with self.store.transaction(_Broker(), None) as tx:
            # Current authority is locked first; slots are locked after task guards.
            authority = self.current(tx, record)
            if not _current(authority, self.clock()):
                return None
            tx.connection.execute("SELECT pg_advisory_xact_lock(71306)")
            now = self.clock()
            if deadline <= now or not _current(authority, now):
                return None
            retired = tx.connection.execute(
                "SELECT 1 FROM assistance.inference_job WHERE bridge_generation=%s "
                "AND state='stopped' LIMIT 1",
                (record["bridge_generation"],),
            ).fetchone()
            if retired:
                return None
            existing = tx.connection.execute(
                "SELECT id FROM assistance.inference_job WHERE id=%s "
                "OR (task_id=%s AND step_id=%s AND fence=%s)",
                (record["id"], record["task_id"], record["step_id"], record["fence"]),
            ).fetchone()
            if existing:
                # Never repeat uncertain/provider work after a transport retry.
                return None
            slot = tx.connection.execute(
                "SELECT id FROM assistance.compute_slot WHERE state='free' ORDER BY id "
                "LIMIT 1 FOR UPDATE"
            ).fetchone()
            if slot is None:
                # Zero waiting jobs is within the eight-queued upper bound. Manual
                # requests never block on an inference queue or provider lock.
                return None
            now = self.clock()
            if deadline <= now or not _current(authority, now):
                return None
            slot_id = cast(str, slot["id"])
            tx.connection.execute(
                "INSERT INTO assistance.inference_job "
                "(id,task_id,step_id,fence,revision,model_digest,prompt_digest,request_digest,"
                "state,deadline,slot_id,bridge_generation) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'running',%s,%s,%s)",
                tuple(
                    record[key]
                    for key in (
                        "id",
                        "task_id",
                        "step_id",
                        "fence",
                        "revision",
                        "model_digest",
                        "prompt_digest",
                        "request_digest",
                        "deadline",
                    )
                )
                + (slot_id, record["bridge_generation"]),
            )
            tx.connection.execute(
                "UPDATE assistance.compute_slot SET state='occupied',job_id=%s,"
                "bridge_generation=%s WHERE id=%s",
                (record["id"], record["bridge_generation"], slot_id),
            )
            return slot_id

    def mark_unknown(self, job_id: str) -> None:
        with self.store.transaction(_Broker(), None) as tx:
            tx.connection.execute("SELECT pg_advisory_xact_lock(71306)")
            job = tx.connection.execute(
                "UPDATE assistance.inference_job SET state='compute_unknown' "
                "WHERE id=%s AND state='running' RETURNING slot_id",
                (job_id,),
            ).fetchone()
            if job:
                tx.connection.execute(
                    "UPDATE assistance.compute_slot SET state='compute_unknown' "
                    "WHERE id=%s AND job_id=%s",
                    (job["slot_id"], job_id),
                )

    def complete(self, job_id: str, result_digest: str, *, deliverable: bool) -> bool:
        with self.store.transaction(_Broker(), None) as tx:
            metadata = tx.connection.execute(
                "SELECT * FROM assistance.inference_job WHERE id=%s",
                (job_id,),
            ).fetchone()
            if metadata is None:
                return False
            # This callback locks task/epoch guards before the global slots lock.
            fresh = (
                deliverable
                and metadata["state"] == "running"
                and cast(datetime, metadata["deadline"]) > self.clock()
                and self.completion_current(tx, dict(metadata))
            )
            tx.connection.execute("SELECT pg_advisory_xact_lock(71306)")
            job = tx.connection.execute(
                "SELECT * FROM assistance.inference_job WHERE id=%s FOR UPDATE",
                (job_id,),
            ).fetchone()
            if job is None or job["state"] not in {"running", "compute_unknown"}:
                return False
            # An occupied slot row may still wait behind another transaction.
            tx.connection.execute(
                "SELECT id FROM assistance.compute_slot WHERE id=%s FOR UPDATE",
                (job["slot_id"],),
            )
            now = self.clock()
            # A timed-out/cancelled request never regains delivery authority from
            # a late reply, even if its original task still happens to be current.
            output_allowed = (
                deliverable
                and _current(fresh, now)
                and job["state"] == "running"
                and (
                    self.bridge_generation is None
                    or job["bridge_generation"] == self.bridge_generation
                )
                and cast(datetime, job["deadline"]) > now
            )
            tx.connection.execute(
                "UPDATE assistance.inference_job SET state=%s,result_digest=%s WHERE id=%s",
                ("completed" if output_allowed else "fenced", result_digest, job_id),
            )
            tx.connection.execute(
                "UPDATE assistance.compute_slot SET state='free',job_id=NULL,"
                "bridge_generation=NULL WHERE id=%s AND job_id=%s",
                (job["slot_id"], job_id),
            )
            return output_allowed

    def release_verified(self, job_id: str, bridge_generation: str) -> bool:
        """Caller must prove provider stop/recovery via authenticated control path.

        This method is deliberately absent from runtime/broker model tools and
        requires the exact generation owning the job, not a new process name.
        """
        if bridge_generation == self.bridge_generation:
            raise ValueError("authenticated provider stop evidence required")
        stopped_at = self.verified_stop_time(bridge_generation)
        if stopped_at is None or stopped_at.tzinfo is None or stopped_at > datetime.now(UTC):
            raise ValueError("authenticated provider stop evidence required")
        with self.store.transaction(_Broker(), None) as tx:
            tx.connection.execute("SELECT pg_advisory_xact_lock(71306)")
            job = tx.connection.execute(
                "UPDATE assistance.inference_job AS job SET state='stopped' "
                "FROM assistance.compute_slot AS slot "
                "WHERE job.id=%s AND job.bridge_generation=%s AND job.created_at<=%s "
                "AND job.state IN ('running','compute_unknown') "
                "AND slot.id=job.slot_id AND slot.job_id=job.id "
                "AND slot.bridge_generation=job.bridge_generation "
                "AND slot.state IN ('occupied','compute_unknown') RETURNING job.slot_id",
                (job_id, bridge_generation, stopped_at),
            ).fetchone()
            if job is None:
                return False
            tx.connection.execute(
                "UPDATE assistance.compute_slot SET state='free',job_id=NULL,"
                "bridge_generation=NULL WHERE id=%s AND job_id=%s",
                (job["slot_id"], job_id),
            )
            return True

    def reconcile_stopped(self) -> int:
        """Try only the two durable slots, including work orphaned by a crash."""
        if self.bridge_generation is None:
            return 0
        with self.store.transaction(_Broker(), None, locked=False) as tx:
            occupied = tx.connection.execute(
                "SELECT job_id,bridge_generation FROM assistance.compute_slot "
                "WHERE state IN ('occupied','compute_unknown') AND bridge_generation<>%s "
                "ORDER BY id LIMIT 2",
                (self.bridge_generation,),
            ).fetchall()
        released = 0
        for slot in occupied:
            try:
                released += self.release_verified(
                    str(slot["job_id"]), str(slot["bridge_generation"])
                )
            except ValueError:
                # An unavailable or invalid stop proof leaves the slot occupied.
                pass
        return released
