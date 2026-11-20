"""Actual admission/projection checks over newly generated fictional sources."""

import copy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_contracts import validate_contract
from care_link_data.directory_admission import VerifiedDirectoryAdmission
from care_link_domain import ManualError

from services.data.tests.test_directory import unit_projection
from tools.imp04_review.fixture_sources import create_fixture_sources


def test_new_cases_pass_signed_admission_and_actual_directory_projections():
    now = datetime(2026, 11, 20, tzinfo=UTC)
    sources = create_fixture_sources(str(uuid4()), now)
    admission = VerifiedDirectoryAdmission(sources.envelopes, {sources.key_id: sources.public_key})
    assert len(set(sources.service_ids.values())) == 4
    for case, feed in zip(sources.service_ids, sources.feeds, strict=True):
        manifest = admission.manifests[feed["feed_artifact_digest"]]
        view = unit_projection(feed, manifest, now, suspended=case == "suspended")
        validate_contract("DirectoryView", view)
        assert view["id"] == sources.service_ids[case]
        assert (
            view["state"]
            == {
                "current": "verified",
                "stale": "stale",
                "suspended": "suspended",
                "unknown": "verified",
            }[case]
        )
        assert (
            view["facts"]["availability"]
            == {
                "current": "available_fixture",
                "stale": "unknown",
                "suspended": "unavailable",
                "unknown": "unknown",
            }[case]
        )
    assert sources.provenance["prior_source_bytes_reused"] is False
    assert sources.provenance["human_review"] is False


def test_current_case_ages_naturally_after_300_seconds_without_refresh():
    now = datetime(2026, 11, 20, tzinfo=UTC)
    sources = create_fixture_sources(str(uuid4()), now)
    feed = sources.feeds[0]
    admission = VerifiedDirectoryAdmission(sources.envelopes, {sources.key_id: sources.public_key})
    view = unit_projection(
        feed, admission.manifests[feed["feed_artifact_digest"]], now + timedelta(seconds=300)
    )
    assert view["state"] == "stale"
    assert view["facts"]["availability"] == "unknown"
    assert feed["sources"][0]["observed_at"] == "2026-11-20T00:00:00Z"


def test_new_run_ids_and_signing_keys_cannot_adopt_prior_source_evidence():
    now = datetime(2026, 11, 20, tzinfo=UTC)
    first, second = (create_fixture_sources(str(uuid4()), now) for _ in range(2))
    assert set(first.service_ids.values()).isdisjoint(second.service_ids.values())
    assert first.key_id != second.key_id
    with pytest.raises(ManualError):
        VerifiedDirectoryAdmission(first.envelopes, {first.key_id: second.public_key})
    tampered = copy.deepcopy(first.envelopes)
    tampered[0]["human_review"] = True
    with pytest.raises(ManualError):
        VerifiedDirectoryAdmission(tampered, {first.key_id: first.public_key})
