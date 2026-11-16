"""Validate a retained care.audit.v1 metadata chain without releasing content."""

from care_link_domain import ManualError

from .store import Record, instant, number, text
from .values import digest, stamp


def verify_audit_chain(
    events: list[Record], *, initial_digest: str = "0" * 64, initial_sequence: int = 1
) -> str:
    previous = initial_digest
    sequence = initial_sequence
    for event in events:
        if (
            event["previous_hash"] != previous
            or number(event, "sequence") != sequence
            or event["stream_id"] != "demo"
        ):
            raise ManualError("manual.audit_chain_invalid", 503)
        encoded: Record = {name: value for name, value in event.items() if name != "hash"}
        if encoded.get("actor_context") is None:
            encoded.pop("actor_context", None)
        encoded["created_at"] = stamp(instant(event, "created_at"))
        encoded["sequence"] = str(sequence)
        encoded["encoding"] = "care.audit.v1"
        expected = digest(encoded)
        if expected != event["hash"]:
            raise ManualError("manual.audit_chain_invalid", 503)
        previous = text(event, "hash")
        sequence += 1
    return previous
