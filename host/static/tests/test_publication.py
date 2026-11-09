"""Exact review, stale content, atomic CAS and escaped public rendering."""

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_static import Publication, PublicationStore, PublicText, Review, create_app
from care_link_static.publication import PublicationUnavailable, canonical
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

NOW = datetime(2026, 11, 8, tzinfo=UTC)


def reviewed(key: Ed25519PrivateKey, title: str = "Synthetic test") -> Publication:
    texts = (
        PublicText("en-CA", title, "<script>test</script>"),
        PublicText("fr-CA", "Essai fictif", "Texte public d’essai"),
    )
    review = Review(
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        "",
        NOW.isoformat().replace("+00:00", "Z"),
        (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "",
    )
    value = Publication(texts, review)
    review = replace(review, artifact_digest=value.artifact_digest)
    signature = base64.b64encode(key.sign(canonical(review.payload()))).decode()
    return replace(value, review=replace(review, signature=signature))


@pytest.mark.unit
def test_reviewed_publish_and_restart_render(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    publication = reviewed(key)
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    store.publish(publication, None, publication.review.operator_id, str(uuid4()))
    assert (tmp_path / "current.json").stat().st_mode & 0o777 == 0o600
    restarted = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    client = TestClient(create_app(restarted))
    page = client.get("/fallback")
    assert page.status_code == 200
    assert "&lt;script&gt;" in page.text and "<script>" not in page.text
    assert client.get("/static/v1/manifest").json()["digest"] == publication.artifact_digest
    assert client.post("/static-admin/v1/publications", json={}).status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize("change", ["bytes", "signature", "same_person", "operator", "expired"])
def test_invalid_publication_preserves_last_reviewed(tmp_path: Path, change: str) -> None:
    key = Ed25519PrivateKey.generate()
    value = reviewed(key)
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    store.publish(value, None, value.review.operator_id, str(uuid4()))
    bad = reviewed(key, "Candidate")
    operator = bad.review.operator_id
    if change == "bytes":
        bad = replace(bad, texts=(replace(bad.texts[0], text="Changed"), bad.texts[1]))
    elif change == "signature":
        bad = replace(bad, review=replace(bad.review, signature="AA=="))
    elif change == "same_person":
        bad = replace(bad, review=replace(bad.review, reviewer_id=bad.review.operator_id))
    elif change == "operator":
        operator = str(uuid4())
    else:
        store.clock = lambda: NOW + timedelta(days=2)
    with pytest.raises(PublicationUnavailable):
        store.publish(bad, value.artifact_digest, operator, str(uuid4()))
    store.clock = lambda: NOW
    assert store.current() == value


@pytest.mark.unit
def test_concurrent_publication_cas_and_unknown_fields(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    values = [reviewed(key, str(index)) for index in range(2)]

    def publish(value: Publication) -> bool:
        try:
            store.publish(value, None, value.review.operator_id, str(uuid4()))
            return True
        except PublicationUnavailable:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(publish, values)).count(True) == 1
    path = tmp_path / "current.json"
    path.write_text(path.read_text().replace('"texts":', '"unknown":true,"texts":'))
    assert TestClient(create_app(store)).get("/fallback").status_code == 503


@pytest.mark.unit
def test_static_missing_and_expired_review_remain_unavailable(tmp_path: Path) -> None:
    assert TestClient(create_app()).get("/fallback?locale=fr-CA").status_code == 503
    key = Ed25519PrivateKey.generate()
    value = reviewed(key)
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    store.publish(value, None, value.review.operator_id, str(uuid4()))
    store.clock = lambda: NOW + timedelta(days=2)
    assert TestClient(create_app(store)).get("/static/v1/manifest").status_code == 503


@pytest.mark.unit
def test_publication_lost_reply_retries_once_and_rejects_changed_key(tmp_path: Path) -> None:
    key = Ed25519PrivateKey.generate()
    value = reviewed(key)
    operation_id = str(uuid4())
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    store.publish(value, None, value.review.operator_id, operation_id)
    before = (tmp_path / "current.json").read_bytes()
    restarted = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    assert restarted.publish(value, None, value.review.operator_id, operation_id) == value
    assert (tmp_path / "current.json").read_bytes() == before
    changed = reviewed(key, "Changed candidate")
    with pytest.raises(PublicationUnavailable):
        restarted.publish(changed, None, value.review.operator_id, operation_id)
    with pytest.raises(PublicationUnavailable):
        restarted.publish(value, None, str(uuid4()), operation_id)
    assert restarted.current() == value


@pytest.mark.unit
def test_static_admin_requires_non_browser_channel_and_operation_key(tmp_path: Path) -> None:
    from care_link_static.app import Publisher, create_admin_app

    key = Ed25519PrivateKey.generate()
    value = reviewed(key)
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    publisher = Publisher(value.review.operator_id, "operator", True, "authenticated_admin_channel")
    app = create_admin_app(store, lambda _request: publisher, lambda _digest, _receipt: value)
    client = TestClient(app)
    body = {
        "artifact_digest": value.artifact_digest,
        "independent_review_receipt_id": value.review.receipt_id,
        "expected_current_digest": None,
    }
    assert client.post("/static-admin/v1/publications", json=body).status_code == 400
    headers = {"Idempotency-Key": str(uuid4())}
    assert (
        client.post(
            "/static-admin/v1/publications",
            json=body,
            headers=headers | {"Origin": "https://browser.test"},
        ).status_code
        == 403
    )
    result = client.post("/static-admin/v1/publications", json=body, headers=headers)
    assert result.status_code == 200
    assert (
        client.post("/static-admin/v1/publications", json=body, headers=headers).json()
        == result.json()
    )


@pytest.mark.unit
@pytest.mark.parametrize("corruption", ["uuid", "date", "duplicate"])
def test_corrupted_review_shows_visible_unavailable(tmp_path: Path, corruption: str) -> None:
    key = Ed25519PrivateKey.generate()
    value = reviewed(key)
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    store.publish(value, None, value.review.operator_id, str(uuid4()))
    path = tmp_path / "current.json"
    raw = path.read_text()
    if corruption == "uuid":
        raw = raw.replace(value.review.receipt_id, "malformed")
    elif corruption == "date":
        raw = raw.replace(value.review.review_due_at, "malformedZ")
    else:
        raw = raw.replace('"texts":', '"texts":[],"texts":')
    path.write_text(raw)
    assert TestClient(create_app(store)).get("/fallback").status_code == 503
