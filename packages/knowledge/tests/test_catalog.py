"""Behavioral retrieval and release-input checks, independent of patient data."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from care_link_knowledge import CatalogDenied, KnowledgeCatalog

NOW = datetime(2026, 11, 20, tzinfo=UTC)


def entry(**overrides):
    value = {
        "id": str(uuid4()),
        "revision": "1",
        "section_id": "handoff",
        "title": "Fictional handoff",
        "text": "Synthetic handoff preparation exercise.",
        "locale": "en-CA",
        "roles": ["worker"],
        "population": "synthetic-demo",
        "jurisdiction": "CA-ON",
        "status": "synthetic_demo",
        "effective_at": "2026-11-01T00:00:00Z",
        "review_until": "2027-01-01T00:00:00Z",
        "source_url": "https://example.org/reference",
        "source_title": "Background reference",
        "license": "Authored synthetic exercise",
        "keywords": ["handoff", "needs"],
    }
    return {**value, **overrides}


def catalog(*entries):
    return KnowledgeCatalog.from_bytes(
        json.dumps(
            {"schema_version": "care-link.knowledge.v1", "revision": "1", "entries": list(entries)}
        ).encode()
    )


def test_filters_role_locale_expiry_before_ranking_and_excludes_irrelevant():
    worker = entry()
    hidden = entry(section_id="private", roles=["receiver"], text="handoff " * 100)
    french = entry(section_id="french", locale="fr-CA", text="handoff " * 100)
    expired = entry(section_id="old", review_until="2026-11-19T00:00:00Z")
    data = catalog(worker, hidden, french, expired)
    found = data.search("worker", "en-CA", "handoff", now=NOW)
    assert [row["source"]["id"] for row in found] == [worker["id"]]
    assert data.search("worker", "en-CA", "unrelatedzzzz", now=NOW) == []
    assert data.search("pid", "en-CA", "handoff", now=NOW) == []
    with pytest.raises(CatalogDenied, match="scope_denied"):
        data.search("operator", "en-CA", "handoff", now=NOW)


def test_clinical_reference_only_is_restricted_to_professional_roles():
    with pytest.raises(CatalogDenied, match="clinical_reference_role_denied"):
        catalog(entry(status="reference_only", roles=["pid", "worker"]))
    data = catalog(entry(status="reference_only", roles=["worker", "professional_participant"]))
    assert len(data.search("worker", "en-CA", "handoff", now=NOW)) == 1
    assert data.search("carer", "en-CA", "handoff", now=NOW) == []


def test_source_digest_binds_metadata_and_text_and_retrieved_results_are_copies():
    original = entry()
    data = catalog(original)
    found = data.search("worker", "en-CA", "handoff", now=NOW)[0]
    source = found["source"]
    found["text"] = "mutated"
    assert data.search("worker", "en-CA", "handoff", now=NOW)[0]["text"] == original["text"]
    revised = catalog({**original, "source_title": "Updated reference"})
    assert revised.digest != data.digest
    assert revised.search("worker", "en-CA", "handoff", now=NOW)[0]["source"] != source
    assert data.sources_current("worker", "en-CA", [source], now=NOW)
    assert not data.sources_current("receiver", "en-CA", [source], now=NOW)
    assert not data.sources_current("worker", "en-CA", [source], now=NOW + timedelta(days=100))


@pytest.mark.parametrize(
    "change",
    [
        {"source_url": "file:///etc/passwd"},
        {"source_url": "https://secret@example.org"},
        {"status": "approved"},
        {"population": "real"},
        {"jurisdiction": "CA-US"},
        {"roles": ["worker", "worker"]},
        {"text": "a" * 2001},
        {"extra_authority": True},
        {"review_until": "2020-01-01T00:00:00Z"},
        {"effective_at": "2026-11-01T00:00:00+01:00"},
    ],
)
def test_unreviewed_metadata_and_invalid_scope_rejected(change):
    with pytest.raises(CatalogDenied):
        catalog(entry(**change))


def test_duplicate_keys_and_duplicate_identity_rejected():
    with pytest.raises(CatalogDenied):
        KnowledgeCatalog.from_bytes(b'{"revision":"1","revision":"2"}')
    one = entry()
    with pytest.raises(CatalogDenied):
        catalog(one, {**one, "section_id": "another"})


def test_resolving_pinned_sources_does_not_add_later_effective_high_ranked_entry():
    one = entry()
    future = entry(
        section_id="future",
        effective_at="2026-11-20T00:00:05Z",
        text="handoff needs future",
        keywords=["handoff", "needs", "future"],
    )
    data = catalog(one, future)
    first = data.search("worker", "en-CA", "handoff needs future", now=NOW)
    refs = [row["source"] for row in first]
    assert len(refs) == 1
    later = NOW + timedelta(seconds=6)
    assert len(data.search("worker", "en-CA", "handoff needs future", now=later)) == 2
    assert data.resolve_sources("worker", "en-CA", refs, now=later) == first
