"""Explicit per-process business-content custody, separate from identity keys."""

import base64
import binascii
import hashlib
import secrets

from care_link_domain import ManualError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class AESGCMContentCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Content encryption requires an explicit 256-bit key")
        self._cipher = AESGCM(key)
        self.key_ref = "sha256:" + hashlib.sha256(b"care.content.keyref.v1" + key).hexdigest()

    def encrypt(self, value: str) -> str:
        nonce = secrets.token_bytes(12)
        encrypted = self._cipher.encrypt(nonce, value.encode("utf-8"), b"care.manual.content.v1")
        return "care.manual.content.v1:" + base64.urlsafe_b64encode(nonce + encrypted).decode()

    def decrypt(self, value: str) -> str:
        try:
            prefix, encoded = value.split(":", 1)
            if prefix != "care.manual.content.v1":
                raise ValueError("Unknown content version")
            raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
            if len(raw) < 28:
                raise ValueError("Truncated encrypted content")
            return self._cipher.decrypt(raw[:12], raw[12:], b"care.manual.content.v1").decode(
                "utf-8"
            )
        except (ValueError, InvalidTag, UnicodeError, binascii.Error) as error:
            raise ManualError("manual.content_unavailable", 503) from error
