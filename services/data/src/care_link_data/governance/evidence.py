"""Guarded scoped audit metadata, export references and aggregate evidence."""

import base64
import binascii
import hashlib
import hmac
import json
from datetime import timedelta
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from ..engine import Engine
from ..store import Record, Transaction, instant, number, text
from ..values import Outcome, canonical, digest, dt, integer, object_value, stamp
from .authority import current_human
from .grants import check_grant, grant_values
from .metrics import read_metrics

EVIDENCE_ACTIONS = frozenset(
    {"scoped_access_grant", "audit_query", "metrics_query", "evidence_export", "audit_export_read"}
)


def query_filter(query: Record) -> Record:
    return {
        name: value for name, value in query.items() if name not in {"cursor", "limit", "export_id"}
    }


def cursor_encode(key: bytes | None, query: Record, sequence: int) -> str:
    if key is None:
        raise ManualError("governance.cursor_custody_missing", 503)
    payload = canonical({"query": digest(query_filter(query)), "sequence": str(sequence)})
    signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode((payload + "." + signature).encode()).decode()


def cursor_decode(key: bytes | None, query: Record) -> int:
    token = query.get("cursor")
    if token is None:
        return 0
    if key is None or not isinstance(token, str):
        raise ManualError("governance.invalid_cursor", 422)
    try:
        raw = base64.b64decode(token, altchars=b"-_", validate=True).decode()
        encoded, signature = raw.rsplit(".", 1)
        expected = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        payload = object_value(json.loads(encoded))
        if set(payload) != {"query", "sequence"} or payload["query"] != digest(query_filter(query)):
            raise ValueError("Wrong scope")
        sequence = integer(payload["sequence"])
        if sequence < 0 or str(sequence) != payload["sequence"]:
            raise ValueError("Invalid position")
        return sequence
    except (ValueError, UnicodeError, binascii.Error, ManualError) as error:
        raise ManualError("governance.invalid_cursor", 422) from error


def audit_page(service: Engine, tx: Transaction, actor: Actor, query: Record) -> Record:
    control = tx.get("control", "demo")
    if control is None:
        raise ManualError("manual.bootstrap_missing", 503)
    check_grant(tx, actor, query, service.clock(), epoch=number(control, "epoch"))
    limit = query.get("limit", 50)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ManualError("governance.invalid_page_limit", 422)
    after = cursor_decode(service.cursor_key, query)
    rows = tx.connection.execute(
        "SELECT * FROM audit.scoped_page(%s,%s,%s,%s,%s,%s)",
        (
            query["grant_id"],
            dt(query["from"]),
            dt(query["to"]),
            query.get("action"),
            after,
            limit + 1,
        ),
    ).fetchall()
    selected = rows[:limit]
    items: list[Record] = []
    for row in selected:
        item: Record = {
            name: str(row[name]) if name in {"id", "operation_id", "sequence"} else row[name]
            for name in (
                "id",
                "sequence",
                "operation_id",
                "action",
                "decision",
                "input_digest",
                "output_digest",
                "previous_hash",
                "hash",
            )
        }
        item["created_at"] = stamp(instant(row, "created_at"))
        items.append(item)
    next_cursor = (
        cursor_encode(service.cursor_key, query, number(selected[-1], "sequence"))
        if (len(rows) > limit and selected)
        else None
    )
    return {"items": items, "next_cursor": next_cursor}


def export_query(service: Engine, tx: Transaction, actor: Actor, data: Record) -> Record:
    row = tx.get("gov_audit_export", text(data, "export_id"))
    if row is None or row["principal_id"] != actor.account_id:
        raise ManualError("manual.not_found", 404)
    if instant(row, "expires_at") <= service.clock():
        raise ManualError("governance.export_expired", 410)
    if digest(query_filter(data)) != row["query_digest"]:
        raise ManualError("governance.export_scope_changed", 403)
    return {key: value for key, value in data.items() if key != "export_id"}


