"""Explicit same-owner profile, downgrade resistance and safe semantic presentation."""

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_static import Publication, PublicationStore, PublicText, Review, create_app
from care_link_static.app import Publisher, create_admin_app
from care_link_static.publication import PublicationUnavailable, canonical, decode
from care_link_static.rendering import CONTENT_SECURITY_POLICY, STYLES, page, safe_link
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def owner_publication(key: Ed25519PrivateKey) -> Publication:
    owner = str(uuid4())
    review = Review(
        str(uuid4()),
        owner,
        owner,
        "",
        "2026-11-09T00:00:00Z",
        "2026-12-09T00:00:00Z",
        "",
        "owner_review_local_demo",
    )
    result = Publication(
        (
            PublicText("en-CA", "Public test", "## Heading\n\nTest."),
            PublicText("fr-CA", "Essai public", "## Titre\n\nEssai."),
        ),
        review,
    )
    review = replace(review, artifact_digest=result.artifact_digest)
    signature = base64.b64encode(key.sign(canonical(review.payload()))).decode()
    return replace(result, review=replace(review, signature=signature))


@pytest.mark.unit
def test_owner_review_requires_both_explicit_flags_and_never_uses_independent_manifest(
    tmp_path: Path,
):
    key = Ed25519PrivateKey.generate()
    value = owner_publication(key)
    with pytest.raises(PublicationUnavailable):
        value.verify(key.public_key(), NOW)
    default = PublicationStore(tmp_path, key.public_key(), lambda: NOW)
    with pytest.raises(PublicationUnavailable):
        default.publish(value, None, value.review.operator_id, str(uuid4()))
    enabled = PublicationStore(tmp_path, key.public_key(), lambda: NOW, allow_owner_demo=True)
    enabled.publish(value, None, value.review.operator_id, str(uuid4()))
    assert TestClient(create_app(enabled)).get("/fallback").status_code == 503
    client = TestClient(create_app(enabled, allow_owner_demo=True))
    rendered = client.get("/fallback")
    assert rendered.status_code == 200
    assert "Independent review is not established" in rendered.text
    assert "Participant admission is disabled" in rendered.text
    assert client.get("/static/v1/manifest").status_code == 503
    manifest = client.get("/demo-static/v1/manifest").json()
    assert manifest["review_profile"] == "owner_review_local_demo"
    assert manifest["participant_admission"] is False
    assert manifest["independent_review"] is False
    assert "owner_review_digest" in manifest and "independent_review_digest" not in manifest
    assert decode(canonical(value.wire()).decode()) == value
    with pytest.raises(PublicationUnavailable):
        default.current()


@pytest.mark.unit
@pytest.mark.parametrize(
    "attack",
    [
        "drop_profile",
        "independent_format",
        "grant_admission",
        "claim_independent",
        "invalid_profile",
        "different_operator",
    ],
)
def test_owner_profile_cannot_be_downgraded_or_expanded(attack: str):
    key = Ed25519PrivateKey.generate()
    value = owner_publication(key)
    wire = value.wire()
    review = wire["review"]
    assert isinstance(review, dict)
    if attack == "drop_profile":
        del review["review_profile"]
    elif attack == "independent_format":
        for field in (
            "review_profile",
            "participant_admission",
            "independent_review",
            "signature_purpose",
        ):
            del review[field]
        review["format_version"] = "public-text-1"
    elif attack == "grant_admission":
        review["participant_admission"] = True
    elif attack == "claim_independent":
        review["independent_review"] = True
    elif attack == "invalid_profile":
        review["review_profile"] = "unknown"
    else:
        review["operator_id"] = str(uuid4())
    with pytest.raises(PublicationUnavailable):
        decode(json.dumps(wire)).verify(key.public_key(), NOW, allow_owner_demo=True)


