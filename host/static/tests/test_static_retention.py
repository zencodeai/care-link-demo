"""Durable Option B publication custody, bounded cleanup and honest unresolved dependencies."""

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_static import Publication, PublicationStore, PublicText, Review, create_app
from care_link_static.publication import PublicationUnavailable, canonical, digest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def stamp(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def reviewed(key: Ed25519PrivateKey, at: datetime, title: str) -> Publication:
    review = Review(
        str(uuid4()), str(uuid4()), str(uuid4()), "", stamp(at), stamp(at + timedelta(days=30)), ""
    )
    value = Publication(
        (PublicText("en-CA", title, "Public fixture"), PublicText("fr-CA", title, "Essai public")),
        review,
    )
    review = replace(review, artifact_digest=value.artifact_digest)
    return replace(
        value,
        review=replace(
            review, signature=base64.b64encode(key.sign(canonical(review.payload()))).decode()
        ),
    )


def seed_replacement(tmp_path: Path):
    key = Ed25519PrivateKey.generate()
    clock = [NOW]
    store = PublicationStore(tmp_path, key.public_key(), lambda: clock[0])
    first, first_operation = reviewed(key, NOW, "First"), str(uuid4())
    store.publish(first, None, first.review.operator_id, first_operation)
    clock[0] += timedelta(days=1)
    second, second_operation = reviewed(key, clock[0], "Second"), str(uuid4())
    store.publish(second, first.artifact_digest, second.review.operator_id, second_operation)
    return store, clock, first, second, first_operation, second_operation


@pytest.mark.unit
def test_replacement_archives_exact_receipt_and_waits_for_evidenced_end_plus_ninety(tmp_path: Path):
    store, clock, first, second, first_operation, second_operation = seed_replacement(tmp_path)
    reference = digest(first.review.payload())
    path = tmp_path / "current.json"
    record = json.loads(path.read_text())
    assert record["archives"][reference]["publication"] == first.wire()
    assert record["archives"][reference]["dependency_ended_at"] is None
    clock[0] = NOW + timedelta(days=200)
    assert store.cleanup_retention()["removed_archive_count"] == 0
    # No receipt expiry or elapsed time invents the end of a recovery dependency.
    clock[0] = NOW + timedelta(days=5)
    store.end_review_dependency(reference, ended_at=stamp(clock[0]), evidence_digest="a" * 64)
    clock[0] = NOW + timedelta(days=94)
    assert store.cleanup_retention()["removed_archive_count"] == 0
    clock[0] = NOW + timedelta(days=95)
    result = store.cleanup_retention()
    assert result["removed_archive_count"] == result["removed_operation_count"] == 1
    current = json.loads(path.read_text())
    assert reference not in current["archives"]
    assert first_operation not in current["operations"]
    assert second_operation in current["operations"]
    assert current["publication"] == second.wire()
    assert first.review.operator_id not in path.read_text()
    before = path.read_bytes()
    with pytest.raises(PublicationUnavailable):
        store.publish(first, second.artifact_digest, first.review.operator_id, first_operation)
    assert path.read_bytes() == before  # Expired removed operation cannot republish old bytes.


@pytest.mark.unit
def test_expired_current_is_unavailable_and_requires_explicit_owner_dependency_decision(
    tmp_path: Path,
):
    key = Ed25519PrivateKey.generate()
    clock = [NOW]
    store = PublicationStore(tmp_path, key.public_key(), lambda: clock[0])
    value, operation = reviewed(key, NOW, "Current"), str(uuid4())
    store.publish(value, None, value.review.operator_id, operation)
    clock[0] = NOW + timedelta(days=120)
    status = store.cleanup_retention()
    assert status["status"] == "dependency_review_required"
    assert status["current_review_expired"] is True
    assert status["current_dependency_requires_custodian_decision"] is True
    assert status["custodian"] == "main"
    assert TestClient(create_app(store)).get("/fallback").status_code == 503
    reference = digest(value.review.payload())
    store.retire_current(reference, ended_at=stamp(clock[0]), evidence_digest="b" * 64)
    clock[0] += timedelta(days=89)
    assert store.cleanup_retention()["removed_operation_count"] == 0
    clock[0] += timedelta(days=1)
    status = store.cleanup_retention()
    assert status["removed_archive_count"] == status["removed_operation_count"] == 1
    assert value.review.operator_id not in (tmp_path / "current.json").read_text()
    assert TestClient(create_app(store)).get("/fallback").status_code == 503


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["review", "operation"])
def test_holds_keep_exact_dependency_and_flag_overdue_without_automatic_release(
    tmp_path: Path, kind: str
):
    store, clock, first, _second, operation, _other_operation = seed_replacement(tmp_path)
    review_digest = digest(first.review.payload())
    reference = review_digest if kind == "review" else operation
    store.end_review_dependency(review_digest, ended_at=stamp(clock[0]), evidence_digest="c" * 64)
    store.set_retention_hold(
        kind,
        reference,
        reason="Known recovery-copy obligation",
        review_date=stamp(NOW + timedelta(days=2)),
    )
    clock[0] = NOW + timedelta(days=100)
    result = store.cleanup_retention()
    assert result["removed_archive_count"] == result["removed_operation_count"] == 0
    assert result["status"] == "hold_review_required"
    assert result["overdue_holds"] == [
        {
            "kind": kind,
            "reference": reference,
            "owner": "main",
            "review_date": stamp(NOW + timedelta(days=2)),
            "review_required": True,
        }
    ]
    with pytest.raises(PublicationUnavailable):
        store.release_retention_hold(kind, reference, evidence_digest="d" * 64, custodian="other")
    with pytest.raises(PublicationUnavailable):
        store.release_retention_hold(kind, reference, evidence_digest="missing")
    store.release_retention_hold(kind, reference, evidence_digest="d" * 64)
    assert store.cleanup_retention()["removed_archive_count"] == 1


