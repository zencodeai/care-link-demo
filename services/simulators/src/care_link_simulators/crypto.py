"""Receiver-only content key custody and authenticated encryption."""

import base64
import hashlib
import secrets

from care_link_domain import ManualError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ReceiverCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Explicit 256-bit receiver content key required")
        self.cipher = AESGCM(key)
        self.key_ref = "sha256:" + hashlib.sha256(b"care.receiver.keyref.v1" + key).hexdigest()

    def encrypt(self, value: str) -> str:
        nonce = secrets.token_bytes(12)
        return base64.urlsafe_b64encode(
            nonce + self.cipher.encrypt(nonce, value.encode(), b"care.receiver.v1")
        ).decode()

    def decrypt(self, value: str) -> str:
        try:
            raw = base64.b64decode(value, altchars=b"-_", validate=True)
            return self.cipher.decrypt(raw[:12], raw[12:], b"care.receiver.v1").decode()
        except (ValueError, InvalidTag, UnicodeError) as error:
            raise ManualError("receiver.content_unavailable", 503) from error
