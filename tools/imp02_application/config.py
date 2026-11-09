"""Explicit external lab configuration; no inferred credentials or admission."""

import json
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key


def load(path: Path) -> dict[str, object]:
    if path.is_symlink() or path.stat().st_mode & 0o007:
        raise ValueError("Lab configuration must be a protected regular file")
    value: object = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Lab configuration object required")
    return cast(dict[str, object], value)


def text(config: dict[str, object], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("Missing configured field: " + key)
    return value


def private_key(path: str) -> Ed25519PrivateKey:
    value = load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(value, Ed25519PrivateKey):
        raise ValueError("Ed25519 signing key required")
    return value


def public_key(path: str) -> Ed25519PublicKey:
    value = load_pem_public_key(Path(path).read_bytes())
    if not isinstance(value, Ed25519PublicKey):
        raise ValueError("Ed25519 verification key required")
    return value