class Evidence(Engine):
    def scoped_access_grant(self, actor: Actor, key: str, data: Record) -> Record:
        def apply(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            control = tx.get("control", "demo")
            if control is None:
                raise ManualError("manual.bootstrap_missing", 503)
            if integer(body["expected_revision"]) != number(control, "epoch"):
                raise ManualError("manual.stale_revision", 409)
            row = {
                "id": str(uuid4()),
                "control_epoch": number(control, "epoch"),
                **grant_values(tx, current, body, self.clock()),
            }
            tx.put("gov_scope_grant", row)
            return self._evidence_command(key, text(row, "id"))

        def replay(
            tx: Transaction,
            current: Actor,
            _body: Record,
            _s: Record | None,
            _g: Record | None,
        ) -> Outcome:
            return self._reference_replay(tx, current, key, "gov_scope_grant")

        return self._run(
            actor,
            "scoped_access_grant",
            key,
            data,
            None,
            apply,
            contract="ScopeGrantCreate",
            replay=replay,
        )

    def _reference_replay(
        self, tx: Transaction, actor: Actor, key: str, repository: str
    ) -> Outcome:
        operation = tx.get("operation", key)
        row = tx.get(repository, text(operation, "resource_id")) if operation else None
        if row is None or instant(row, "expires_at") <= self.clock():
            raise ManualError("governance.evidence_reference_expired", 410)
        if repository == "gov_scope_grant" and row["revoked"] is not False:
            raise ManualError("governance.audit_grant_stale", 403)
        if repository == "gov_audit_export" and row["principal_id"] != actor.account_id:
            raise ManualError("manual.not_found", 404)
        result = self._evidence_command(key, text(row, "id"))
        if operation:
            result.value["audit_ref"] = operation["canonical_audit_id"]
        return result

    @staticmethod
    def _evidence_command(key: str, resource: str) -> Outcome:
        return Outcome(
            "CommandResult",
            {
                "operation_id": key,
                "state": "committed",
                "resource_id": resource,
                "revision": "1",
                "audit_ref": str(uuid4()),
            },
            resource,
        )

    def audit_query(self, actor: Actor, key: str, data: Record) -> Record:
        def read(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            return Outcome("AuditPage", audit_page(self, tx, current, body))

        return self._run(
            actor, "audit_query", key, data, None, read, contract="AuditQuery", replay=read
        )

    def metrics_query(self, actor: Actor, key: str, data: Record) -> Record:
        def read(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            current_human(tx, current, self.clock())
            return Outcome("MetricsView", read_metrics(tx, body, self.clock()))

        return self._run(
            actor, "metrics_query", key, data, None, read, contract="MetricsQuery", replay=read
        )

    def evidence_export(self, actor: Actor, key: str, data: Record) -> Record:
        def apply(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            if body.get("cursor") is not None:
                raise ManualError("governance.export_requires_first_page", 422)
            control = tx.get("control", "demo")
            if control is None:
                raise ManualError("manual.bootstrap_missing", 503)
            grant = check_grant(tx, current, body, self.clock(), epoch=number(control, "epoch"))
            target = str(uuid4())
            # Reference-only export. Pages are regenerated under the current
            # grant at download; no audit bytes or raw content are materialized.
            tx.put(
                "gov_audit_export",
                {
                    "id": target,
                    "principal_id": current.account_id,
                    "grant_id": body["grant_id"],
                    "revision": 1,
                    "query": query_filter(body),
                    "query_digest": digest(query_filter(body)),
                    "created_at": self.clock(),
                    "expires_at": min(
                        instant(grant, "expires_at"), self.clock() + timedelta(minutes=15)
                    ),
                },
            )
            return self._evidence_command(key, target)

        def replay(
            tx: Transaction,
            current: Actor,
            _body: Record,
            _s: Record | None,
            _g: Record | None,
        ) -> Outcome:
            return self._reference_replay(tx, current, key, "gov_audit_export")

        return self._run(
            actor,
            "evidence_export",
            key,
            data,
            None,
            apply,
            contract="AuditQuery",
            replay=replay,
        )

    def audit_export_read(self, actor: Actor, export_id: str, data: Record) -> Record:
        validate_contract("AuditQuery", data)

        def read(
            tx: Transaction, current: Actor, body: Record, _s: Record | None, _g: Record | None
        ) -> Outcome:
            query = export_query(self, tx, current, body)
            return Outcome("AuditPage", audit_page(self, tx, current, query))

        return self._run(
            actor, "audit_export_read", None, {**data, "export_id": export_id}, None, read
        )


def enrich_evidence_policy(
    service: Engine,
    tx: Transaction,
    actor: Actor,
    action: str,
    arguments: Record,
    snapshot: Record,
    request: Record,
) -> None:
    if action not in EVIDENCE_ACTIONS:
        return
    facts = object_value(request["authority_facts"])
    scope = object_value(request["scope"])
    scope["purpose"] = "governance" if action == "scoped_access_grant" else "audit"
    allowed = bool(facts["resource_owned_or_assigned"])
    try:
        current_human(tx, actor, service.clock())
        if action == "scoped_access_grant":
            grant_values(tx, actor, arguments, service.clock())
        elif action in {"audit_query", "evidence_export", "audit_export_read"}:
            query = (
                export_query(service, tx, actor, arguments)
                if action == "audit_export_read"
                else arguments
            )
            control = object_value(snapshot["control"])
            grant = check_grant(tx, actor, query, service.clock(), epoch=number(control, "epoch"))
            object_value(request["versions"])["resource"] = str(number(grant, "revision"))
            selected = object_value(grant["scope"])
            scope.update(selected)
            scope["purpose"] = "audit"
        elif action == "metrics_query":
            read_metrics(tx, arguments, service.clock())
    except (ManualError, KeyError, ValueError):
        allowed = False
    facts["resource_owned_or_assigned"] = allowed
    facts["field_scope_allowed"] = allowed


def check_evidence_output(
    service: Engine,
    tx: Transaction,
    actor: Actor,
    action: str,
    _result: Record,
    arguments: Record,
) -> None:
    if action not in EVIDENCE_ACTIONS:
        return
    current_human(tx, actor, service.clock())
    if action == "metrics_query":
        # Revalidate fixed release and disclosure authority after canonical audit.
        read_metrics(tx, arguments, service.clock())
    elif action in {"audit_query", "evidence_export", "audit_export_read"}:
        query = (
            export_query(service, tx, actor, arguments)
            if action == "audit_export_read"
            else arguments
        )
        control = tx.get("control", "demo")
        if control is None:
            raise ManualError("manual.bootstrap_missing", 503)
        check_grant(tx, actor, query, service.clock(), epoch=number(control, "epoch"))
    elif action == "scoped_access_grant":
        grant_values(tx, actor, arguments, service.clock())
