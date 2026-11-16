"""Fresh continuation target without resetting the retained one-way fence.

SPIRE and Keycloak are reused. A disposable PostgreSQL process preserves the
launcher's fixed fresh-only DB/group-role invariants and the old target's data.
"""

import argparse
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from psycopg.conninfo import make_conninfo

from tools.imp02_application.tls import PinnedAddressTransport

from . import docker, provider
from .deployment import name
from .infrastructure import private_write
from .model import CONFIG, PREFIX, PRIVATE, binding, mount
from .operator import shared_secret
from .profiles import ACTIVE

ORIGINAL = Path("/private/tmp/care-link-imp03-003-shared")
PG_HOST = "postgres.care-link-imp02-002.svc.cluster.local"
PG_IMAGE = "postgres@sha256:80630f83606d8db77d30b3851b16a9f78be2d0d4dda6f7b82a1fdca5ebe3acba"


def require_profile() -> None:
    if ACTIVE.name != "continuation-001":
        raise ValueError("Explicit continuation-001 profile required")


def issue() -> dict[str, object]:
    require_profile()
    os.umask(0o077)
    PRIVATE.mkdir(mode=0o700, exist_ok=False)
    pki = PRIVATE / "tls-renewal"
    pki.mkdir(mode=0o700)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "IMP03 continuation001 private CA")]
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    old_ca = (ORIGINAL / "tls-renewal/ca.crt").read_bytes()
    private_write(pki / "continuation-ca.crt", ca.public_bytes(pem))
    private_write(pki / "original-ca.crt", old_ca)
    private_write(pki / "ca.crt", old_ca + ca.public_bytes(pem))
    private_write(
        pki / "continuation-ca.key",
        key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
    )
    for name_, hostname in [("manual", "qualification.localhost"), ("postgres", PG_HOST)]:
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
            .issuer_name(subject)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False
            )
            .sign(key, hashes.SHA256())
        )
        private_write(pki / (name_ + ".crt"), leaf.public_bytes(pem))
        private_write(
            pki / (name_ + ".key"),
            leaf_key.private_bytes(
                pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ),
        )
    with httpx.Client(
        transport=PinnedAddressTransport(provider.BASE, "127.0.0.1", str(pki / "ca.crt")),
        trust_env=False,
        follow_redirects=False,
    ) as client:
        state = provider.bootstrap(
            client, shared_secret("keycloak_admin_password"), PRIVATE / "provider-state.json"
        )
    opa = ORIGINAL / "opa-linux-arm64"
    digest = hashlib.sha256(opa.read_bytes()).hexdigest()
    products = json.loads(Path("config/demo/imp03/products.json").read_text())
    if digest != products["opa"]["linux_arm64_static_sha256"]:
        raise ValueError("Pinned existing Linux OPA required")
    private_write(PRIVATE / "opa-linux-arm64", opa.read_bytes())
    password = secrets.token_urlsafe(32)
    private_write(pki / "postgres.env", "POSTGRES_PASSWORD=" + password + "\n")
    data = binding(state, {r: secrets.token_urlsafe(32) for r in ("identity", "data")}, digest)
    admin = {
        r + "_admin_dsn": make_conninfo(
            host=PG_HOST,
            hostaddr="127.0.0.1",
            port=5432,
            dbname="postgres",
            user="postgres",
            password=password,
            sslmode="verify-full",
            sslrootcert=CONFIG + "/" + r + "/shared-ca.crt",
        )
        for r in ("identity", "data")
    }
    private_write(PRIVATE / "inputs.json", json.dumps({"binding": data, "admin": admin}, indent=2))
    browser = provider.browser_config(
        state,
        help_origin="https://help.localhost:19443",
        static_origin="https://static.localhost:21443",
        ignore_https_errors=False,
    )
    private_write(PRIVATE / "browser.json", json.dumps(browser, indent=2))
    host_admin = make_conninfo(
        host=PG_HOST,
        hostaddr="127.0.0.1",
        port=25435,
        dbname="imp03_runtime_002",
        user="postgres",
        password=password,
        sslmode="verify-full",
        sslrootcert=str(pki / "ca.crt"),
    )
    private_write(PRIVATE / "host-admin.json", json.dumps({"dsn": host_admin}))
    return {
        "profile": ACTIVE.name,
        "realm": provider.REALM,
        "actor_count": len(provider.ROLES),
        "main_origin": ACTIVE.main_origin,
        "old_target_reset": False,
    }


def start_database() -> None:
    require_profile()
    docker.create_network(PREFIX + "-database", subnet="172.29.35.0/24")
    script = """
from pathlib import Path
import os,shutil
cfg=Path('/volumes/postgres-config');data=Path('/volumes/postgres-data')
assert not any(cfg.iterdir()) and not any(data.iterdir())
for directory in (cfg,data):directory.chmod(0o700);os.chown(directory,999,999)
for filename in ('postgres.crt','postgres.key','postgres.env','ca.crt'):
 p=cfg/filename;shutil.copyfile(Path('/operator/tls')/filename,p);p.chmod(0o600);os.chown(p,999,999)
p=cfg/'pg_hba.conf'
p.write_text('local all postgres trust\\n'
 'hostssl all imp03_identity_runtime_002 172.29.35.11/32 scram-sha-256\\n'
 'hostssl all imp03_data_runtime_002 172.29.35.12/32 scram-sha-256\\n'
 'hostssl all postgres 172.29.35.0/24 scram-sha-256\\n'
 'hostssl all postgres 127.0.0.1/32 scram-sha-256\\n'
 'host all all 0.0.0.0/0 reject\\n')
p.chmod(0o600);os.chown(p,999,999)
home=Path('/volumes/browser-home');assert not any(home.iterdir())
home.chmod(0o700);os.chown(home,1000,1000)
"""
    docker.exec(name("seed"), ["python", "-c", script], root=True)
    docker.create_container(
        name("postgres-ingress"),
        image=PG_IMAGE,
        args=[
            "-c",
            "set -a; . /config/postgres.env; set +a; "
            "export PGDATA=/var/lib/postgresql/data; "
            "exec docker-entrypoint.sh postgres -c ssl=on "
            "-c ssl_cert_file=/config/postgres.crt -c ssl_key_file=/config/postgres.key "
            "-c hba_file=/config/pg_hba.conf -c ssl_min_protocol_version=TLSv1.3",
        ],
        mounts=[
            mount("postgres-config", "/config", readonly=True),
            mount("postgres-data", "/var/lib/postgresql/data"),
        ],
        user="999:999",
        network=PREFIX + "-database",
        ip="172.29.35.10",
        publish=["127.0.0.1:25435:5432"],
        entrypoint="/bin/sh",
        memory="512m",
        tmpfs=[
            "/var/run/postgresql:rw,noexec,nosuid,size=4m,mode=1777",
            "/tmp:rw,noexec,nosuid,size=16m,mode=1777",  # noqa: S108 - container tmpfs
        ],
    )
    docker.start(name("postgres-ingress"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["issue"])
    parser.parse_args()
    print(json.dumps(issue()))


if __name__ == "__main__":
    main()
