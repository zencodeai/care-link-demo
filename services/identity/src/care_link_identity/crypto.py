"""Vetted encrypted custody and deterministic signed evidence encoding."""

import base64
import hashlib
import json
import secrets

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .domain import IdentityError


def token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


class Custody:
    def __init__(self, key: bytes) -> None:
        self._cipher = Fernet(key)

    def encrypt(self, value: str) -> str:
        return self._cipher.encrypt(value.encode()).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._cipher.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as error:
            raise IdentityError("identity.custody_unavailable", 503) from error


class ReceiptSigner:
    def __init__(self, key: Ed25519PrivateKey, key_id: str) -> None:
        self._key = key
        self.key_id = key_id

    def sign(self, payload: dict[str, object]) -> str:
        signature = self._key.sign(canonical(payload))
        return base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
