"""Directory source admission, honest operating states and guarded PostgreSQL effects."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import psycopg
import pytest
from care_link_contracts import validate_contract
from care_link_data.directory import (
    FIELD_CLASSES,
    Directory,
    admission_reason,
)
from care_link_data.store import Record, Transaction
from care_link_data.values import digest, object_value, stamp
from care_link_domain import ManualError

if TYPE_CHECKING:
    from services.data.tests.conftest import Harness


def feed(
    now: datetime, state: str = "normal_operations", *, event_verified: bool = False
) -> tuple[Record, Record]:
    service_id = str(uuid4())
    facts: Record = {
        "name": "Fictional service",
        "jurisdictions": ["CA-XX"],
        "languages": ["en-CA", "fr-CA"],
        "age_scope": "all_fixture",
        "availability": "available_fixture",
        "police_involvement": "unknown",
        "qualifications": ["Synthetic training option"],
        "alternative_service_id": None,
        "hours_description": "Fictional daytime hours",
        "operating_state": state,
    }
    source: Record = {
        "kind": "directory",
        "id": str(uuid4()),
        "revision": "1",
        "digest": "a" * 64,
        "observed_at": stamp(now),
        "verification": "disputed" if state == "conflicting_source" else "verified",
    }
    data: Record = {
        "expected_revision": "0",
        "service_id": service_id,
        "facts": facts,
        "sources": [source],
        "feed_artifact_digest": "b" * 64,
    }
    manifest: Record = {
        "admitted": True,
        "needs": ["client_support", "carer_support", "navigation", "interpretation"],
        "service_id": service_id,
        "payload_digest": digest({key: data[key] for key in ("service_id", "facts", "sources")}),
        "source_authorities": [
            {
                "id": source["id"],
                "revision": source["revision"],
                "digest": source["digest"],
                "owner": "fictional-demo-curator",
                "method": "synthetic_fixture_review",
                "field_classes": dict(FIELD_CLASSES),
                "event_verified": event_verified,
            }
        ],
    }
    return data, manifest


def unit_projection(
    data: Record, manifest: Record, now: datetime, *, suspended: bool = False
) -> Record:
    class Guards:
        def get(self, _repository: str, _identifier: str) -> Record:
            return {
                "service_id": data["service_id"],
                "current_revision": 1,
                "suspension_revision": 1,
                "suspended": suspended,
            }

    service = object.__new__(Directory)
    service.clock = lambda: now
    service.directory_artifacts = {str(data["feed_artifact_digest"]): manifest}
    observed = datetime.fromisoformat(
        str(object_value(cast(list[object], data["sources"])[0])["observed_at"])
    )
    row: Record = {
        "id": str(uuid4()),
        "service_id": data["service_id"],
        "revision": 1,
        "facts": data["facts"],
        "sources": data["sources"],
        "state": "verified",
        "verified_at": observed,
        "expires_at": observed + timedelta(hours=720),
        "artifact_digest": data["feed_artifact_digest"],
    }
    return service.directory_projection(cast(Transaction, Guards()), row)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("normal_operations", "available_fixture"),
        ("temporary_closure", "unavailable"),
        ("regional_outage", "unavailable"),
        ("holiday_hours", "unknown"),
        ("severe_weather", "unknown"),
        ("api_failure", "unknown"),
        ("conflicting_source", "unknown"),
    ],
)
def test_all_operating_states_keep_unknown_and_unavailable_truthful(
    state: str, expected: str
) -> None:
    now = datetime.now(UTC)
    data, manifest = feed(now, state)
    result = unit_projection(data, manifest, now)
    validate_contract("DirectoryView", result)
    facts = object_value(result["facts"])
    assert facts["operating_state"] == state
    assert facts["availability"] == expected
    assert facts["police_involvement"] == "unknown"
    assert "No reviewed alternative" in str(facts["qualifications"])
    assert result["state"] == "verified"


@pytest.mark.unit
@pytest.mark.parametrize("state", ["holiday_hours", "severe_weather"])
def test_event_hours_require_current_explicit_event_evidence(state: str) -> None:
    now = datetime.now(UTC)
    data, manifest = feed(now, state, event_verified=True)
    assert (
        object_value(unit_projection(data, manifest, now)["facts"])["availability"]
        == "available_fixture"
    )
    assert (
        object_value(unit_projection(data, manifest, now + timedelta(seconds=300))["facts"])[
            "availability"
        ]
        == "unknown"
    )


@pytest.mark.unit
def test_exact_source_admission_binding_and_no_source_authority_from_text() -> None:
    now = datetime.now(UTC)
    data, manifest = feed(now)
    assert admission_reason(data, {"b" * 64: manifest}, now) is None
    assert admission_reason(data, {}, now) == "artifact_not_admitted"
    object_value(data["facts"])["availability"] = "unavailable"
    assert admission_reason(data, {"b" * 64: manifest}, now) == "artifact_binding_mismatch"


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    ["source_owner", "source_revision", "future", "provenance", "stretched_ttl", "url", "dispute"],
)
def test_poisoned_or_unproven_sources_are_quarantined(mutation: str) -> None:
    now = datetime.now(UTC)
    data, manifest = feed(now)
    source = object_value(cast(list[object], data["sources"])[0])
    authority = object_value(cast(list[object], manifest["source_authorities"])[0])
    if mutation == "source_owner":
        authority["owner"] = None
    elif mutation == "source_revision":
        source["revision"] = "2"
    elif mutation == "future":
        source["observed_at"] = stamp(now + timedelta(minutes=1))
    elif mutation == "provenance":
        authority["field_classes"] = {"name": "structural"}
    elif mutation == "stretched_ttl":
        object_value(authority["field_classes"])["availability"] = "structural"
    elif mutation == "url":
        object_value(data["facts"])["hours_description"] = "https://untrusted.invalid/run"
    elif mutation == "dispute":
        source["verification"] = "disputed"
    manifest["payload_digest"] = digest(
        {key: data[key] for key in ("service_id", "facts", "sources")}
    )
    assert admission_reason(data, {"b" * 64: manifest}, now) is not None


@pytest.mark.unit
def test_stale_and_suspended_options_cannot_imply_available() -> None:
    now = datetime.now(UTC)
    data, manifest = feed(now)
    stale = unit_projection(data, manifest, now + timedelta(seconds=300))
    assert stale["state"] == "stale"
    assert object_value(stale["facts"])["availability"] == "unknown"
    assert "unknown" in str(object_value(stale["facts"])["hours_description"])
    suspended = unit_projection(data, manifest, now, suspended=True)
    assert suspended["state"] == "suspended"
    assert object_value(suspended["facts"])["availability"] == "unknown"


@pytest.fixture
def directory_harness(harness: Harness) -> Harness:
    h = harness
    with psycopg.connect(h.database.admin) as connection:
        if (
            connection.execute("SELECT to_regclass('knowledge.service_version')").fetchone()[0]
            is None
        ):
            connection.execute(
                (
                    Path(__file__).parents[1] / "migrations/003_plans_consent_directory.sql"
                ).read_text()
            )
        connection.execute(
            "TRUNCATE knowledge.service_guard,knowledge.service_version,"
            "knowledge.quarantine CASCADE"
        )
    return h


def admit(h: Harness, state: str = "normal_operations") -> tuple[Record, Record]:
    data, manifest = feed(datetime.now(UTC), state)
    h.service.directory_artifacts[str(data["feed_artifact_digest"])] = manifest
    return data, h.service.directory_ingest(h.operator, str(uuid4()), data)


def test_rejected_replacement_preserves_last_admitted_version(directory_harness: Harness) -> None:
    h = directory_harness
    data, initial = admit(h)
    replacement = {**data, "expected_revision": "1", "feed_artifact_digest": "c" * 64}
    rejected = h.service.directory_ingest(h.operator, str(uuid4()), replacement)
    assert rejected["state"] == "quarantined"
    current = h.service.directory_read(h.participant, str(data["service_id"]))
    assert current["revision"] == initial["revision"]
    assert current["state"] == "verified"
    assert h.read("SELECT count(*) FROM knowledge.service_version")[0][0] == 1
    assert h.read("SELECT reason FROM knowledge.quarantine")[0][0] == "artifact_not_admitted"


def test_missing_record_ingestion_race_serializes_and_versions_append(
    directory_harness: Harness,
) -> None:
    h = directory_harness
    data, manifest = feed(datetime.now(UTC))
    h.service.directory_artifacts[str(data["feed_artifact_digest"])] = manifest

    def create():
        try:
            return h.service.directory_ingest(h.operator, str(uuid4()), data)["revision"]
        except ManualError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert results.count("1") == 1
    assert (
        sum(value in {"manual.stale_revision", "manual.stale_authority"} for value in results) == 1
    )
    updated = {**data, "expected_revision": "1"}
    assert h.service.directory_ingest(h.operator, str(uuid4()), updated)["revision"] == "2"
    assert h.read("SELECT count(*) FROM knowledge.service_version")[0][0] == 2


def test_authoritative_suspension_is_journalled_and_cannot_be_relaxed_by_ingest(
    directory_harness: Harness,
) -> None:
    h = directory_harness
    data, initial = admit(h)
    security = replace(h.operator, account_id=str(uuid4()), role="security")
    from care_link_data import PostgresStore

    PostgresStore(h.database.admin).provision_principal(security)
    h.service.directory_suspend(
        security,
        str(uuid4()),
        {"expected_revision": initial["revision"], "reason": "security"},
        str(data["service_id"]),
    )
    assert h.journal.records[-1]["restriction"]["kind"] == "service_suspend"
    assert h.service.directory_read(h.participant, str(data["service_id"]))["state"] == "suspended"
    h.service.directory_ingest(h.operator, str(uuid4()), {**data, "expected_revision": "1"})
    assert h.service.directory_read(h.participant, str(data["service_id"]))["state"] == "suspended"


def test_participant_cannot_admit_sources_or_suspend_options(directory_harness: Harness) -> None:
    h = directory_harness
    data, _initial = admit(h)
    with pytest.raises(ManualError):
        h.service.directory_ingest(h.participant, str(uuid4()), {**data, "expected_revision": "1"})
    with pytest.raises(ManualError):
        h.service.directory_suspend(
            h.participant,
            str(uuid4()),
            {"expected_revision": "1", "reason": "security"},
            str(data["service_id"]),
        )


@pytest.mark.unit
def test_incomplete_source_scope_and_lost_admission_fail_closed() -> None:
    now = datetime.now(UTC)
    data, manifest = feed(now)
    manifest.pop("needs")
    assert admission_reason(data, {"b" * 64: manifest}, now) == "source_service_scope_missing"
    result = unit_projection(data, manifest, now)
    assert result["state"] == "quarantined"
    assert object_value(result["facts"])["availability"] == "unknown"


def test_failed_first_source_keeps_no_admitted_version(directory_harness: Harness) -> None:
    h = directory_harness
    data, _manifest = feed(datetime.now(UTC))
    result = h.service.directory_ingest(h.operator, str(uuid4()), data)
    assert result["state"] == "quarantined"
    assert result["revision"] == "0"
    assert h.read("SELECT count(*) FROM knowledge.service_guard")[0][0] == 0
    assert h.read("SELECT count(*) FROM knowledge.service_version")[0][0] == 0
    assert h.read("SELECT count(*) FROM knowledge.quarantine")[0][0] == 1
    with pytest.raises(ManualError):
        h.service.directory_read(h.participant, str(data["service_id"]))


def test_search_filters_need_and_cursor_is_bound_to_actor_query(directory_harness: Harness) -> None:
    h = directory_harness
    for _ in range(3):
        data, manifest = feed(datetime.now(UTC))
        manifest["needs"] = ["navigation"]
        h.service.directory_artifacts[str(data["feed_artifact_digest"])] = manifest
        # Each manifest has an exact artifact key; retain prior service bindings.
        artifact = digest(data)
        data["feed_artifact_digest"] = artifact
        h.service.directory_artifacts[artifact] = manifest
        h.service.directory_ingest(h.operator, str(uuid4()), data)
    query: Record = {"jurisdiction": "CA-XX", "locale": "en-CA", "need": "navigation", "limit": 1}
    first = h.service.directory_search(h.participant, str(uuid4()), query)
    assert len(first["items"]) == 1
    assert first["next_cursor"] is not None
    second = h.service.directory_search(
        h.participant, str(uuid4()), {**query, "cursor": first["next_cursor"]}
    )
    assert first["items"][0]["id"] != second["items"][0]["id"]
    with pytest.raises(ManualError):
        h.service.directory_search(
            h.worker, str(uuid4()), {**query, "cursor": first["next_cursor"]}
        )
    empty = h.service.directory_search(
        h.participant, str(uuid4()), {**query, "need": "carer_support"}
    )
    assert empty["items"] == []
