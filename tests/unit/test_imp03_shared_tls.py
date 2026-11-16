"""Renewal-proposal tests use generated local keys; no live lab or trust mutation."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from imp03_tls_fixture import prepare_private_lab

from tools.imp03_shared import tls_renewal

NOW = datetime(2026, 11, 13, 18, 0, tzinfo=UTC)


def save(path, data):
    path.write_bytes(data)
    path.chmod(0o600)


def key_bytes(key):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def spki(key):
    return key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


@pytest.fixture
def private_lab(tmp_path):
    return prepare_private_lab(tmp_path)


def test_expired_same_key_certificates_renew_without_modifying_inputs(private_lab):
    root, output = private_lab
    source = root / "secrets"
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir()}
    manifest = tls_renewal.prepare(root, output, now=NOW)
    ca = x509.load_pem_x509_certificate((output / "ca.crt").read_bytes())
    assert manifest["apply_executed"] is False
    assert manifest["existing_private_keys_copied"] is False
    for name in ("ca", *tls_renewal.LEAVES):
        old = x509.load_pem_x509_certificate((source / (name + ".crt")).read_bytes())
        renewed = x509.load_pem_x509_certificate((output / (name + ".crt")).read_bytes())
        assert old.not_valid_after_utc < NOW
        assert renewed.not_valid_before_utc == NOW - timedelta(minutes=5)
        assert renewed.not_valid_after_utc == NOW + timedelta(days=14 if name == "ca" else 7)
        assert old.serial_number != renewed.serial_number
        assert old.subject == renewed.subject and old.issuer == renewed.issuer
        assert list(old.extensions) == list(renewed.extensions)
        assert spki(old.public_key()) == spki(renewed.public_key())
        renewed.verify_directly_issued_by(ca)
    assert before == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source.iterdir()
    }
    assert output.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())
    assert {path.name for path in output.iterdir()} == {
        *(name + ".crt" for name in tls_renewal.CERTIFICATES),
        "manual.key",
        "manifest.json",
    }
    assert all(item["public_key_spki_preserved"] for item in manifest["renewed_certificates"])
    assert all(
        item["subject_issuer_extensions_preserved"] for item in manifest["renewed_certificates"]
    )


def test_manual_certificate_has_new_key_exact_hostname_and_public_digest(private_lab):
    root, output = private_lab
    manifest = tls_renewal.prepare(root, output, now=NOW)
    ca = x509.load_pem_x509_certificate((output / "ca.crt").read_bytes())
    cert = x509.load_pem_x509_certificate((output / "manual.crt").read_bytes())
    key = serialization.load_pem_private_key((output / "manual.key").read_bytes(), None)
    assert spki(cert.public_key()) == spki(key.public_key())
    cert.verify_directly_issued_by(ca)
    assert cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.DNSName) == ["manual.localhost"]
    assert cert.not_valid_after_utc == NOW + timedelta(days=7)
    summary = tls_renewal.public_summary(output)
    assert summary == manifest
    assert (
        summary["new_manual_certificate"]["new"]["pem_sha256"]
        == hashlib.sha256((output / "manual.crt").read_bytes()).hexdigest()
    )
    assert "BEGIN PRIVATE KEY" not in json.dumps(summary)
    for path in (root / "secrets").glob("*.key"):
        old = serialization.load_pem_private_key(path.read_bytes(), None)
        assert spki(cert.public_key()) != spki(old.public_key())


def test_existing_output_and_symlink_are_never_overwritten(private_lab):
    root, output = private_lab
    output.mkdir(mode=0o700)
    sentinel = output / "preserve"
    sentinel.write_text("existing")
    with pytest.raises(ValueError, match="existing output refused"):
        tls_renewal.prepare(root, output, now=NOW)
    assert sentinel.read_text() == "existing"
    output = output.parent / "linked-renewal"
    output.symlink_to(output.parent / "missing-output")
    with pytest.raises(ValueError, match="existing output refused"):
        tls_renewal.prepare(root, output, now=NOW)


def test_mismatched_old_private_key_refuses_before_output(private_lab):
    root, output = private_lab
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    save(root / "secrets" / "postgres.key", key_bytes(key))
    with pytest.raises(ValueError, match="public bindings differ"):
        tls_renewal.prepare(root, output, now=NOW)
    assert not output.exists()


def test_leaf_signed_by_other_issuer_is_refused_before_output(private_lab):
    root, output = private_lab
    original = x509.load_pem_x509_certificate((root / "secrets" / "help.crt").read_bytes())
    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    builder = (
        x509.CertificateBuilder()
        .subject_name(original.subject)
        .issuer_name(original.issuer)
        .public_key(original.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(original.not_valid_before_utc)
        .not_valid_after(original.not_valid_after_utc)
    )
    for extension in original.extensions:
        builder = builder.add_extension(extension.value, critical=extension.critical)
    forged = builder.sign(wrong, hashes.SHA256())
    save(root / "secrets" / "help.crt", forged.public_bytes(serialization.Encoding.PEM))
    with pytest.raises(ValueError):
        tls_renewal.prepare(root, output, now=NOW)
    assert not output.exists()


def test_nonprivate_input_and_symlink_keys_are_refused(private_lab):
    root, output = private_lab
    key = root / "secrets" / "ca.key"
    key.chmod(0o644)
    with pytest.raises(ValueError, match="regular0600"):
        tls_renewal.prepare(root, output, now=NOW)
    assert not output.exists()
    key.chmod(0o600)
    saved = root / "secrets" / "saved.key"
    key.rename(saved)
    key.symlink_to(saved)
    with pytest.raises(ValueError, match="regular0600"):
        tls_renewal.prepare(root, output, now=NOW)
    assert not output.exists()


def test_public_summary_rejects_certificate_drift(private_lab):
    root, output = private_lab
    tls_renewal.prepare(root, output, now=NOW)
    path = output / "postgres.crt"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="proposal digest"):
        tls_renewal.public_summary(output)
