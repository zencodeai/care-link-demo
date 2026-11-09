"""Offline reviewed public text publication; no identity or core dependency."""

import base64
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import cast
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import retention


class PublicationUnavailable(ValueError):
    """No currently valid exact independently reviewed public bundle."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def instant(value: str) -> datetime:
    if not value.endswith("Z"):
        raise PublicationUnavailable("UTC required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class PublicText:
    locale: str
    title: str
    text: str

    def __post_init__(self) -> None:
        if self.locale not in {"en-CA", "fr-CA"}:
            raise PublicationUnavailable("Unsupported locale")
        if not (1 <= len(self.title) <= 200 and 1 <= len(self.text) <= 16000):
            raise PublicationUnavailable("Invalid public text")

    def wire(self) -> dict[str, str]:
        return {"locale": self.locale, "title": self.title, "text": self.text}


@dataclass(frozen=True)
class Review:
    receipt_id: str
    reviewer_id: str
    operator_id: str
    artifact_digest: str
    verified_at: str
    review_due_at: str
    signature: str
    profile: str = "independent"

    def payload(self) -> dict[str, object]:
        if self.profile not in {"independent", "owner_review_local_demo"}:
            raise PublicationUnavailable("Unknown review profile")
        payload: dict[str, object] = {
            "format_version": "public-text-1",
            "receipt_id": self.receipt_id,
            "reviewer_id": self.reviewer_id,
            "operator_id": self.operator_id,
            "artifact_digest": self.artifact_digest,
            "verified_at": self.verified_at,
            "review_due_at": self.review_due_at,
            "public_only": True,
            "locales": ["en-CA", "fr-CA"],
        }
        if self.profile == "owner_review_local_demo":
            payload.update(
                {
                    "format_version": "public-text-owner-demo-1",
                    "review_profile": self.profile,
                    "participant_admission": False,
                    "independent_review": False,
                    "signature_purpose": "local_artifact_integrity",
                }
            )
        # The independent profile deliberately retains its original exact signed
        # payload. The new owner profile is explicit and cannot downgrade into it.
        return payload


@dataclass(frozen=True)
class Publication:
    texts: tuple[PublicText, PublicText]
    review: Review

    @property
    def artifact_digest(self) -> str:
        return digest([text.wire() for text in self.texts])

    def verify(
        self, key: Ed25519PublicKey, now: datetime, *, allow_owner_demo: bool = False
    ) -> None:
        try:
            self._verify(key, now, allow_owner_demo=allow_owner_demo)
        except (ValueError, TypeError, AttributeError) as error:
            raise PublicationUnavailable("Invalid or unavailable reviewed publication") from error

    def _verify(self, key: Ed25519PublicKey, now: datetime, *, allow_owner_demo: bool) -> None:
        review = self.review
        if tuple(text.locale for text in self.texts) != ("en-CA", "fr-CA"):
            raise PublicationUnavailable("Both ordered locales required")
        for identifier in (review.receipt_id, review.reviewer_id, review.operator_id):
            if str(UUID(identifier)) != identifier:
                raise PublicationUnavailable("Canonical identity required")
        if review.profile == "independent":
            if review.reviewer_id == review.operator_id:
                raise PublicationUnavailable("Independent review required")
        elif review.profile == "owner_review_local_demo":
            if not allow_owner_demo or review.reviewer_id != review.operator_id:
                raise PublicationUnavailable("Explicit same-owner local-demo review required")
        else:
            raise PublicationUnavailable("Unknown review profile")
        if self.artifact_digest != review.artifact_digest:
            raise PublicationUnavailable("Artifact changed")
        verified, due = instant(review.verified_at), instant(review.review_due_at)
        if not verified <= now < due or due > verified + timedelta(days=30):
            raise PublicationUnavailable("Review missing, overdue or beyond the approved cadence")
        try:
            key.verify(
                base64.b64decode(review.signature, validate=True), canonical(review.payload())
            )
        except (InvalidSignature, ValueError) as error:
            raise PublicationUnavailable("Invalid review signature") from error

    def wire(self) -> dict[str, object]:
        return {
            "texts": [text.wire() for text in self.texts],
            "review": self.review.payload() | {"signature": self.review.signature},
        }

    def manifest(self, locale: str) -> dict[str, str]:
        if self.review.profile != "independent":
            raise PublicationUnavailable("Independent manifest unavailable for owner-reviewed demo")
        if locale not in {text.locale for text in self.texts}:
            raise PublicationUnavailable("Unsupported locale")
        return {
            "digest": self.artifact_digest,
            "locale": locale,
            "verified_at": self.review.verified_at,
            "review_due_at": self.review.review_due_at,
            "independent_review_digest": digest(self.review.payload()),
        }

    def owner_manifest(self, locale: str) -> dict[str, object]:
        if self.review.profile != "owner_review_local_demo" or locale not in {
            text.locale for text in self.texts
        }:
            raise PublicationUnavailable("Owner-demo manifest unavailable")
        return {
            "digest": self.artifact_digest,
            "locale": locale,
            "verified_at": self.review.verified_at,
            "review_due_at": self.review.review_due_at,
            "owner_review_digest": digest(self.review.payload()),
            "review_profile": self.review.profile,
            "independent_review": False,
            "participant_admission": False,
            "signature_purpose": "local_artifact_integrity",
        }


def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PublicationUnavailable("Duplicate publication key")
        result[key] = value
    return result


def decode(raw: str) -> Publication:
    try:
        data = cast(dict[str, object], json.loads(raw, object_pairs_hook=unique))
        if set(data) != {"texts", "review"}:
            raise PublicationUnavailable("Invalid publication")
        texts: list[PublicText] = []
        for item in cast(list[dict[str, object]], data["texts"]):
            if set(item) != {"locale", "title", "text"}:
                raise PublicationUnavailable("Invalid text")
            if not all(isinstance(value, str) for value in item.values()):
                raise PublicationUnavailable("Text values required")
            texts.append(PublicText(**cast(dict[str, str], item)))
        if len(texts) != 2:
            raise PublicationUnavailable("Both locales required")
        review = cast(dict[str, object], data["review"])
        fields = {
            "receipt_id",
            "reviewer_id",
            "operator_id",
            "artifact_digest",
            "verified_at",
            "review_due_at",
            "signature",
            "format_version",
            "public_only",
            "locales",
        }
        profile = "independent"
        owner_fields = {
            "review_profile",
            "participant_admission",
            "independent_review",
            "signature_purpose",
        }
        if review.get("format_version") == "public-text-owner-demo-1":
            if (
                set(review) != fields | owner_fields
                or review.get("review_profile") != "owner_review_local_demo"
                or review.get("participant_admission") is not False
                or review.get("independent_review") is not False
                or review.get("signature_purpose") != "local_artifact_integrity"
            ):
                raise PublicationUnavailable("Invalid owner-demo review")
            profile = "owner_review_local_demo"
        elif set(review) != fields or review.get("format_version") != "public-text-1":
            raise PublicationUnavailable("Invalid independent review")
        if review.get("public_only") is not True or review.get("locales") != ["en-CA", "fr-CA"]:
            raise PublicationUnavailable("Invalid review")
        excluded = {"format_version", "public_only", "locales"} | owner_fields
        values = {k: v for k, v in review.items() if k not in excluded}
        values["profile"] = profile
        if not all(isinstance(v, str) for v in values.values()):
            raise PublicationUnavailable("Invalid review values")
        return Publication((texts[0], texts[1]), Review(**cast(dict[str, str], values)))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise PublicationUnavailable("Invalid publication") from error


class PublicationStore:
    """One local publisher; atomic full-record replacement and directory fsync.

    Mount the publication directory read-only in the independent public process.
    The admin process alone owns its OS write permission. No live registry reads.
    """

    def __init__(
        self,
        directory: Path,
        key: Ed25519PublicKey,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        *,
        allow_owner_demo: bool = False,
    ) -> None:
        self.directory = directory
        self.key = key
        self.clock = clock
        self._lock = RLock()
        self.allow_owner_demo = allow_owner_demo

    def _read_record(self) -> retention.Record:
        try:
            raw = (self.directory / "current.json").read_bytes()
            if len(raw) > 4 * 1024 * 1024:
                raise PublicationUnavailable("Publication record too large")
            data = retention.validate(json.loads(raw, object_pairs_hook=unique))
            if data["current"] is not None:
                publication = decode(canonical(data["publication"]).decode())
                metadata = retention.record(data["current"])
                if digest(publication.review.payload()) != metadata["review_digest"]:
                    raise PublicationUnavailable("Current review custody mismatch")
                publication.verify(
                    self.key,
                    retention.timestamp(metadata["published_at"]),
                    allow_owner_demo=self.allow_owner_demo,
                )
            for reference, value in retention.record(data["archives"]).items():
                archive = retention.record(value)
                publication = decode(canonical(archive["publication"]).decode())
                if digest(publication.review.payload()) != reference:
                    raise PublicationUnavailable("Archived review custody mismatch")
                publication.verify(
                    self.key,
                    retention.timestamp(archive["published_at"]),
                    allow_owner_demo=self.allow_owner_demo,
                )
            return data
        except retention.CustodyError as error:
            raise PublicationUnavailable(str(error)) from error
        except (OSError, ValueError, TypeError) as error:
            raise PublicationUnavailable("Reviewed fallback unavailable") from error

    def _read(self) -> tuple[Publication | None, dict[str, object]]:
        data = self._read_record()
        publication = (
            decode(canonical(data["publication"]).decode())
            if data["publication"] is not None
            else None
        )
        return publication, retention.record(data["operations"])

    def current(self) -> Publication:
        publication, _operations = self._read()
        if publication is None:
            raise PublicationUnavailable("No active publication")
        publication.verify(self.key, self.clock(), allow_owner_demo=self.allow_owner_demo)
        return publication

    def _write_record(self, record: retention.Record) -> None:
        retention.validate(record)
        encoded = canonical(record)
        if len(encoded) > 4 * 1024 * 1024:
            raise PublicationUnavailable("Publication operation custody limit reached")
        fd, name = tempfile.mkstemp(dir=self.directory, prefix=".publication-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.directory / "current.json")
            descriptor = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            Path(name).unlink(missing_ok=True)

    @contextmanager
    def _publisher_guard(self) -> Iterator[None]:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_mode & 0o077:
            raise PublicationUnavailable("Publisher directory must be private")
        descriptor = os.open(
            self.directory / ".publisher.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def publish(
        self, publication: Publication, expected: str | None, operator_id: str, operation_id: str
    ) -> Publication:
        if str(UUID(operation_id)) != operation_id:
            raise PublicationUnavailable("Canonical operation UUID required")
        with self._lock, self._publisher_guard():
            path = self.directory / "current.json"
            data: retention.Record | None = self._read_record() if path.exists() else None
            current = (
                decode(canonical(data["publication"]).decode())
                if data is not None and data["publication"] is not None
                else None
            )
            operations = retention.record(data["operations"]) if data is not None else {}
            binding = {
                "operator_id": operator_id,
                "body_digest": digest(
                    {
                        "artifact_digest": publication.artifact_digest,
                        (
                            "owner_review_receipt_id"
                            if publication.review.profile == "owner_review_local_demo"
                            else "independent_review_receipt_id"
                        ): publication.review.receipt_id,
                        "expected_current_digest": expected,
                    }
                ),
            }
            prior = operations.get(operation_id)
            if prior is not None:
                if retention.record(prior)["binding"] != binding or current is None:
                    raise PublicationUnavailable("Publication operation conflict")
                current.verify(self.key, self.clock(), allow_owner_demo=self.allow_owner_demo)
                return current
            now = self.clock()
            publication.verify(self.key, now, allow_owner_demo=self.allow_owner_demo)
            if publication.review.operator_id != operator_id:
                raise PublicationUnavailable("Receipt operator mismatch")
            actual = current.artifact_digest if current else None
            if actual != expected:
                raise PublicationUnavailable("Publication changed")
            reference = digest(publication.review.payload())
            if data is None:
                data = {
                    "format_version": retention.FORMAT,
                    "publication": None,
                    "current": None,
                    "archives": {},
                    "operations": operations,
                }
            archives = retention.record(data["archives"])
            previous = retention.record(data["current"]) if data["current"] is not None else None
            if (
                current is not None
                and previous is not None
                and previous["review_digest"] != reference
            ):
                archives[str(previous["review_digest"])] = {
                    "publication": current.wire(),
                    "published_at": previous["published_at"],
                    "retired_at": retention.stamp(now),
                    "dependency_ended_at": None,
                    "dependency_evidence_digest": None,
                    "hold": previous["hold"],
                    "hold_release": previous["hold_release"],
                }
            if previous is not None and previous["review_digest"] == reference:
                metadata = previous
            elif reference in archives:
                restored = retention.record(archives.pop(reference))
                metadata = retention.metadata(reference, str(restored["published_at"]))
                metadata.update(
                    {"hold": restored["hold"], "hold_release": restored["hold_release"]}
                )
            else:
                metadata = retention.metadata(reference, retention.stamp(now))
            data["publication"], data["current"] = publication.wire(), metadata
            operations[operation_id] = {
                "binding": binding,
                "event_at": retention.stamp(now),
                "review_digest": reference,
                "hold": None,
                "hold_release": None,
            }
            self._write_record(data)
            return publication

    def _maintain(
        self, change: Callable[[retention.Record, datetime], retention.Record]
    ) -> retention.Record:
        """Offline same-writer custody only; never called by a public/browser route."""
        with self._lock, self._publisher_guard():
            data = self._read_record()
            try:
                result = change(data, self.clock())
                self._write_record(data)
                return result
            except retention.CustodyError as error:
                raise PublicationUnavailable(str(error)) from error

    def end_review_dependency(
        self, reference: str, *, ended_at: str, evidence_digest: str, custodian: str = "main"
    ) -> retention.Record:
        def apply(data: retention.Record, now: datetime) -> retention.Record:
            retention.end_dependency(data, reference, ended_at, evidence_digest, custodian, now)
            return {"status": "dependency_end_recorded", "review_digest": reference}

        return self._maintain(apply)

    def retire_current(
        self, reference: str, *, ended_at: str, evidence_digest: str, custodian: str = "main"
    ) -> retention.Record:
        """Explicitly end serving/recovery dependencies using actual custodian evidence.

        Retirement makes serving unavailable. It does not erase the exact review:
        the archived receipt/artifact remains until this end anchor plus 90 days.
        """

        def apply(data: retention.Record, now: datetime) -> retention.Record:
            retention.custodian(custodian)
            metadata = retention.record(data["current"]) if data["current"] is not None else None
            if metadata is not None and metadata["review_digest"] == reference:
                if metadata["hold"] is not None:
                    raise retention.CustodyError(
                        "Review a current publication hold before retirement"
                    )
                retention.record(data["archives"])[reference] = {
                    "publication": data["publication"],
                    "published_at": metadata["published_at"],
                    "retired_at": retention.stamp(now),
                    "dependency_ended_at": None,
                    "dependency_evidence_digest": None,
                    "hold": metadata["hold"],
                    "hold_release": metadata["hold_release"],
                }
                data["current"], data["publication"] = None, None
            retention.end_dependency(data, reference, ended_at, evidence_digest, custodian, now)
            return {"status": "retired", "review_digest": reference}

        return self._maintain(apply)

    def set_retention_hold(
        self, kind: str, reference: str, *, reason: str, review_date: str, custodian: str = "main"
    ) -> retention.Record:
        def apply(data: retention.Record, _now: datetime) -> retention.Record:
            retention.set_hold(data, kind, reference, custodian, reason, review_date)
            return {"status": "held", "kind": kind, "reference": reference}

        return self._maintain(apply)

    def release_retention_hold(
        self, kind: str, reference: str, *, evidence_digest: str, custodian: str = "main"
    ) -> retention.Record:
        def apply(data: retention.Record, now: datetime) -> retention.Record:
            retention.release_hold(data, kind, reference, custodian, evidence_digest, now)
            return {"status": "hold_released", "kind": kind, "reference": reference}

        return self._maintain(apply)

    def cleanup_retention(self, *, custodian: str = "main") -> retention.Record:
        return self._maintain(lambda data, now: retention.cleanup(data, custodian, now))
