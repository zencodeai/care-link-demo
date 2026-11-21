"""Bounded rotating copy graph scans and guarded content minimization."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from ..engine import Engine
from ..store import Record, Transaction, number, text
from .graph import graph_blockers, hold_matches


class CopyPurger:
    def __init__(self, service: Engine, clock: Callable[[], datetime]) -> None:
        self.service, self.clock = service, clock

    def run(self, tx: Transaction, data: Record, limit: int) -> int:
        if limit <= 0:
            return 0
        tx.scope(None, queue=True)
        anchored = self.anchor_referrals(tx, limit) if data["class"] == "referral" else 0
        limit -= anchored
        if limit <= 0:
            return anchored
        tx.scope(None, queue=True)
        # Select work, never the first N historical inventory rows. Old purged
        # copies cannot starve new subjects or roll back unrelated inbox delivery.
        previous = tx.connection.execute(
            "SELECT subject_id FROM lifecycle.scan_cursor WHERE class=%s", (data["class"],)
        ).fetchone()
        cursor = str(previous["subject_id"]) if previous else "00000000-0000-0000-0000-000000000000"
        subjects = tx.connection.execute(
            "SELECT subject_id FROM (SELECT subject_id FROM lifecycle.copy "
            "WHERE state<>'purged' AND anchor_at IS NOT NULL AND expires_at<=%s "
            "UNION SELECT subject_id FROM rights.request WHERE kind='delete' "
            "AND state IN ('eligible','held','reconciliation_needed')) s "
            "ORDER BY (subject_id>%s::uuid) DESC,subject_id LIMIT %s",
            (self.clock(), cursor, limit),
        ).fetchall()
        done = 0
        for item in subjects:
            if done >= limit:
                break
            subject_id = str(item["subject_id"])
            tx.connection.execute(
                "INSERT INTO lifecycle.scan_cursor VALUES(%s,%s) "
                "ON CONFLICT(class) DO UPDATE SET subject_id=EXCLUDED.subject_id",
                (data["class"], subject_id),
            )
            tx.scope(None, queue=True)
            # Metadata reads avoid taking arbitrary child locks before subject.
            tx.locked = False
            pending = tx.rows("rights", subject_id=subject_id, kind="delete", limit=100)
            tx.locked = True
            requests = [
                r for r in pending if r["state"] in {"eligible", "held", "reconciliation_needed"}
            ]
            # Include all connected dependencies, including retained children and
            # purged parents. UNION terminates a cyclic connected graph safely.
            rows = tx.connection.execute(
                "WITH RECURSIVE component(id) AS ("
                " SELECT copy_id FROM lifecycle.copy WHERE subject_id=%s AND state<>'purged'"
                " UNION SELECT CASE WHEN d.parent_copy_id=c.id THEN d.child_copy_id "
                " ELSE d.parent_copy_id END FROM component c JOIN lifecycle.dependency d "
                " ON d.parent_copy_id=c.id OR d.child_copy_id=c.id)"
                " SELECT x.* FROM lifecycle.copy x JOIN component c ON c.id=x.copy_id "
                " ORDER BY x.copy_id LIMIT 101",
                (subject_id,),
            ).fetchall()
            graph = {
                str(row["copy_id"]): cast(
                    Record, {k: str(v) if isinstance(v, UUID) else v for k, v in row.items()}
                )
                for row in rows
            }
            overflow = len(rows) > 100 or len(pending) == 100
            if overflow:
                for request in requests:
                    self._progress(
                        tx, request, ["lifecycle_graph_limit_review_required"], held=False
                    )
                continue
            ids = list(graph)
            edges = tx.connection.execute(
                "SELECT parent_copy_id,child_copy_id FROM lifecycle.dependency "
                "WHERE parent_copy_id=ANY(%s::uuid[]) OR child_copy_id=ANY(%s::uuid[]) "
                "ORDER BY parent_copy_id,child_copy_id LIMIT 10001",
                (ids, ids),
            ).fetchall()
            pairs = [(str(e["parent_copy_id"]), str(e["child_copy_id"])) for e in edges]
            sessions = sorted({text(row, "session_id") for row in graph.values()})
            subjects = sorted({text(row, "subject_id") for row in graph.values()})
            hold_rows = tx.connection.execute(
                "SELECT * FROM lifecycle.hold WHERE released_at IS NULL "
                "AND (expires_at IS NULL OR expires_at>%s) "
                "AND (scope->>'subject_id' IS NULL OR scope->>'subject_id'=ANY(%s::text[])) "
                "AND (scope->>'session_id' IS NULL OR scope->>'session_id'=ANY(%s::text[])) "
                "ORDER BY id LIMIT 101",
                (self.clock(), subjects, sessions),
            ).fetchall()
            holds = [dict(h) for h in hold_rows]
            if len(holds) > 100:
                for request in requests:
                    self._progress(tx, request, ["hold_inventory_limit_review_required"], held=True)
                continue
            subject = tx.get("subject", subject_id)
            if subject is None:
                continue
            right = bool(requests and subject["delete_state"] == "restricted")
            blockers = graph_blockers(
                graph, pairs, self.clock(), rights_subject=subject_id if right else None
            )
            for copy_id, row in graph.items():
                if row["state"] == "purged":
                    continue
                tx.scope(text(row, "session_id"))
                source = tx.connection.execute(
                    "SELECT * FROM lifecycle.copy_source(%s)", (copy_id,)
                ).fetchone()
                if source is None:
                    blockers[copy_id] = "source_inventory_review_required"
                elif source["blocked_reason"]:
                    blockers[copy_id] = str(source["blocked_reason"])
                elif (
                    right
                    and source["owner_id"]
                    and str(source["owner_id"]) != requests[0]["requester_id"]
                ):
                    blockers[copy_id] = "other_author_private_content_retained"
            # Iterate leaves until the bounded batch is exhausted or no further
            # safe copy is available. Plan copies keep their independent anchors.
            changed = True
            while changed and done < limit:
                changed = False
                for copy_id, row in graph.items():
                    if done >= limit:
                        break
                    if row["state"] == "purged" or row["subject_id"] != subject_id:
                        continue
                    if not right and not self._class_matches(text(data, "class"), row):
                        continue
                    if copy_id in blockers or any(
                        hold_matches(h, row, self.clock()) for h in holds
                    ):
                        continue
                    if any(
                        parent == copy_id
                        and (child not in graph or graph[child]["state"] != "purged")
                        for parent, child in pairs
                    ):
                        continue
                    tx.scope(text(row, "session_id"))
                    tx.connection.execute(
                        "SELECT lifecycle.purge_copy(%s,%s)",
                        (copy_id, self.service.cipher.encrypt("{}")),
                    )
                    row["state"] = "purged"
                    done += 1
                    changed = True
            retained = [
                r
                for r in graph.values()
                if r["subject_id"] == subject_id and r["state"] != "purged"
            ]
            exceptions = sorted(
                {
                    reason
                    for key, reason in blockers.items()
                    if key in graph and graph[key]["subject_id"] == subject_id
                }
            )
            held = any(hold_matches(h, r, self.clock()) for h in holds for r in retained)
            if retained:
                exceptions.append("retained_active_copies:" + str(len(retained)))
            if held:
                exceptions.append("active_hold")
            for request in requests:
                self._progress(tx, request, exceptions, held=held)
        return done + anchored

    def anchor_referrals(self, tx: Transaction, limit: int) -> int:
        rows = tx.connection.execute(
            "SELECT c.copy_id,c.session_id,s.closed_at,r.dispatch_id "
            "FROM lifecycle.copy c JOIN core.session s ON s.id=c.session_id "
            "JOIN referral.generation r ON r.id=c.aggregate_id "
            "WHERE c.aggregate_type='referral' AND c.state='anchor_pending' "
            "AND s.closed_at IS NOT NULL AND (r.dispatch_id IS NULL OR EXISTS "
            "(SELECT 1 FROM referral.dispatch d WHERE d.id=r.dispatch_id "
            "AND d.state IN ('received','accepted','rejected','cancelled'))) "
            "ORDER BY c.copy_id LIMIT %s",
            (limit,),
        ).fetchall()
        count = 0
        for row in rows:
            tx.scope(str(row["session_id"]))
            copy = tx.get("copy", str(row["copy_id"]))
            if copy is None:
                continue
            anchor = (
                max(cast(datetime, row["closed_at"]), self.clock())
                if row["dispatch_id"]
                else cast(datetime, row["closed_at"])
            )
            copy["anchor_at"] = anchor
            copy["expires_at"] = anchor + timedelta(days=7)
            copy["state"] = "retained"
            tx.put("copy", copy)
            count += 1
        return count

    @staticmethod
    def _progress(tx: Transaction, request: Record, exceptions: list[str], *, held: bool) -> None:
        tx.scope(text(request, "session_id"))
        request["state"] = (
            "held" if held else "reconciliation_needed" if exceptions else "backup_pending"
        )
        request["exceptions"] = [
            "backup_erasure_pending_IMP09",
            "physical_erasure_not_proven",
            *exceptions,
        ][:32]
        request["revision"] = number(request, "revision") + 1
        tx.put("rights", request)

    @staticmethod
    def _class_matches(kind: str, row: Record) -> bool:
        return (
            kind == "referral"
            and row["purpose"] == "referral"
            or kind == "plan"
            and row["purpose"] == "plan"
            or kind == "export"
            and row["purpose"] == "rights"
            or kind in {"session", "person"}
            and row["purpose"] in {"support", "follow_up"}
        )
