"""Closed, integrity-pinned demo knowledge with scope filtering before ranking.

Content is administrative synthetic-demo guidance, not executable policy, an
approved clinical protocol, personal memory, or an authorization source. URLs
are citation metadata only; this module never fetches them.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

ROLES = frozenset({"pid", "carer", "professional_participant", "worker", "supervisor", "receiver"})
LOCALES = frozenset({"en-CA", "fr-CA"})
DECIMAL = re.compile(r"^[1-9][0-9]{0,18}$")
SECTION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
ENTRY_FIELDS = frozenset(
    {
        "id",
        "revision",
        "section_id",
        "title",
        "text",
        "locale",
        "roles",
        "population",
        "jurisdiction",
        "status",
        "effective_at",
        "review_until",
        "source_url",
        "source_title",
        "license",
        "keywords",
    }
)


class CatalogDenied(ValueError):
    """Safe failure code; no query or retrieved content in the exception."""


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogDenied("knowledge.duplicate_key")
        result[key] = value
    return result


def _date(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CatalogDenied("knowledge.utc_required")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise CatalogDenied("knowledge.invalid_date") from error
    if result.utcoffset() is None:
        raise CatalogDenied("knowledge.utc_required")
    return result


def _text(value: Mapping[str, object], key: str, limit: int) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not 1 <= len(result.strip()) <= limit:
        raise CatalogDenied("knowledge.invalid_metadata")
    return result


def _words(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[\wÀ-ÿ]+", value.casefold()))


@dataclass(frozen=True)
class _Entry:
    """Serialized metadata is private immutable text, never caller-owned mappings."""

    encoded: str
    roles: frozenset[str]
    locale: str
    effective: datetime
    review_until: datetime
    terms: frozenset[str]
    identifier: str
    section: str
    digest: str

    def value(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.encoded))

    def source(self) -> dict[str, object]:
        value = self.value()
        return {
            "kind": "protocol",
            "id": self.identifier,
            "revision": value["revision"],
            "digest": self.digest,
            "observed_at": value["effective_at"],
            # Integrity of authored demo bytes only; never clinical validation.
            "verification": "verified",
        }

    def result(self) -> dict[str, object]:
        value = self.value()
        return {
            "source": self.source(),
            "title": value["title"],
            "text": value["text"],
            "source_url": value["source_url"],
            "source_title": value["source_title"],
            "locale": self.locale,
        }


@dataclass(frozen=True)
class KnowledgeCatalog:
    digest: str
    revision: str
    _entries: tuple[_Entry, ...]

    @classmethod
    def from_path(cls, path: Path) -> KnowledgeCatalog:
        return cls.from_bytes(path.read_bytes())

    @classmethod
    def from_bytes(cls, raw: bytes) -> KnowledgeCatalog:
        if not 1 <= len(raw) <= 1048576:
            raise CatalogDenied("knowledge.catalog_limit")
        try:
            decoded: object = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        except (ValueError, UnicodeError, RecursionError) as error:
            raise CatalogDenied("knowledge.invalid_catalog") from error
        if not isinstance(decoded, dict):
            raise CatalogDenied("knowledge.closed_catalog_required")
        value = cast(dict[str, object], decoded)
        if set(value) != {"schema_version", "revision", "entries"}:
            raise CatalogDenied("knowledge.closed_catalog_required")
        revision = _text(value, "revision", 19)
        if (
            value["schema_version"] != "care-link.knowledge.v1"
            or not DECIMAL.fullmatch(revision)
            or int(revision) > 9223372036854775807
        ):
            raise CatalogDenied("knowledge.version_required")
        rows = value["entries"]
        if not isinstance(rows, list) or not 1 <= len(cast(list[object], rows)) <= 128:
            raise CatalogDenied("knowledge.entry_limit")
        entries: list[_Entry] = []
        ids: set[str] = set()
        sections: set[tuple[str, str]] = set()
        for raw_entry in cast(list[object], rows):
            if not isinstance(raw_entry, dict):
                raise CatalogDenied("knowledge.closed_entry_required")
            entry = cast(dict[str, object], raw_entry)
            if set(entry) != set(ENTRY_FIELDS):
                raise CatalogDenied("knowledge.closed_entry_required")
            identifier = _text(entry, "id", 36)
            try:
                if str(UUID(identifier)) != identifier:
                    raise ValueError("canonical id required")
            except ValueError as error:
                raise CatalogDenied("knowledge.invalid_id") from error
            section = _text(entry, "section_id", 96)
            locale = _text(entry, "locale", 5)
            entry_revision = _text(entry, "revision", 19)
            if (
                identifier in ids
                or (section, locale) in sections
                or not SECTION.fullmatch(section)
                or locale not in LOCALES
                or not DECIMAL.fullmatch(entry_revision)
                or int(entry_revision) > 9223372036854775807
                or entry["population"] != "synthetic-demo"
                or entry["jurisdiction"] != "CA-ON"
                or entry["status"] not in {"synthetic_demo", "reference_only"}
            ):
                raise CatalogDenied("knowledge.invalid_scope")
            if not isinstance(entry["roles"], list) or not isinstance(entry["keywords"], list):
                raise CatalogDenied("knowledge.invalid_index")
            roles = cast(list[object], entry["roles"])
            keywords = cast(list[object], entry["keywords"])
            if (
                not roles
                or len(roles) > len(ROLES)
                or any(not isinstance(role, str) or role not in ROLES for role in roles)
                or len(set(roles)) != len(roles)
                or not 1 <= len(keywords) <= 32
                or any(not isinstance(term, str) or not 1 <= len(term) <= 80 for term in keywords)
            ):
                raise CatalogDenied("knowledge.invalid_index")
            if entry["status"] == "reference_only" and not set(roles) <= {
                "worker",
                "professional_participant",
            }:
                raise CatalogDenied("knowledge.clinical_reference_role_denied")
            title = _text(entry, "title", 200)
            text = _text(entry, "text", 2000)
            _text(entry, "source_title", 200)
            _text(entry, "license", 500)
            url = urlsplit(_text(entry, "source_url", 1000))
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise CatalogDenied("knowledge.invalid_source_url")
            effective, until = _date(entry["effective_at"]), _date(entry["review_until"])
            if effective >= until:
                raise CatalogDenied("knowledge.invalid_review_window")
            encoded = canonical(entry)
            entries.append(
                _Entry(
                    encoded,
                    frozenset(cast(list[str], roles)),
                    locale,
                    effective,
                    until,
                    _words(title + " " + text + " " + " ".join(cast(list[str], keywords))),
                    identifier,
                    section,
                    hashlib.sha256(encoded.encode()).hexdigest(),
                )
            )
            ids.add(identifier)
            sections.add((section, locale))
        return cls(hashlib.sha256(raw).hexdigest(), revision, tuple(entries))

    def _scoped(self, role: str, locale: str, now: datetime) -> tuple[_Entry, ...]:
        if role not in ROLES or locale not in LOCALES or now.tzinfo is None:
            raise CatalogDenied("knowledge.scope_denied")
        # Filtering occurs before scoring; wrong-role/stale entries never enter
        # a candidate context or a cross-role similarity computation.
        return tuple(
            entry
            for entry in self._entries
            if role in entry.roles
            and entry.locale == locale
            and entry.effective <= now < entry.review_until
        )

    def search(
        self, role: str, locale: str, query: str, *, now: datetime | None = None
    ) -> list[dict[str, object]]:
        if not 1 <= len(query.strip()) <= 500:
            raise CatalogDenied("knowledge.query_limit")
        scoped = self._scoped(role, locale, now or datetime.now(UTC))
        terms = _words(query)
        ranked = sorted(
            ((len(terms & entry.terms), entry) for entry in scoped),
            key=lambda row: (-row[0], row[1].identifier),
        )
        return [entry.result() for score, entry in ranked[:4] if score > 0]

    def section(
        self, role: str, locale: str, section_id: str, *, now: datetime | None = None
    ) -> dict[str, object] | None:
        scoped = self._scoped(role, locale, now or datetime.now(UTC))
        return next((entry.result() for entry in scoped if entry.section == section_id), None)

    def sources_current(
        self, role: str, locale: str, sources: list[dict[str, object]], *, now: datetime
    ) -> bool:
        current = [entry.source() for entry in self._scoped(role, locale, now)]
        return all(source in current for source in sources)

    def resolve_sources(
        self, role: str, locale: str, sources: list[dict[str, object]], *, now: datetime
    ) -> list[dict[str, object]]:
        """Resolve a frozen selection without reranking newly effective entries."""
        scoped = self._scoped(role, locale, now)
        result: list[dict[str, object]] = []
        if len({canonical(source) for source in sources}) != len(sources):
            raise CatalogDenied("knowledge.source_binding_changed")
        for source in sources:
            matches = [entry for entry in scoped if entry.source() == source]
            if len(matches) != 1:
                raise CatalogDenied("knowledge.source_binding_changed")
            result.append(matches[0].result())
        return result
