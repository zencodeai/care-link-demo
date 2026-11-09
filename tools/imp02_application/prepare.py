"""Generate private ephemeral lab PKI and initial passwords; no live mutation."""

import argparse
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID

NAMESPACE = "care-link-imp02-002"


def write(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def pem(key: rsa.RSAPrivateKey | ed25519.Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def prepare(root: Path) -> None:
    if not root.is_absolute() or not root.resolve().is_relative_to(Path("/private/tmp")):
        raise ValueError("Dedicated absolute private temporary output required")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_mode & 0o077 or any(root.iterdir()):
        raise ValueError("Fresh empty owner-only output directory required")
    now = datetime.now(UTC)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "CARE-Link IMP02-002 temporary lab CA")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True
        )
        .sign(key, hashes.SHA256())
    )
    write(root / "ca.key", pem(key))
    write(root / "ca.crt", cert.public_bytes(serialization.Encoding.PEM))
    for role, names in {
        "keycloak": ["id.localhost", "keycloak", f"keycloak.{NAMESPACE}.svc.cluster.local"],
        "postgres": ["postgres.localhost", "postgres", f"postgres.{NAMESPACE}.svc.cluster.local"],
        "main": ["main.localhost"],
        "help": ["help.localhost"],
        "static": ["static.localhost"],
    }.items():
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
        leaf = (
            x509.CertificateBuilder()
            .subject_name(leaf_name)
            .issuer_name(cert.subject)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
            )
            .add_extension(
                x509.KeyUsage(True, False, True, False, False, False, False, False, False),
                critical=True,
            )
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(item) for item in names]), critical=False
            )
            .add_extension(
                x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
            )
            .sign(key, hashes.SHA256())
        )
        write(root / (role + ".key"), pem(leaf_key))
        write(root / (role + ".crt"), leaf.public_bytes(serialization.Encoding.PEM))
    passwords = {
        name: secrets.token_urlsafe(32)
        for name in (
            "postgres_password",
            "keycloak_db_password",
            "keycloak_admin_password",
            "identity_runtime_password",
            "identity_migrator_password",
        )
    }
    write(root / "passwords.json", (json.dumps(passwords, indent=2) + "\n").encode())
    write(root / "custody.key", Fernet.generate_key())
    write(root / "backup.key", Fernet.generate_key())
    for role in ("identity-signing", "signals", "publication"):
        signing = ed25519.Ed25519PrivateKey.generate()
        write(root / (role + ".key"), pem(signing))
        write(
            root / (role + ".pub"),
            signing.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            ),
        )
    print(
        json.dumps(
            {
                "prepared": True,
                "path": str(root),
                "private_material_in_evidence": False,
                "participant_admission": False,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args().output)
