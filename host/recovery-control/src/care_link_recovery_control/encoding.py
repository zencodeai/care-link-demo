"""Strict local file encoding and explicitly injected signing custody."""

import base64
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from care_link_domain import ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("UTC instant required")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def record(raw: bytes) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value: object = json.loads(raw, object_pairs_hook=pairs)
        if not isinstance(value, dict):
            raise ValueError("nonobject record")
        parsed = cast(dict[str, object], value)
        if canonical(parsed) != raw:
            raise ValueError("noncanonical record")
        return parsed
    except (UnicodeError, ValueError, TypeError) as error:
        raise ManualError("journal.corrupt", 503) from error


def signed(value: dict[str, object], signer: Ed25519PrivateKey) -> dict[str, object]:
    return {**value, "signature": base64.urlsafe_b64encode(signer.sign(canonical(value))).decode()}


def verify(value: dict[str, object], signer: Ed25519PrivateKey) -> dict[str, object]:
    unsigned = {key: item for key, item in value.items() if key != "signature"}
    signature = value.get("signature")
    try:
        if not isinstance(signature, str):
            raise ValueError("signature absent")
        decoded = base64.b64decode(signature, altchars=b"-_", validate=True)
        if len(decoded) != 64 or base64.urlsafe_b64encode(decoded).decode() != signature:
            raise ValueError("noncanonical signature")
        signer.public_key().verify(decoded, canonical(unsigned))
    except (InvalidSignature, ValueError) as error:
        raise ManualError("journal.signature_invalid", 503) from error
    return unsigned


def read(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read()


def write_new(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
