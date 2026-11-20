"""Admitted synthetic directory versions and current, conservative option views.

Admission manifests are injected trusted configuration. Feed bytes never confer
source authority and never create an executable endpoint or network request.
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

from care_link_contracts import validate_contract
from care_link_domain import Actor, ManualError

from .engine import Engine
from .store import Record, Transaction, instant, number, text
from .values import Outcome, canonical, digest, dt, integer, object_value, stamp

TTL = {
    "structural": timedelta(hours=720),
    "operational": timedelta(hours=24),
    "near_realtime": timedelta(seconds=300),
}
FIELD_CLASSES = {
    "name": "structural",
    "jurisdictions": "structural",
    "languages": "structural",
    "age_scope": "structural",
    "police_involvement": "structural",
    "qualifications": "structural",
    "alternative_service_id": "structural",
    "hours_description": "operational",
    "operating_state": "operational",
    "availability": "near_realtime",
}
FIELDS = frozenset(
    {
        "name",
        "jurisdictions",
        "languages",
        "age_scope",
        "availability",
        "police_involvement",
        "qualifications",
        "alternative_service_id",
        "hours_description",
        "operating_state",
    }
)
STATE_QUALIFICATIONS = {
    "normal_operations": (
        "Normal fictional operations; availability requires current evidence.",
        "Fonctionnement fictif normal; disponibilité selon les preuves actuelles.",
    ),
    "temporary_closure": (
        "Temporary closure; this option is unavailable.",
        "Fermeture temporaire; cette option est indisponible.",
    ),
    "regional_outage": (
        "Regional outage; this option is unavailable.",
        "Panne régionale; cette option est indisponible.",
    ),
    "holiday_hours": (
        "Holiday hours; current event-specific verification is required.",
        "Horaire des jours fériés; vérification actuelle propre à cet événement requise.",
    ),
    "severe_weather": (
        "Severe weather; current event-specific verification is required.",
        "Intempéries; vérification actuelle propre à cet événement requise.",
    ),
    "api_failure": (
        "Source API unavailable; availability is unknown.",
        "API source indisponible; disponibilité inconnue.",
    ),
    "conflicting_source": (
        "Sources conflict; affected availability is unknown.",
        "Sources contradictoires; disponibilité concernée inconnue.",
    ),
}


def _sources(value: object) -> list[Record]:
    if not isinstance(value, list):
        raise ManualError("manual.directory_corrupt", 503)
    return [object_value(source) for source in cast(list[object], value)]


def _binding(manifest: Record, source: Record) -> Record | None:
    values = manifest.get("source_authorities")
    if not isinstance(values, list):
        return None
    for raw in cast(list[object], values):
        authority = object_value(raw)
        if all(authority.get(key) == source.get(key) for key in ("id", "revision", "digest")):
            return authority
    return None


def admission_reason(data: Record, manifests: dict[str, Record], now: datetime) -> str | None:
    """Verify exact preadmitted bytes, source ownership and complete field provenance."""
    manifest = manifests.get(text(data, "feed_artifact_digest"))
    if manifest is None or manifest.get("admitted") is not True:
        return "artifact_not_admitted"
    payload = {key: data[key] for key in ("service_id", "facts", "sources")}
    if manifest.get("service_id") != data["service_id"] or manifest.get("payload_digest") != digest(
        payload
    ):
        return "artifact_binding_mismatch"
    sources = _sources(data["sources"])
    needs = manifest.get("needs")
    if (
        not isinstance(needs, list)
        or not needs
        or len(cast(list[object], needs)) > 4
        or not all(
            isinstance(need, str)
            and need in {"client_support", "carer_support", "navigation", "interpretation"}
            for need in cast(list[object], needs)
        )
    ):
        return "source_service_scope_missing"
    covered: set[str] = set()
    seen: set[str] = set()
    for source in sources:
        authority = _binding(manifest, source)
        if (
            source["kind"] != "directory"
            or source["verification"] not in {"verified", "disputed"}
            or authority is None
            or not authority.get("owner")
            or not authority.get("method")
            or text(source, "id") in seen
            or dt(source["observed_at"]) > now + timedelta(seconds=1)
        ):
            return "source_authority_invalid"
        seen.add(text(source, "id"))
        classes = authority.get("field_classes")
        if not isinstance(classes, dict):
            return "source_field_provenance_missing"
        for field, category in cast(dict[str, object], classes).items():
            if field not in FIELDS or not isinstance(category, str) or category not in TTL:
                return "source_field_provenance_invalid"
            if TTL[category] > TTL[FIELD_CLASSES[field]]:
                return "source_freshness_class_too_long"
            covered.add(field)
    if covered != set(FIELDS):
        return "source_field_provenance_missing"
    facts = object_value(data["facts"])
    if (
        any(source["verification"] == "disputed" for source in sources)
        and facts["operating_state"] != "conflicting_source"
    ):
        return "conflict_not_preserved"
    # These fields are informational text only. Executable destination material
    # is not part of this contract, even when an artifact was misconfigured.
    if any(
        marker in canonical(facts).lower()
        for marker in ("https://", "http://", "javascript:", "file://")
    ):
        return "destination_material_forbidden"
    if len(canonical(data).encode()) > 65536:
        return "feed_too_large"
    return None


class Directory(Engine):
    def lookup_directory(self, tx: Transaction, service_id: str) -> Record:
        guard = tx.get("service_guard", service_id)
        if guard is None:
            raise ManualError("manual.not_found", 404)
        rows = tx.rows(
            "directory", service_id=service_id, revision=guard["current_revision"], limit=1
        )
        if not rows:
            raise ManualError("manual.directory_corrupt", 503)
        return rows[0]

    def directory_projection(self, tx: Transaction, row: Record) -> Record:
        facts = dict(object_value(row["facts"]))
        sources = _sources(row["sources"])
        service_id = text(row, "service_id")
        guard = tx.get("service_guard", service_id)
        state = text(row, "state")
        manifest = self.directory_artifacts.get(text(row, "artifact_digest"))
        current = self.clock()
        event_verified = True
        expiry = instant(row, "expires_at")
        if manifest is None or admission_reason(
            {
                "service_id": service_id,
                "facts": row["facts"],
                "sources": row["sources"],
                "feed_artifact_digest": row["artifact_digest"],
            },
            self.directory_artifacts,
            current,
        ):
            state = "quarantined"
        else:
            for source in sources:
                authority = _binding(manifest, source)
                if authority is None:
                    state = "quarantined"
                    break
                classes = object_value(authority["field_classes"])
                for category in classes.values():
                    expiry = min(expiry, dt(source["observed_at"]) + TTL[cast(str, category)])
                if (
                    authority.get("event_verified") is not True
                    or dt(source["observed_at"]) + TTL["near_realtime"] <= current
                ):
                    event_verified = False
            if state == "verified" and expiry <= current:
                state = "stale"
        if guard is None or guard["current_revision"] != row["revision"]:
            raise ManualError("manual.directory_stale", 409)
        if guard["suspended"] is True:
            state = "suspended"
        operating = text(facts, "operating_state")
        if operating in {"temporary_closure", "regional_outage"}:
            facts["availability"] = "unavailable"
        elif (
            state != "verified"
            or operating in {"api_failure", "conflicting_source"}
            or (operating in {"holiday_hours", "severe_weather"} and not event_verified)
        ):
            facts["availability"] = "unknown"
        if state != "verified":
            facts["hours_description"] = (
                "Current hours unknown; source not current. / "
                "Horaire actuel inconnu; source non actuelle."
            )
        alternative = facts["alternative_service_id"]
        if alternative is not None:
            alternative_guard = tx.get("service_guard", cast(str, alternative))
            if (
                state != "verified"
                or alternative == service_id
                or alternative_guard is None
                or alternative_guard["suspended"] is True
            ):
                facts["alternative_service_id"] = None
            else:
                candidate = self.lookup_directory(tx, cast(str, alternative))
                candidate_facts = object_value(candidate["facts"])
                if (
                    candidate["state"] != "verified"
                    or instant(candidate, "expires_at") <= current
                    or candidate_facts["operating_state"]
                    in {"temporary_closure", "regional_outage", "api_failure", "conflicting_source"}
                    or admission_reason(
                        {
                            "service_id": alternative,
                            "facts": candidate["facts"],
                            "sources": candidate["sources"],
                            "feed_artifact_digest": candidate["artifact_digest"],
                        },
                        self.directory_artifacts,
                        current,
                    )
                ):
                    facts["alternative_service_id"] = None
        english, french = STATE_QUALIFICATIONS[operating]
        warning = english + " / " + french
        if state != "verified":
            warning += (
                " Source "
                + state
                + "; availability unknown. / Source non actuelle; disponibilité inconnue."
            )
        if facts["alternative_service_id"] is None:
            warning += " No reviewed alternative. / Aucune autre option examinée."
        existing = facts["qualifications"]
        if not isinstance(existing, list):
            raise ManualError("manual.directory_corrupt", 503)
        # Never remove an admitted qualification to make room for UI copy.
        # UI independently renders the closed state and explicit absence.
        if len(cast(list[object], existing)) < 8:
            facts["qualifications"] = [*cast(list[str], existing), warning[:512]]
        return {
            "id": service_id,
            "revision": str(number(row, "revision")),
            "facts": facts,
            "sources": sources,
            "state": state,
            "verified_at": stamp(instant(row, "verified_at")),
            "expires_at": stamp(expiry),
        }

    def directory_read(self, actor: Actor, service_id: str) -> Record:
        def read(
            tx: Transaction,
            _actor: Actor,
            _data: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            return Outcome(
                "DirectoryView",
                self.directory_projection(tx, self.lookup_directory(tx, service_id)),
                service_id,
            )

        return self._run(actor, "directory_read", None, {"service_id": service_id}, None, read)

    def _directory_cursor(self, actor: Actor, query: Record, raw: str | None) -> str | None:
        if raw is None:
            return None
        if not self.cursor_key:
            raise ManualError("manual.pagination_unconfigured", 503)
        try:
            encoded, signature = raw.split(".")
            expected = hmac.new(self.cursor_key, encoded.encode(), hashlib.sha256).hexdigest()
            value = object_value(json.loads(bytes.fromhex(encoded)))
            if (
                not hmac.compare_digest(signature, expected)
                or value["principal"] != actor.account_id
                or value["query"] != digest({k: v for k, v in query.items() if k != "cursor"})
                or dt(value["expires"]) <= self.clock()
            ):
                raise ValueError("invalid cursor")
            return text(value, "after")
        except (ValueError, KeyError, TypeError) as error:
            raise ManualError("manual.cursor_invalid", 422) from error

    def directory_search(self, actor: Actor, key: str, data: Record) -> Record:
        def search(
            tx: Transaction,
            current: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            after = self._directory_cursor(current, body, cast(str | None, body.get("cursor")))
            limit = cast(int, body.get("limit", 50))
            items: list[Record] = []
            last = after
            # Walk bounded repository pages; skip mismatched locale/jurisdiction
            # without falsely reporting no later entries. Work stays capped.
            scanned = 0
            more = True
            while len(items) <= limit and more and scanned < 100:
                batch_size = min(51, 100 - scanned)
                guards = tx.directory_page(last, batch_size)
                more = bool(guards)
                for guard in guards:
                    last = text(guard, "service_id")
                    row = self.lookup_directory(tx, last)
                    view = self.directory_projection(tx, row)
                    facts = object_value(view["facts"])
                    manifest = self.directory_artifacts.get(text(row, "artifact_digest"), {})
                    needs = manifest.get("needs", [])
                    scanned += 1
                    if (
                        body["need"] in cast(list[str], needs)
                        and body["jurisdiction"] in cast(list[str], facts["jurisdictions"])
                        and body["locale"] in cast(list[str], facts["languages"])
                    ):
                        items.append(view)
                        if len(items) > limit:
                            break
                if len(guards) < batch_size and len(items) <= limit:
                    more = False
            next_cursor = None
            if len(items) > limit:
                last = text(items[limit - 1], "id")
                items = items[:limit]
                more = True
            if more and last is not None:
                if not self.cursor_key:
                    raise ManualError("manual.pagination_unconfigured", 503)
                encoded = (
                    canonical(
                        {
                            "principal": current.account_id,
                            "query": digest({k: v for k, v in body.items() if k != "cursor"}),
                            "after": last,
                            "expires": stamp(self.clock() + timedelta(minutes=5)),
                        }
                    )
                    .encode()
                    .hex()
                )
                next_cursor = (
                    encoded
                    + "."
                    + hmac.new(self.cursor_key, encoded.encode(), hashlib.sha256).hexdigest()
                )
            return Outcome("DirectoryPage", {"items": items, "next_cursor": next_cursor})

        return self._run(
            actor,
            "directory_search",
            key,
            data,
            None,
            search,
            contract="DirectoryQuery",
            replay=search,
        )

    def directory_ingest(self, actor: Actor, key: str, data: Record) -> Record:
        def ingest(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            service_id = text(body, "service_id")
            guard = tx.get("service_guard", service_id)
            revision = number(guard, "current_revision") if guard else 0
            if integer(body["expected_revision"]) != revision:
                raise ManualError("manual.stale_revision", 409)
            reason = admission_reason(body, self.directory_artifacts, self.clock())
            if reason is not None:
                tx.put(
                    "directory_quarantine",
                    {
                        "id": str(uuid4()),
                        "service_id": service_id,
                        "artifact_digest": body["feed_artifact_digest"],
                        "payload_digest": digest(body),
                        "reason": reason,
                        "created_at": self.clock(),
                    },
                )
                if guard:
                    view = self.directory_projection(tx, self.lookup_directory(tx, service_id))
                    view["state"] = "quarantined"
                    object_value(view["facts"])["availability"] = "unknown"
                else:
                    facts: Record = {
                        "name": "Unadmitted fictional source / Source fictive non admise",
                        "jurisdictions": ["CA-XX"],
                        "languages": ["en-CA", "fr-CA"],
                        "age_scope": "all_fixture",
                        "availability": "unknown",
                        "police_involvement": "unknown",
                        "qualifications": [
                            "Source quarantined; no option admitted. / "
                            "Source en quarantaine; aucune option admise."
                        ],
                        "alternative_service_id": None,
                        "hours_description": "Unknown / Inconnu",
                        "operating_state": "api_failure",
                    }
                    view = {
                        "id": service_id,
                        "revision": "0",
                        "facts": facts,
                        "sources": body["sources"],
                        "state": "quarantined",
                        "verified_at": stamp(self.clock()),
                        "expires_at": stamp(self.clock()),
                    }
                return Outcome("DirectoryView", view, service_id)
            now = self.clock()
            sources = _sources(body["sources"])
            manifest = self.directory_artifacts[text(body, "feed_artifact_digest")]
            expiry = now + TTL["structural"]
            for source in sources:
                authority = _binding(manifest, source)
                if authority is None:
                    raise ManualError("manual.directory_corrupt", 503)
                for category in object_value(authority["field_classes"]).values():
                    expiry = min(expiry, dt(source["observed_at"]) + TTL[cast(str, category)])
            new_revision = integer(str(revision + 1))
            row: Record = {
                "id": str(uuid4()),
                "service_id": service_id,
                "revision": new_revision,
                "environment": "demo",
                "population": "synthetic",
                "created_at": now,
                "updated_at": now,
                "facts": body["facts"],
                "sources": sources,
                "state": "verified",
                "verified_at": now,
                "expires_at": expiry,
                "source_revision": max(integer(source["revision"]) for source in sources),
                "freshness_class": "near_realtime",
                "artifact_digest": body["feed_artifact_digest"],
            }
            tx.put("directory", row)
            tx.put(
                "service_guard",
                {
                    "service_id": service_id,
                    "current_revision": new_revision,
                    "suspension_revision": number(guard, "suspension_revision") if guard else 0,
                    "suspended": guard["suspended"] if guard else False,
                },
            )
            return Outcome("DirectoryView", self.directory_projection(tx, row), service_id)

        return self._run(
            actor, "directory_ingest", key, data, None, ingest, contract="DirectoryIngest"
        )

    def directory_suspend(self, actor: Actor, key: str, data: Record, service_id: str) -> Record:
        def suspend(
            tx: Transaction,
            _actor: Actor,
            body: Record,
            _session: Record | None,
            _guard: Record | None,
        ) -> Outcome:
            guard = tx.get("service_guard", service_id)
            if guard is None:
                raise ManualError("manual.not_found", 404)
            if integer(body["expected_revision"]) != number(guard, "current_revision"):
                raise ManualError("manual.stale_revision", 409)
            control = tx.get("control", "demo")
            if control is None:
                raise ManualError("manual.bootstrap_missing", 503)
            self.append_restriction(
                tx,
                key,
                control,
                {
                    "kind": "service_suspend",
                    "service_id": service_id,
                    "directory_revision": str(number(guard, "current_revision")),
                    "suspended": True,
                },
                {
                    "session_id": None,
                    "subject_id": None,
                    "purpose": "security",
                    "fields": [],
                    "recipient_id": None,
                },
            )
            guard["suspension_revision"] = integer(str(number(guard, "suspension_revision") + 1))
            guard["suspended"] = True
            tx.put("service_guard", guard)
            return Outcome(
                "CommandResult",
                {
                    "operation_id": key,
                    "state": "committed",
                    "resource_id": service_id,
                    "revision": str(number(guard, "current_revision")),
                    "audit_ref": str(uuid4()),
                },
                service_id,
            )

        validate_contract("ReasonCommand", data)
        return self._run(
            actor, "directory_suspend", key, {**data, "service_id": service_id}, None, suspend
        )
