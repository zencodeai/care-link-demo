"""Signed exact source admission rejects forgery, scope drift and mutable aliases."""

import base64
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from care_link_data.directory_admission import VerifiedDirectoryAdmission
from care_link_data.store import Record
from care_link_data.values import canonical, digest, object_value
from care_link_domain import ManualError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from services.data.tests.test_directory import feed


def envelope(key: Ed25519PrivateKey, manifest: Record) -> Record:
    body: Record = {
        "version": "care.directory.admission.v1",
        "artifact_digest": "b" * 64,
        "manifest_digest": digest(manifest),
        "manifest": manifest,
        "key_id": "test-source-authority",
        "tags": {"environment": "demo", "population": "synthetic"},
        "human_review": False,
        "participant_admission": False,
    }
    body["signature"] = (
        base64.urlsafe_b64encode(key.sign(canonical(body).encode())).rstrip(b"=").decode()
    )
    return body


@pytest.mark.unit
def test_exact_signed_metadata_binds_artifact_and_cannot_be_mutated_after_verification() -> None:
    private = Ed25519PrivateKey.generate()
    _data, manifest = feed(datetime.now(UTC))
    signed = envelope(private, manifest)
    registry = VerifiedDirectoryAdmission([signed], {"test-source-authority": private.public_key()})
    copied = registry.manifests
    object_value(copied["b" * 64])["admitted"] = False
    object_value(signed["manifest"])["admitted"] = False
    assert registry.manifest_for("b" * 64)["admitted"] is True
    assert registry.manifest_for("c" * 64) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "field",
    [
        "artifact_digest",
        "manifest_digest",
        "manifest",
        "tags",
        "human_review",
        "participant_admission",
    ],
)
def test_unsigned_changes_to_exact_admission_envelope_fail(field: str) -> None:
    private = Ed25519PrivateKey.generate()
    _data, manifest = feed(datetime.now(UTC))
    signed = envelope(private, manifest)
    if field in {"artifact_digest", "manifest_digest"}:
        signed[field] = "c" * 64
    elif field == "manifest":
        object_value(signed["manifest"])["service_id"] = "00000000-0000-4000-8000-000000000000"
    elif field == "tags":
        signed[field] = {"environment": "demo", "population": "real"}
    else:
        signed[field] = True
    with pytest.raises(ManualError):
        VerifiedDirectoryAdmission([signed], {"test-source-authority": private.public_key()})


@pytest.mark.unit
def test_missing_unknown_or_wrong_trusted_key_rejects_source() -> None:
    private = Ed25519PrivateKey.generate()
    _data, manifest = feed(datetime.now(UTC))
    signed = envelope(private, manifest)
    for keys in [
        {},
        {"other-authority": private.public_key()},
        {"test-source-authority": Ed25519PrivateKey.generate().public_key()},
    ]:
        with pytest.raises(ManualError):
            VerifiedDirectoryAdmission([signed], keys)
    unsigned = {key: value for key, value in signed.items() if key != "signature"}
    with pytest.raises(ManualError):
        VerifiedDirectoryAdmission([unsigned], {"test-source-authority": private.public_key()})


@pytest.mark.unit
@pytest.mark.parametrize(
    "defect",
    [
        "owner",
        "method",
        "tuple",
        "needs",
        "field_scope",
        "duplicate_source",
        "unknown_field",
        "manifest_hash",
    ],
)
def test_signed_but_incomplete_or_invalid_authority_scope_is_rejected(defect: str) -> None:
    private = Ed25519PrivateKey.generate()
    _data, manifest = feed(datetime.now(UTC))
    authority = object_value(cast(list[object], manifest["source_authorities"])[0])
    if defect in {"owner", "method"}:
        authority[defect] = " "
    elif defect == "tuple":
        authority["revision"] = "01"
    elif defect == "needs":
        manifest["needs"] = []
    elif defect == "field_scope":
        authority["field_classes"] = {"name": "structural"}
    elif defect == "duplicate_source":
        manifest["source_authorities"] = [authority, copy.deepcopy(authority)]
    elif defect == "unknown_field":
        manifest["executable_url"] = "https://untrusted.invalid"
    signed = envelope(private, manifest)
    if defect == "manifest_hash":
        signed["manifest_digest"] = "c" * 64
        body = {key: value for key, value in signed.items() if key != "signature"}
        signed["signature"] = (
            base64.urlsafe_b64encode(private.sign(canonical(body).encode())).rstrip(b"=").decode()
        )
    with pytest.raises(ManualError):
        VerifiedDirectoryAdmission([signed], {"test-source-authority": private.public_key()})


@pytest.mark.unit
def test_duplicate_signed_artifact_key_and_raw_unsigned_map_are_rejected() -> None:
    private = Ed25519PrivateKey.generate()
    _data, manifest = feed(datetime.now(UTC))
    signed = envelope(private, manifest)
    with pytest.raises(ManualError):
        VerifiedDirectoryAdmission(
            [signed, signed], {"test-source-authority": private.public_key()}
        )
    with pytest.raises(ManualError):
        VerifiedDirectoryAdmission(cast(list[Record], {"b" * 64: manifest}), {})


@pytest.mark.unit
def test_checked_in_candidates_verify_using_separate_public_key_pin() -> None:
    root = Path(__file__).parents[3] / "config/demo/imp04"
    bundle = json.loads((root / "directory-fixtures.json").read_text())
    pin = json.loads((root / "directory-source-key-pin.json").read_text())
    key_bytes = bytes.fromhex(pin["public_key_hex"])
    import hashlib

    assert hashlib.sha256(key_bytes).hexdigest() == pin["public_key_sha256"]
    registry = VerifiedDirectoryAdmission(
        bundle["signed_admissions"], {pin["key_id"]: Ed25519PublicKey.from_public_bytes(key_bytes)}
    )
    assert len(registry.manifests) == 7
    assert all(envelope["human_review"] is False for envelope in bundle["signed_admissions"])
    assert all(
        envelope["participant_admission"] is False for envelope in bundle["signed_admissions"]
    )
