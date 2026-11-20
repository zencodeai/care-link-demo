"""Cryptographic admission of exact synthetic directory source manifests.

The trusted public-key ring is supplied independently of source bytes. A signed
engineering fixture establishes only the scoped source binding, never human
review, participant admission, clinical validity or an executable destination.
"""

import base64
import binascii
import copy
import re
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID

from care_link_domain import ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .store import Record
from .values import canonical, digest, integer, object_value

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = {
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
_TTL = {"structural": 720 * 3600, "operational": 24 * 3600, "near_realtime": 300}
_NEEDS = frozenset({"client_support", "carer_support", "navigation", "interpretation"})
_ENVELOPE_KEYS = frozenset(
    {
        "version",
        "artifact_digest",
        "manifest_digest",
        "manifest",
        "key_id",
        "tags",
        "human_review",
        "participant_admission",
        "signature",
    }
)
_MANIFEST_KEYS = frozenset(
    {"admitted", "service_id", "payload_digest", "needs", "source_authorities"}
)
_AUTHORITY_KEYS = frozenset(
    {"id", "revision", "digest", "owner", "method", "field_classes", "event_verified"}
)


def _fail() -> ManualError:
    return ManualError("manual.directory_admission_invalid", 503)


def _uuid(value: object) -> None:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise _fail()


def _hash(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise _fail()
    return value


def _label(value: object, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise _fail()
    return value


def _manifest(value: object) -> Record:
    manifest = object_value(value)
    if set(manifest) != set(_MANIFEST_KEYS) or manifest["admitted"] is not True:
        raise _fail()
    _uuid(manifest["service_id"])
    _hash(manifest["payload_digest"])
    needs = manifest["needs"]
    if not isinstance(needs, list) or not 1 <= len(cast(list[object], needs)) <= 4:
        raise _fail()
    need_values = cast(list[object], needs)
    if not all(isinstance(need, str) and need in _NEEDS for need in need_values) or len(
        set(cast(list[str], needs))
    ) != len(need_values):
        raise _fail()
    authorities = manifest["source_authorities"]
    if not isinstance(authorities, list) or not 1 <= len(cast(list[object], authorities)) <= 32:
        raise _fail()
    seen: set[str] = set()
    coverage: set[str] = set()
    for raw in cast(list[object], authorities):
        authority = object_value(raw)
        if set(authority) != set(_AUTHORITY_KEYS):
            raise _fail()
        _uuid(authority["id"])
        source_id = cast(str, authority["id"])
        if source_id in seen:
            raise _fail()
        seen.add(source_id)
        revision = authority["revision"]
        if not isinstance(revision, str):
            raise _fail()
        integer(revision)
        _hash(authority["digest"])
        _label(authority["owner"])
        _label(authority["method"])
        if not isinstance(authority["event_verified"], bool):
            raise _fail()
        classes = object_value(authority["field_classes"])
        if not classes:
            raise _fail()
        for field, category in classes.items():
            if (
                field not in _FIELDS
                or not isinstance(category, str)
                or category not in _TTL
                or _TTL[category] > _TTL[_FIELDS[field]]
            ):
                raise _fail()
            coverage.add(field)
    if coverage != set(_FIELDS):
        raise _fail()
    return manifest


class VerifiedDirectoryAdmission:
    """Validated, detached directory source registry for a composition root."""

    def __init__(
        self, envelopes: Sequence[Record], trusted_keys: Mapping[str, Ed25519PublicKey]
    ) -> None:
        if len(envelopes) > 1000:
            raise _fail()
        self._manifests: dict[str, Record] = {}
        for source in envelopes:
            try:
                # A roundtrip copy prevents caller mutations after validation.
                envelope = copy.deepcopy(source)
                if set(envelope) != set(_ENVELOPE_KEYS):
                    raise _fail()
                if (
                    envelope["version"] != "care.directory.admission.v1"
                    or envelope["tags"] != {"environment": "demo", "population": "synthetic"}
                    or envelope["human_review"] is not False
                    or envelope["participant_admission"] is not False
                ):
                    raise _fail()
                artifact = _hash(envelope["artifact_digest"])
                key_id = _label(envelope["key_id"], 64)
                public_key = trusted_keys.get(key_id)
                if not isinstance(public_key, Ed25519PublicKey):
                    raise _fail()
                signature = _label(envelope["signature"], 128)
                if re.fullmatch(r"[A-Za-z0-9_-]{86}", signature) is None:
                    raise _fail()
                decoded = base64.urlsafe_b64decode(signature + "==")
                if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode() != signature:
                    raise _fail()
                body = {key: value for key, value in envelope.items() if key != "signature"}
                encoded = canonical(body).encode()
                if len(encoded) > 65536:
                    raise _fail()
                public_key.verify(decoded, encoded)
                manifest = _manifest(envelope["manifest"])
                if _hash(envelope["manifest_digest"]) != digest(manifest):
                    raise _fail()
                if artifact in self._manifests:
                    raise _fail()
                self._manifests[artifact] = manifest
            except (InvalidSignature, binascii.Error, ValueError, KeyError, TypeError) as error:
                raise _fail() from error

    @property
    def manifests(self) -> dict[str, Record]:
        """Return a detached copy; validation cannot be invalidated by a caller."""
        return copy.deepcopy(self._manifests)

    def manifest_for(self, artifact_digest: str) -> Record | None:
        value = self._manifests.get(artifact_digest)
        return copy.deepcopy(value) if value is not None else None
