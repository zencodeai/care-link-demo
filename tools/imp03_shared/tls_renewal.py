"""Prepare, never apply, same-key transport-certificate renewal for Option B.

Input keys stay in their existing private directory. The output contains renewed
public certificates, one *new* manual-service key/certificate, and public binding
metadata. It is a reviewable proposal, not evidence of operator approval or reload.
"""

import hashlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

LEAVES = ("postgres", "keycloak", "main", "help", "static")
CERTIFICATES = ("ca", *LEAVES, "manual")
Record = dict[str, object]


def _private_directory(path: Path) -> None:
    info = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("Absolute owner-only0700 directory required")


def _private_file(path: Path) -> bytes:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size > 128 * 1024
    ):
        raise ValueError("Owner-only regular0600 input required")
    return path.read_bytes()


def _write(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _spki(cert: x509.Certificate) -> bytes:
    return cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _key(path: Path, cert: x509.Certificate) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(_private_file(path), password=None)
    # The selected lab uses RSA keys. Do not silently change its signing family.
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("Existing RSA lab signing/transport key required")
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if spki != _spki(cert):
        raise ValueError("Existing certificate/private-key public bindings differ")
    return key


def _renew(
    old: x509.Certificate, issuer_key: rsa.RSAPrivateKey, now: datetime, days: int
) -> x509.Certificate:
    serial = x509.random_serial_number()
    while serial == old.serial_number:
        serial = x509.random_serial_number()
    builder = (
        x509.CertificateBuilder()
        .subject_name(old.subject)
        .issuer_name(old.issuer)
        .public_key(old.public_key())
        .serial_number(serial)
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
    )
    for extension in old.extensions:
        builder = builder.add_extension(extension.value, critical=extension.critical)
    return builder.sign(issuer_key, hashes.SHA256())


def _metadata(cert: x509.Certificate, pem: bytes) -> Record:
    return {
        "pem_sha256": hashlib.sha256(pem).hexdigest(),
        "der_fingerprint_sha256": cert.fingerprint(hashes.SHA256()).hex(),
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "serial_number": str(cert.serial_number),
        "not_valid_before": cert.not_valid_before_utc.isoformat(),
        "not_valid_after": cert.not_valid_after_utc.isoformat(),
        "public_key_spki_sha256": hashlib.sha256(_spki(cert)).hexdigest(),
    }


def _manual(
    issuer: x509.Certificate, ca_key: rsa.RSAPrivateKey, now: datetime
) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "manual.localhost")]))
        .issuer_name(issuer.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(True, False, True, False, False, False, False, False, False),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("manual.localhost")]), critical=False
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return cert, key


