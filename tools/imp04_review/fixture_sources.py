"""New fictional directory cases, with fresh provenance and ordinary admission."""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from care_link_contracts import validate_contract
from care_link_data.directory import FIELD_CLASSES, admission_reason
from care_link_data.directory_admission import VerifiedDirectoryAdmission
from care_link_data.values import canonical, digest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .types import JsonRecord


@dataclass(frozen=True)
class FreshDirectorySources:
    service_ids: dict[str, str]
    feeds: tuple[JsonRecord, ...]
    envelopes: tuple[JsonRecord, ...]
    key_id: str
    public_key: Ed25519PublicKey
    provenance: JsonRecord


def create_fixture_sources(run_id: str, created_at: datetime) -> FreshDirectorySources:
    """Create new IDs/evidence, never rewrite or re-date an existing source."""
    namespace = UUID(run_id)
    if str(namespace) != run_id or created_at.tzinfo != UTC:
        raise ValueError("Canonical run UUID and actual UTC activation time required")
    generated = created_at.isoformat().replace("+00:00", "Z")
    key = Ed25519PrivateKey.generate()
    key_id = "review-source-" + namespace.hex
    services: dict[str, str] = {}
    feeds: list[JsonRecord] = []
    envelopes: list[JsonRecord] = []
    for case in ("current", "stale", "suspended", "unknown"):
        service_id = str(uuid5(namespace, "directory-service:" + case))
        services[case] = service_id
        observed = created_at - timedelta(seconds=301) if case == "stale" else created_at
        operating = {
            "current": "normal_operations",
            "stale": "normal_operations",
            "suspended": "temporary_closure",
            "unknown": "api_failure",
        }[case]
        facts: JsonRecord = {
            "name": "New fictional review option / Nouvelle option fictive: " + case,
            "jurisdictions": ["CA-XX"],
            "languages": ["en-CA", "fr-CA"],
            "age_scope": "all_fixture",
            "availability": "available_fixture",
            "police_involvement": "unknown",
            "alternative_service_id": None,
            "hours_description": "Fictional daytime hours / Horaire fictif de jour",
            "operating_state": operating,
            "qualifications": [
                "New synthetic engineering scenario, not a real service. / "
                "Nouveau scénario technique fictif, pas un service réel.",
                "Created / Créé: " + generated,
                "The stale case depicts an observation 301 seconds earlier. / "
                "Le cas périmé représente une observation antérieure de 301 secondes.",
            ],
        }
        source: JsonRecord = {
            "kind": "directory",
            "id": str(uuid5(namespace, "directory-source:" + case)),
            "revision": "1",
            "digest": digest({"run_id": run_id, "case": case, "created_at": generated}),
            "observed_at": observed.isoformat().replace("+00:00", "Z"),
            "verification": "verified",
        }
        payload: JsonRecord = {"service_id": service_id, "facts": facts, "sources": [source]}
        artifact = digest(payload)
        feed = {"expected_revision": "0", **payload, "feed_artifact_digest": artifact}
        validate_contract("DirectoryIngest", feed)
        manifest: JsonRecord = {
            "admitted": True,
            "service_id": service_id,
            "payload_digest": artifact,
            "needs": ["client_support", "carer_support", "navigation", "interpretation"],
            "source_authorities": [
                {
                    "id": source["id"],
                    "revision": "1",
                    "digest": source["digest"],
                    "owner": "synthetic-review-operator",
                    "method": "new-fictional-review-case:" + generated,
                    "field_classes": dict(FIELD_CLASSES),
                    "event_verified": False,
                }
            ],
        }
        body: JsonRecord = {
            "version": "care.directory.admission.v1",
            "artifact_digest": artifact,
            "manifest_digest": digest(manifest),
            "manifest": manifest,
            "key_id": key_id,
            "tags": {"environment": "demo", "population": "synthetic"},
            "human_review": False,
            "participant_admission": False,
        }
        body["signature"] = (
            base64.urlsafe_b64encode(key.sign(canonical(body).encode())).rstrip(b"=").decode()
        )
        feeds.append(feed)
        envelopes.append(body)
    admission = VerifiedDirectoryAdmission(envelopes, {key_id: key.public_key()})
    for feed in feeds:
        if admission_reason(feed, admission.manifests, created_at) is not None:
            raise ValueError("Fresh fictional directory evidence was not admitted")
    return FreshDirectorySources(
        services,
        tuple(feeds),
        tuple(envelopes),
        key_id,
        key.public_key(),
        {
            "kind": "new_synthetic_review_fixture_set",
            "run_id": run_id,
            "created_at": generated,
            "prior_source_bytes_reused": False,
            "human_review": False,
            "participant_admission": False,
            "stale_case": (
                "New fictional observation deliberately depicts age 301 seconds at creation"
            ),
        },
    )
