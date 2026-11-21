"""Replay restrictive journal payloads; positive/relaxing records never grant."""

from typing import cast

import psycopg
from care_link_contracts import validate_contract
from care_link_domain import ManualError
from psycopg.types.json import Jsonb

from ..values import digest

Record = dict[str, object]


def apply(connection: psycopg.Connection[Record], entry: Record, actor_id: str) -> bool:
    command = cast(Record, entry["command"])
    restriction = cast(Record, command["restriction"])
    validate_contract("JournalAppend", command)
    kind = str(restriction["kind"])
    old = connection.execute(
        "SELECT payload_digest,disposition FROM recovery.restriction WHERE command_id=%s",
        (command["command_id"],),
    ).fetchone()
    if old is not None:
        if old["payload_digest"] != digest(restriction):
            raise ManualError("recovery.restriction_conflict", 409)
        # Reapply current effects even if an older restore recorded 'applied'.
        # Snapshot metadata cannot certify that a restrictive kill was relaxed.
    applied = True
    if kind in {"identity_revoke", "role_revoke"}:
        field = "identity_revision" if kind == "identity_revoke" else "role_revision"
        # Fixed SQL alternatives; no journal-provided SQL identifiers.
        query = (
            "UPDATE control.principal_guard SET revoked=true,identity_revision="
            "GREATEST(identity_revision,%s) WHERE principal_id=%s"
            if field == "identity_revision"
            else "UPDATE control.principal_guard SET revoked=true,role_revision="
            "GREATEST(role_revision,%s) WHERE principal_id=%s"
        )
        connection.execute(query, (int(str(restriction[field])), restriction["principal_id"]))
    elif kind in {"consent_revoke", "share_revoke", "subject_delete"}:
        connection.execute(
            "UPDATE core.subject_guard SET authority_revision=GREATEST(authority_revision,%s),"
            "delete_state=CASE WHEN %s THEN 'restricted' ELSE delete_state END WHERE subject_id=%s",
            (
                int(str(restriction["subject_revision"])),
                kind == "subject_delete",
                restriction["subject_id"],
            ),
        )
        # All restored positive grants are already suspended before replay.
    elif kind == "hold":
        existing_hold = connection.execute(
            "SELECT scope FROM lifecycle.hold WHERE id=%s", (restriction["hold_id"],)
        ).fetchone()
        if existing_hold is not None and existing_hold["scope"] != restriction["scope"]:
            applied = False
        connection.execute(
            "INSERT INTO lifecycle.hold(id,revision,scope,reason,authority_ref,actor_id,created_at)"
            " VALUES(%s,1,%s,'recovery_restrictive_intent',%s,%s,%s) ON CONFLICT(id) DO UPDATE"
            " SET released_at=NULL,expires_at=NULL,revision=lifecycle.hold.revision+1"
            " WHERE lifecycle.hold.released_at IS NOT NULL"
            " OR lifecycle.hold.expires_at IS NOT NULL",
            (
                restriction["hold_id"],
                Jsonb(restriction["scope"]),
                restriction["authority_ref"],
                actor_id,
                restriction["starts_at"],
            ),
        )
        # A stale snapshot cannot establish that a hold expired or was released.
    elif kind == "kill":
        current = connection.execute("SELECT bundle_digest FROM control.guard").fetchone()
        if (
            current is None
            or current["bundle_digest"] != restriction["bundle_digest"]
            or restriction["mode"] in {"restricted", "quarantine"}
        ):
            # Promotion approval cannot relax an operational kill. Persist the
            # unresolved restriction even when the snapshot has matching bytes;
            # only a separately reviewed current-authority reconciliation can
            # establish that a restrictive kill was subsequently relaxed.
            applied = False
        connection.execute(
            "UPDATE control.guard SET epoch=GREATEST(epoch,%s),mode='quarantine'",
            (int(str(restriction["epoch"])),),
        )
    elif kind == "service_suspend":
        changed = connection.execute(
            "UPDATE knowledge.service_guard SET suspended=true,"
            "suspension_revision=GREATEST(suspension_revision,%s) WHERE service_id=%s",
            (int(str(restriction["directory_revision"])), restriction["service_id"]),
        )
        if changed.rowcount != 1:
            # An absent pre-capture guard cannot discard a current suspension;
            # a later ingestion must not silently create an active service.
            applied = False
    elif kind == "serving_fence":
        connection.execute("UPDATE control.guard SET mode='quarantine',serving_generation=0")
    elif kind == "workload_fence":
        # No stale instance ACK remains eligible, and AI remains disabled.
        connection.execute(
            "UPDATE governance.instance SET healthy=false WHERE workload_id=%s",
            (restriction["workload_id"],),
        )
    else:
        applied = False
    connection.execute(
        (
            "INSERT INTO recovery.restriction VALUES(%s,%s,%s,%s,%s,%s) ON "
            "CONFLICT(command_id) DO UPDATE SET disposition=EXCLUDED.disposition"
        ),
        (
            command["command_id"],
            int(str(entry["sequence"])),
            kind,
            Jsonb(restriction),
            digest(restriction),
            "applied" if applied else "unresolved",
        ),
    )
    return applied
