"""Explicit local secret adapters; secret values never become process arguments."""

import base64
import hashlib
import hmac
import json
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import DemoError
from .models import Record, identifier, record, text
from .storage import private_directory, private_read, private_write


class SecretStore(Protocol):
    def get(self, reference: str) -> str: ...
    def put(self, reference: str, value: str) -> None: ...


class KeychainSecrets:
    """macOS credential store. Interactive security input avoids argv exposure."""

    service = "CARE-Link Demo reference toolkit"
    compressed_prefix = "CARE-LINK-ZLIB-V1:"

    def _command(self, args: list[str], *, stdin: str | None = None) -> str:
        if sys.platform != "darwin":
            raise DemoError("keychain_unavailable_choose_explicit_vault")
        try:
            result = subprocess.run(  # noqa: S603 - fixed OS credential-store tool
                ["/usr/bin/security", *args],
                input=stdin,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise DemoError("keychain_unavailable") from error
        if result.returncode:
            raise DemoError("keychain_secret_unavailable")
        return result.stdout.rstrip("\n")

    def get(self, reference: str) -> str:
        encoded = self._command(
            ["find-generic-password", "-s", self.service, "-a", identifier(reference), "-w"]
        )
        try:
            raw = base64.urlsafe_b64decode(encoded)
            prefix = self.compressed_prefix.encode()
            if raw.startswith(prefix):
                reader = zlib.decompressobj()
                raw = reader.decompress(raw[len(prefix) :], 1048577)
                if len(raw) > 1048576 or not reader.eof or reader.unused_data:
                    raise ValueError("Invalid bounded secret envelope")
            return raw.decode()
        except (ValueError, UnicodeError, zlib.error) as error:
            raise DemoError("keychain_secret_invalid") from error

    def put(self, reference: str, value: str) -> None:
        # Only constant/validated fields and unpadded URL-safe base64 reach the
        # security interactive parser. No user text can inject another command.
        name = identifier(reference)
        raw = value.encode()
        if len(raw) > 2048:
            raw = self.compressed_prefix.encode() + zlib.compress(raw)
        encoded = base64.urlsafe_b64encode(raw).decode()
        command = f'add-generic-password -U -s "{self.service}" -a {name} -w {encoded}\n'
        self._command(["-i"], stdin=command)
        if not hmac.compare_digest(self.get(name), value):
            raise DemoError("keychain_write_unverified")


class VaultSecrets:
    """Encrypted fallback requiring an explicit existing 32-byte private key."""

    def __init__(self, root: Path, key_file: Path) -> None:
        private_directory(root, create=True)
        key = private_read(key_file, limit=32)
        if len(key) != 32:
            raise DemoError("vault_key_must_be_32_bytes")
        self.root, self.key, self.file = root, key, root / "secrets.aesgcm"

    def _read(self) -> Record:
        if not self.file.exists() and not self.file.is_symlink():
            return {}
        raw = private_read(self.file)
        try:
            return record(
                json.loads(AESGCM(self.key).decrypt(raw[:12], raw[12:], b"care-link-demo-vault-v1"))
            )
        except Exception as error:
            raise DemoError("vault_unavailable_or_wrong_key") from error

    def get(self, reference: str) -> str:
        value = self._read().get(identifier(reference))
        if not isinstance(value, str):
            raise DemoError("secret_missing")
        return value

    def put(self, reference: str, value: str) -> None:
        # The registry lock serializes credential operations. Vault also has its
        # own lock for callers using the adapter independently.
        from .storage import Registry

        with Registry(self.root).lock("vault"):
            items = self._read()
            items[identifier(reference)] = value
            nonce = os.urandom(12)
            encrypted = AESGCM(self.key).encrypt(
                nonce, json.dumps(items).encode(), b"care-link-demo-vault-v1"
            )
            private_write(self.file, nonce + encrypted)


def credential(raw: str) -> Record:
    try:
        value = record(json.loads(raw))
        if set(value) != {"password", "totp_secret", "revision"}:
            raise DemoError("invalid_credential_fields")
        text(value, "password", limit=1024)
        seed = text(value, "totp_secret", limit=128)
        if len(base64.b32decode(seed, casefold=True)) < 16:
            raise DemoError("invalid_totp_seed")
        if not isinstance(value["revision"], str) or not str(value["revision"]).isdigit():
            raise DemoError("invalid_credential_revision")
        return value
    except (ValueError, UnicodeError) as error:
        raise DemoError("credential_invalid") from error


def totp(seed: str, *, now: float | None = None) -> tuple[str, int]:
    instant = time.time() if now is None else now
    try:
        key = base64.b32decode(seed, casefold=True)
    except ValueError as error:
        raise DemoError("invalid_totp_seed") from error
    counter = int(instant) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    code = str((struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000).zfill(
        6
    )
    return code, 30 - int(instant) % 30
