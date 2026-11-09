"""Mechanical accepted-card conversion and explicitly local integrity publication."""

import argparse
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from care_link_static import PublicationStore
from care_link_static.publication import PublicationUnavailable, canonical

from tools.prepare_fallback_card import (
    ACCEPTANCE,
    DRAFTS,
    TRANSFORMATIONS,
    accepted_refs,
    prepare,
    publish_owner,
    write_new,
)


@pytest.mark.unit
def test_card_conversion_preserves_accepted_sources_and_separates_new_candidate(tmp_path: Path):
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [ACCEPTANCE, *DRAFTS.glob("*")]
        if path.is_file()
    }
    candidate, delta = prepare()
    assert candidate["review_status"] == "unsigned_final_candidate"
    assert candidate["participant_admission"] is False
    assert "review" not in candidate
    assert delta["accepted_sources"] == accepted_refs()
    assert delta["artifact_digest"] == candidate["artifact_digest"]
    texts = candidate["texts"]
    assert isinstance(texts, list)
    for text in texts:
        banner, provenance, retained = TRANSFORMATIONS[text["locale"]]
        assert banner not in text["text"] and provenance not in text["text"]
        assert retained in text["text"]
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before}
    output = tmp_path / "candidate.json"
    write_new(output, canonical(candidate))
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_new(output, canonical(candidate))


@pytest.mark.unit
def test_owner_helper_uses_explicit_actual_account_uuid_and_no_human_signature_claim(
    tmp_path: Path,
):
    candidate, _delta = prepare()
    candidate_path = tmp_path / "candidate.json"
    write_new(candidate_path, canonical(candidate))
    owner = str(uuid4())  # Synthetic test owner only, never an actual human review.
    now = datetime.now(UTC)
    arguments = argparse.Namespace(
        candidate=candidate_path,
        owner_account_id=owner,
        operation_id=str(uuid4()),
        integrity_private_key=tmp_path / "key.pem",
        directory=tmp_path / "publication",
        verified_at=now.isoformat().replace("+00:00", "Z"),
        review_due_at=(now + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        expected_current_digest=None,
    )
    result = publish_owner(arguments)
    assert result["review_profile"] == "owner_review_local_demo"
    assert result["human_signature_claim"] is False
    assert result["independent_review"] is False
    assert result["participant_admission"] is False
    assert arguments.integrity_private_key.stat().st_mode & 0o777 == 0o600
    from tools.prepare_fallback_card import owner_key

    key = owner_key(arguments.integrity_private_key)
    store = PublicationStore(arguments.directory, key.public_key(), allow_owner_demo=True)
    current = store.current()
    assert current.review.reviewer_id == current.review.operator_id == owner
    assert current.review.payload()["signature_purpose"] == "local_artifact_integrity"
    with pytest.raises(PublicationUnavailable):
        current.manifest("en-CA")
    assert publish_owner(arguments) == result
    arguments.owner_account_id = "main"
    with pytest.raises(ValueError):
        publish_owner(arguments)
