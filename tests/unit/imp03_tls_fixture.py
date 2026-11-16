"""Private generated TLS material shared by renewal and mocked-apply tests."""

from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

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


def prepare_private_lab(tmp_path):
    root = tmp_path / "old-lab"
    root.mkdir(mode=0o700)
    source = root / "secrets"
    source.mkdir(mode=0o700)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic old transport CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=5))
        .not_valid_after(NOW - timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True
        )
        .sign(ca_key, hashes.SHA256())
    )
    save(source / "ca.key", key_bytes(ca_key))
    save(source / "ca.crt", ca.public_bytes(serialization.Encoding.PEM))
    for name in tls_renewal.LEAVES:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name + ".localhost")]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(NOW - timedelta(days=4))
            .not_valid_after(NOW - timedelta(days=3))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.DNSName(name + ".localhost"), x509.DNSName(name + ".synthetic.invalid")]
                ),
                critical=False,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        save(source / (name + ".key"), key_bytes(key))
        save(source / (name + ".crt"), leaf.public_bytes(serialization.Encoding.PEM))
    return root, tmp_path / "renewal"
