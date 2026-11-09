"""Pure Option B custody rules for offline static-publication maintenance.

The OS writer and authorized custodian supply evidence of dependency end/hold
review. None of these functions authenticates a browser or grants publication.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

Record = dict[str, object]
FORMAT = "public-text-custody-2"


class CustodyError(ValueError):
    pass


def record(value: object) -> Record:
    if not isinstance(value, dict):
        raise CustodyError("Invalid publication custody object")
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise CustodyError("Invalid publication custody key")
    return cast(Record, raw)


def timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CustodyError("Publication custody anchor missing: migration_pending")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise CustodyError("Invalid publication custody anchor") from error
    if result.tzinfo is None:
        raise CustodyError("Aware publication custody anchor required")
    return result


def stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


def digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise CustodyError("Exact publication evidence digest required")
    return value


def identifier(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise CustodyError("Canonical custody UUID required")
    return value


def custodian(owner: str) -> None:
    if owner != "main":
        raise CustodyError("The selected offline publication custodian is main")


def validate_hold(value: object) -> None:
    if value is None:
        return
    hold = record(value)
    if set(hold) != {"owner", "reason", "review_date"} or hold["owner"] != "main":
        raise CustodyError("Invalid publication hold")
    if not isinstance(hold["reason"], str) or not 1 <= len(hold["reason"]) <= 2000:
        raise CustodyError("Publication hold reason required")
    timestamp(hold["review_date"])


def validate_release(value: object) -> None:
    if value is None:
        return
    release = record(value)
    if set(release) != {"owner", "reviewed_at", "evidence_digest"} or release["owner"] != "main":
        raise CustodyError("Invalid publication hold review")
    timestamp(release["reviewed_at"])
    digest(release["evidence_digest"])


def metadata(review_digest: str, published_at: str) -> Record:
    return {
        "review_digest": review_digest,
        "published_at": published_at,
        "hold": None,
        "hold_release": None,
    }


def serving_ended_at(archive: Record) -> datetime:
    publication = record(archive["publication"])
    review = record(publication.get("review"))
    return min(timestamp(archive["retired_at"]), timestamp(review.get("review_due_at")))


def validate(value: object) -> Record:
    data = record(value)
    if data.get("format_version") != FORMAT:
        raise CustodyError("Publication lifecycle migration_pending")
    if set(data) != {"format_version", "publication", "current", "archives", "operations"}:
        raise CustodyError("Invalid publication custody record")
    if data["current"] is None:
        if data["publication"] is not None:
            raise CustodyError("Retired current publication pointer is inconsistent")
    else:
        current = record(data["current"])
        if data["publication"] is None or set(current) != {
            "review_digest",
            "published_at",
            "hold",
            "hold_release",
        }:
            raise CustodyError("Current publication anchor missing: migration_pending")
        digest(current["review_digest"])
        timestamp(current["published_at"])
        validate_hold(current["hold"])
        validate_release(current["hold_release"])
    for key, item in record(data["archives"]).items():
        digest(key)
        archive = record(item)
        if set(archive) != {
            "publication",
            "published_at",
            "retired_at",
            "dependency_ended_at",
            "dependency_evidence_digest",
            "hold",
            "hold_release",
        }:
            raise CustodyError("Archived publication anchor missing: migration_pending")
        published, retired = timestamp(archive["published_at"]), timestamp(archive["retired_at"])
        if published > retired:
            raise CustodyError("Publication retirement precedes publication")
        ended = archive["dependency_ended_at"]
        if ended is not None:
            if timestamp(ended) < max(published, serving_ended_at(archive)):
                raise CustodyError("Dependency end precedes the actual serving boundary")
            digest(archive["dependency_evidence_digest"])
        elif archive["dependency_evidence_digest"] is not None:
            raise CustodyError("Dependency evidence has no end anchor")
        validate_hold(archive["hold"])
        validate_release(archive["hold_release"])
    for key, item in record(data["operations"]).items():
        identifier(key)
        operation = record(item)
        if set(operation) != {"binding", "event_at", "review_digest", "hold", "hold_release"}:
            raise CustodyError("Publication operation anchor missing: migration_pending")
        binding = record(operation["binding"])
        if set(binding) != {"operator_id", "body_digest"}:
            raise CustodyError("Invalid publication operation binding")
        identifier(binding["operator_id"])
        digest(binding["body_digest"])
        digest(operation["review_digest"])
        timestamp(operation["event_at"])
        validate_hold(operation["hold"])
        validate_release(operation["hold_release"])
    return data


def item(data: Record, kind: str, reference: str) -> Record:
    if kind == "operation":
        result = record(data["operations"]).get(identifier(reference))
    elif kind == "review":
        digest(reference)
        current = record(data["current"]) if data["current"] is not None else None
        result = (
            current
            if current is not None and current["review_digest"] == reference
            else record(data["archives"]).get(reference)
        )
    else:
        raise CustodyError("Unknown publication custody reference")
    if result is None:
        raise CustodyError("Publication custody reference unavailable")
    return record(result)


def end_dependency(
    data: Record, reference: str, ended_at: str, evidence_digest: str, owner: str, now: datetime
) -> None:
    custodian(owner)
    archive = record(record(data["archives"]).get(digest(reference)))
    ended = timestamp(ended_at)
    lower_bound = max(timestamp(archive["published_at"]), serving_ended_at(archive))
    if not lower_bound <= ended <= now:
        raise CustodyError("Dependency end precedes the actual serving boundary or is not past")
    digest(evidence_digest)
    if archive["dependency_ended_at"] is not None:
        if (archive["dependency_ended_at"], archive["dependency_evidence_digest"]) != (
            ended_at,
            evidence_digest,
        ):
            raise CustodyError("Dependency anchor cannot be renewed or silently replaced")
        return
    archive.update({"dependency_ended_at": ended_at, "dependency_evidence_digest": evidence_digest})


def set_hold(
    data: Record, kind: str, reference: str, owner: str, reason: str, review_date: str
) -> None:
    custodian(owner)
    hold = {"owner": owner, "reason": reason, "review_date": review_date}
    validate_hold(hold)
    item(data, kind, reference)["hold"] = hold


def release_hold(
    data: Record, kind: str, reference: str, owner: str, evidence_digest: str, now: datetime
) -> None:
    custodian(owner)
    digest(evidence_digest)
    target = item(data, kind, reference)
    if target["hold"] is None:
        raise CustodyError("No hold to release")
    target["hold"] = None
    target["hold_release"] = {
        "owner": owner,
        "reviewed_at": stamp(now),
        "evidence_digest": evidence_digest,
    }


def cleanup(data: Record, owner: str, now: datetime) -> Record:
    custodian(owner)
    archives, operations = record(data["archives"]), record(data["operations"])
    removed_archives: list[str] = []
    for reference, value in list(archives.items()):
        archive = record(value)
        ended = archive["dependency_ended_at"]
        linked_hold = any(
            record(operation)["review_digest"] == reference
            and record(operation)["hold"] is not None
            for operation in operations.values()
        )
        if (
            ended is not None
            and timestamp(ended) + timedelta(days=90) <= now
            and archive["hold"] is None
            and not linked_hold
        ):
            del archives[reference]
            removed_archives.append(reference)
    protected = set(archives)
    if data["current"] is not None:
        protected.add(digest(record(data["current"])["review_digest"]))
    removed_operations: list[str] = []
    for reference, value in list(operations.items()):
        operation = record(value)
        if (
            timestamp(operation["event_at"]) + timedelta(days=90) <= now
            and operation["review_digest"] not in protected
            and operation["hold"] is None
        ):
            del operations[reference]
            removed_operations.append(reference)
    overdue: list[Record] = []
    targets: list[tuple[str, str, Record]] = []
    expired = False
    needs_decision = False
    if data["current"] is not None:
        current = record(data["current"])
        targets.append(("review", digest(current["review_digest"]), current))
        review = record(record(data["publication"])["review"])
        expired = timestamp(review["review_due_at"]) <= now
        needs_decision = expired and current["hold"] is None
    targets += [("review", reference, record(value)) for reference, value in archives.items()]
    targets += [("operation", reference, record(value)) for reference, value in operations.items()]
    for kind, reference, target in targets:
        if target["hold"] is not None:
            hold = record(target["hold"])
            if timestamp(hold["review_date"]) <= now:
                overdue.append(
                    {
                        "kind": kind,
                        "reference": reference,
                        "owner": hold["owner"],
                        "review_date": hold["review_date"],
                        "review_required": True,
                    }
                )
    return {
        "removed_archive_count": len(removed_archives),
        "removed_operation_count": len(removed_operations),
        "overdue_holds": overdue,
        "status": "hold_review_required"
        if overdue
        else "dependency_review_required"
        if needs_decision
        else "completed",
        "current_review_expired": expired,
        "current_dependency_requires_custodian_decision": needs_decision,
        "custodian": "main",
        "scope": "active custody record only; no backup or physical-erasure claim",
    }
