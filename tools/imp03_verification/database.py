"""Isolated PostgreSQL/TLS test fixture, never the accepted IMP-02 lab.

Only the explicit CLI start command creates this named disposable resource.
Secrets stay in owner-only temporary storage, not evidence or stdout.
"""

import argparse
import ipaddress
import json
import os
import secrets
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

NAME = "care-link-imp03-001-postgres"
IMAGE = "postgres@sha256:80630f83606d8db77d30b3851b16a9f78be2d0d4dda6f7b82a1fdca5ebe3acba"
DIRECTORY = Path("/private/tmp/care-link-imp03-001/database")
PORT = 25433


def _run(arguments: list[str]) -> str:
    result = subprocess.run(arguments, check=True, capture_output=True, text=True)  # noqa: S603
    return result.stdout.strip()


def prepare() -> None:
    if DIRECTORY.exists():
        raise ValueError("Refusing to adopt existing fixture directory")
    DIRECTORY.mkdir(parents=True, mode=0o700)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "IMP03 disposable test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    for filename, content in [
        ("ca.crt", ca.public_bytes(serialization.Encoding.PEM)),
        ("server.crt", server.public_bytes(serialization.Encoding.PEM)),
        (
            "server.key",
            server_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
        ),
    ]:
        path = DIRECTORY / filename
        path.write_bytes(content)
        path.chmod(0o600)
    password = secrets.token_urlsafe(32)
    env = DIRECTORY / "postgres.env"
    env.write_text("POSTGRES_PASSWORD=" + password + "\n")
    env.chmod(0o600)
    settings = {
        "host": "localhost",
        "hostaddr": "127.0.0.1",
        "port": str(PORT),
        "dbname": "postgres",
        "user": "postgres",
        "password": password,
        "sslmode": "verify-full",
        "sslrootcert": str(DIRECTORY / "ca.crt"),
    }
    config = DIRECTORY / "connection.json"
    config.write_text(json.dumps(settings))
    config.chmod(0o600)


def start() -> None:
    if _run(["docker", "ps", "-a", "--filter", "name=^/" + NAME + "$", "--format", "{{.ID}}"]):
        raise ValueError("Refusing to adopt an existing named container")
    if not DIRECTORY.exists():
        prepare()
    # Image entrypoint runs initdb as postgres after copying private fixture keys.
    script = (
        "cp /fixture/server.key /tmp/server.key && "
        "cp /fixture/server.crt /tmp/server.crt && "
        "chown postgres:postgres /tmp/server.key /tmp/server.crt && "
        "chmod 600 /tmp/server.key && "
        "exec docker-entrypoint.sh postgres -c ssl=on "
        "-c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key "
        "-c ssl_min_protocol_version=TLSv1.3 -c ssl_max_protocol_version=TLSv1.3"
    )
    _run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            NAME,
            "--label",
            "care-link.scope=imp03-001-verification",
            "--publish",
            f"127.0.0.1:{PORT}:5432",
            "--tmpfs",
            "/var/lib/postgresql:rw,noexec,nosuid",
            "--mount",
            f"type=bind,src={DIRECTORY},dst=/fixture,readonly",
            "--env-file",
            str(DIRECTORY / "postgres.env"),
            "--entrypoint",
            "sh",
            IMAGE,
            "-c",
            script,
        ]
    )
    print("Started disposable IMP-03 TLS PostgreSQL fixture on loopback25433; no lab changes.")


def stop() -> None:
    label = _run(
        ["docker", "inspect", "--format", '{{index .Config.Labels "care-link.scope"}}', NAME]
    )
    if label != "imp03-001-verification":
        raise ValueError("Refusing cleanup of unowned container")
    _run(["docker", "rm", "--force", NAME])
    print("Removed owned IMP-03 disposable database fixture.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "start", "stop"])
    args = parser.parse_args()
    os.umask(0o077)
    {"prepare": prepare, "start": start, "stop": stop}[args.action]()


if __name__ == "__main__":
    main()