@pytest.mark.unit
def test_independent_signature_payload_remains_unchanged():
    value = Review(
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        "a" * 64,
        "2026-11-09T00:00:00Z",
        "2026-11-10T00:00:00Z",
        "",
    )
    assert value.payload() == {
        "format_version": "public-text-1",
        "receipt_id": value.receipt_id,
        "reviewer_id": value.reviewer_id,
        "operator_id": value.operator_id,
        "artifact_digest": value.artifact_digest,
        "verified_at": value.verified_at,
        "review_due_at": value.review_due_at,
        "public_only": True,
        "locales": ["en-CA", "fr-CA"],
    }


@pytest.mark.unit
def test_owner_admin_requires_explicit_route_and_actual_selected_profile(tmp_path: Path):
    key = Ed25519PrivateKey.generate()
    value = owner_publication(key)
    store = PublicationStore(tmp_path, key.public_key(), lambda: NOW, allow_owner_demo=True)
    publisher = Publisher(value.review.operator_id, "operator", True, "authenticated_admin_channel")
    client = TestClient(
        create_admin_app(
            store,
            lambda _request: publisher,
            lambda _digest, _receipt: value,
            allow_owner_demo=True,
        )
    )
    body = {
        "artifact_digest": value.artifact_digest,
        "owner_review_receipt_id": value.review.receipt_id,
        "expected_current_digest": None,
    }
    header = {"Idempotency-Key": str(uuid4())}
    assert client.post("/demo-static-admin/v1/publications", json=body).status_code == 400
    assert (
        client.post(
            "/demo-static-admin/v1/publications",
            json=body,
            headers=header | {"Origin": "https://browser.test"},
        ).status_code
        == 403
    )
    independent = dict(body)
    independent["independent_review_receipt_id"] = independent.pop("owner_review_receipt_id")
    assert (
        client.post("/static-admin/v1/publications", json=independent, headers=header).status_code
        == 409
    )
    result = client.post("/demo-static-admin/v1/publications", json=body, headers=header)
    assert result.status_code == 200
    assert "independent_review_digest" not in result.json()
    assert result.json()["participant_admission"] is False


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "a":
            self.hrefs.extend(
                value for name, value in attrs if name == "href" and value is not None
            )


@pytest.mark.unit
def test_semantic_rendering_escapes_html_and_allows_only_explicit_public_link_schemes():
    raw = (
        "## Support\n\n<script>never()</script>\n\n"
        "- **Call** [988](tel:988?oai_link_source=model_response_hotline)\n"
        "- [Public site](https://example.test/support)\n"
        "- [unsafe](javascript:alert)\n- [unsafe](//example.test)\n"
        "- [unsafe](https://user:secret@example.test/)\n- [unsafe](sms:988?body=private)"
    )
    rendered = page(PublicText("en-CA", "Escaped <title>", raw))
    assert (
        "<h2>Support</h2>" in rendered
        and "<ul>" in rendered
        and "<strong>Call</strong>" in rendered
    )
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered
    assert 'name="viewport"' in rendered and "overflow-wrap:anywhere" in rendered
    parser = Links()
    parser.feed(rendered)
    assert parser.hrefs == [
        "tel:988?oai_link_source=model_response_hotline",
        "https://example.test/support",
    ]
    assert all(safe_link(value) for value in parser.hrefs)
    style_hash = base64.b64encode(hashlib.sha256(STYLES.encode()).digest()).decode()
    assert f"'sha256-{style_hash}'" in CONTENT_SECURITY_POLICY
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY


@pytest.mark.unit
def test_owner_review_cadence_cannot_extend_beyond_approved_thirty_days():
    key = Ed25519PrivateKey.generate()
    value = owner_publication(key)
    overdue = replace(value, review=replace(value.review, review_due_at="2026-12-10T00:00:00Z"))
    with pytest.raises(PublicationUnavailable):
        overdue.verify(key.public_key(), NOW, allow_owner_demo=True)
    with pytest.raises(PublicationUnavailable):
        value.verify(key.public_key(), NOW + timedelta(days=31), allow_owner_demo=True)