def prepare(root: Path, output: Path, *, now: datetime | None = None) -> Record:
    """Prepare fresh owner-only output; no source files, services or trust are changed."""
    _private_directory(root)
    source = root / "secrets"
    _private_directory(source)
    if not output.is_absolute() or output.exists() or output.is_symlink():
        raise ValueError("Fresh absolute renewal output required; existing output refused")
    if output.parent.is_symlink() or not output.parent.is_dir():
        raise ValueError("Existing nonsymlink output parent required")
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Timezone-aware renewal time required")
    current = current.astimezone(UTC).replace(microsecond=0)
    originals = {name: (_private_file(source / (name + ".crt"))) for name in ("ca", *LEAVES)}
    old = {name: x509.load_pem_x509_certificate(pem) for name, pem in originals.items()}
    ca = old["ca"]
    ca_key = _key(source / "ca.key", ca)
    if (
        ca.subject != ca.issuer
        or not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    ):
        raise ValueError("Existing self-issued CA certificate required")
    if not ca.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign:
        raise ValueError("Existing CA certificate-signing usage required")
    try:
        ca.verify_directly_issued_by(ca)
    except InvalidSignature:
        raise ValueError("Existing CA signature binding invalid") from None
    renewed = {"ca": _renew(ca, ca_key, current, 14)}
    renewed["ca"].verify_directly_issued_by(renewed["ca"])
    for name in LEAVES:
        cert = old[name]
        _key(source / (name + ".key"), cert)
        if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("Existing transport certificate must be an end entity")
        try:
            cert.verify_directly_issued_by(ca)
        except InvalidSignature:
            raise ValueError("Existing leaf signature/issuer binding invalid") from None
        renewed[name] = _renew(cert, ca_key, current, 7)
        renewed[name].verify_directly_issued_by(renewed["ca"])
    manual, manual_key = _manual(renewed["ca"], ca_key, current)
    manual.verify_directly_issued_by(renewed["ca"])
    new_pem = {
        name: cert.public_bytes(serialization.Encoding.PEM) for name, cert in renewed.items()
    }
    manifest: Record = {
        "schema_version": 1,
        "profile": "imp03-option-b-transport-tls-renewal-proposal",
        "prepared_at": current.isoformat(),
        "apply_executed": False,
        "existing_private_keys_copied": False,
        "existing_input_files_changed": False,
        "renewed_certificates": [
            {
                "name": name,
                "filename": name + ".crt",
                "old": _metadata(old[name], originals[name]),
                "new": _metadata(renewed[name], new_pem[name]),
                "subject_issuer_extensions_preserved": (
                    old[name].subject == renewed[name].subject
                    and old[name].issuer == renewed[name].issuer
                    and list(old[name].extensions) == list(renewed[name].extensions)
                ),
                "public_key_spki_preserved": _spki(old[name]) == _spki(renewed[name]),
                "private_key_public_binding_verified": True,
            }
            for name in ("ca", *LEAVES)
        ],
        "new_manual_certificate": {
            "name": "manual",
            "filename": "manual.crt",
            "private_key_filename": "manual.key",
            "dns_names": ["manual.localhost"],
            "new": _metadata(manual, manual.public_bytes(serialization.Encoding.PEM)),
            "fresh_private_key_generated": True,
        },
        "scope": (
            "Prepared files only; no resource change, reload, host trust installation or approval."
        ),
    }
    output.mkdir(mode=0o700, exist_ok=False)
    _private_directory(output)
    for name, pem in new_pem.items():
        _write(output / (name + ".crt"), pem)
    _write(output / "manual.crt", manual.public_bytes(serialization.Encoding.PEM))
    _write(
        output / "manual.key",
        manual_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    _write(output / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return manifest


def public_summary(output: Path) -> Record:
    """Return public proposal metadata after verifying exact output cert digests."""
    _private_directory(output)
    raw: object = json.loads(_private_file(output / "manifest.json"))
    if not isinstance(raw, dict):
        raise ValueError("Invalid public renewal manifest")
    manifest = cast(Record, raw)
    if manifest.get("profile") != "imp03-option-b-transport-tls-renewal-proposal":
        raise ValueError("Wrong certificate proposal profile")
    raw_certificates = manifest.get("renewed_certificates")
    raw_manual = manifest.get("new_manual_certificate")
    if not isinstance(raw_certificates, list) or not isinstance(raw_manual, dict):
        raise ValueError("Missing renewal certificate bindings")
    certificates = [*cast(list[object], raw_certificates), cast(Record, raw_manual)]
    expected = set(CERTIFICATES)
    seen: set[str] = set()
    for raw_record in certificates:
        if not isinstance(raw_record, dict):
            raise ValueError("Malformed public certificate record")
        record = cast(Record, raw_record)
        name, binding = record.get("name"), record.get("new")
        if not isinstance(name, str) or name not in expected or name in seen:
            raise ValueError("Exact nonduplicate certificate inventory required")
        seen.add(name)
        if record.get("filename") != name + ".crt" or not isinstance(binding, dict):
            raise ValueError("Exact certificate filename/binding required")
        expected_digest = cast(Record, binding).get("pem_sha256")
        if hashlib.sha256(_private_file(output / (name + ".crt"))).hexdigest() != expected_digest:
            raise ValueError("Certificate differs from prepared proposal digest")
    if seen != expected:
        raise ValueError("Incomplete public certificate inventory")
    return manifest