@pytest.mark.unit
def test_cleanup_failure_is_atomic_and_timestamp_metadata_does_not_refresh_retry(
    tmp_path: Path, monkeypatch
):
    store, clock, first, _second, first_operation, _other_operation = seed_replacement(tmp_path)
    reference = digest(first.review.payload())
    store.end_review_dependency(reference, ended_at=stamp(clock[0]), evidence_digest="e" * 64)
    path = tmp_path / "current.json"
    before = path.read_bytes()
    clock[0] = NOW + timedelta(days=2)
    # Stable binding returns the current valid publication without renewing event_at.
    store.publish(first, None, first.review.operator_id, first_operation)
    assert path.read_bytes() == before
    clock[0] = NOW + timedelta(days=100)

    def failed_replace(_source, _destination):
        raise OSError("Synthetic atomic replacement failure")

    monkeypatch.setattr("care_link_static.publication.os.replace", failed_replace)
    with pytest.raises(OSError):
        store.cleanup_retention()
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".publication-*"))


@pytest.mark.unit
def test_legacy_or_missing_anchors_stays_migration_pending_without_invented_times(tmp_path: Path):
    key = Ed25519PrivateKey.generate()
    value = reviewed(key, NOW, "Legacy")
    path = tmp_path / "current.json"
    legacy = {
        "publication": value.wire(),
        "operations": {
            str(uuid4()): {"operator_id": value.review.operator_id, "body_digest": "f" * 64}
        },
    }
    path.write_bytes(canonical(legacy))
    before = path.read_bytes()
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    with pytest.raises(PublicationUnavailable, match="migration_pending"):
        store.current()
    with pytest.raises(PublicationUnavailable, match="migration_pending"):
        store.cleanup_retention()
    assert path.read_bytes() == before
    assert "event_at" not in path.read_text()


@pytest.mark.unit
def test_dependency_end_cannot_predate_last_actual_serving_or_shorten_ninety_day_window(
    tmp_path: Path,
):
    store, clock, first, _second, _operation, _other_operation = seed_replacement(tmp_path)
    reference = digest(first.review.payload())
    path = tmp_path / "current.json"
    before = path.read_bytes()
    with pytest.raises(PublicationUnavailable, match="serving boundary"):
        store.end_review_dependency(reference, ended_at=stamp(NOW), evidence_digest="a" * 64)
    assert path.read_bytes() == before
    store.end_review_dependency(reference, ended_at=stamp(clock[0]), evidence_digest="a" * 64)
    clock[0] = NOW + timedelta(days=90)
    assert store.cleanup_retention()["removed_archive_count"] == 0
    clock[0] += timedelta(days=1)
    assert store.cleanup_retention()["removed_archive_count"] == 1


@pytest.mark.unit
def test_expired_serving_boundary_may_use_exact_signed_due_date_with_explicit_final_evidence(
    tmp_path: Path,
):
    key = Ed25519PrivateKey.generate()
    clock = [NOW]
    store = PublicationStore(tmp_path, key.public_key(), lambda: clock[0])
    value = reviewed(key, NOW, "Expiring")
    store.publish(value, None, value.review.operator_id, str(uuid4()))
    clock[0] = NOW + timedelta(days=120)
    reference = digest(value.review.payload())
    store.retire_current(reference, ended_at=value.review.review_due_at, evidence_digest="b" * 64)
    assert store.cleanup_retention()["removed_archive_count"] == 1


@pytest.mark.unit
def test_signed_microsecond_publication_anchor_survives_read_retry_and_restart(tmp_path: Path):
    key = Ed25519PrivateKey.generate()
    instant = NOW.replace(microsecond=123456)
    value = reviewed(key, instant, "Precise review")
    operation = str(uuid4())
    store = PublicationStore(tmp_path, key.public_key(), lambda: instant)
    store.publish(value, None, value.review.operator_id, operation)
    before = (tmp_path / "current.json").read_bytes()
    assert json.loads(before)["current"]["published_at"] == stamp(instant)
    assert store.current() == value
    assert store.publish(value, None, value.review.operator_id, operation) == value
    restarted = PublicationStore(tmp_path, key.public_key(), lambda: instant)
    assert restarted.current() == value
    assert restarted.publish(value, None, value.review.operator_id, operation) == value
    assert (tmp_path / "current.json").read_bytes() == before
