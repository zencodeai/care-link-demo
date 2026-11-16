"""Primary-owned operations for the explicit Option B qualification profile."""

import argparse
import base64
import hashlib
import json
import secrets
from pathlib import Path

import httpx
from psycopg.conninfo import make_conninfo

from tools.imp02_application.tls import PinnedAddressTransport

from . import deployment, provider
from .infrastructure import command, private_write
from .model import CONFIG, KUBE, PRIVATE, Record, binding


def shared_secret(field: str) -> str:
    if field not in {"postgres_password", "keycloak_admin_password"}:
        raise ValueError("Exact shared bootstrap credential required")
    encoded = command(
        KUBE
        + [
            "-n",
            "care-link-imp02-002",
            "get",
            "secret",
            "imp02-passwords",
            "-o",
            "jsonpath={.data." + field + "}",
        ],
    )
    if not encoded:
        raise ValueError("Shared bootstrap credential missing")
    return base64.b64decode(encoded, validate=True).decode()


def issue_inputs(private: Path) -> Record:
    if (private / "inputs.json").exists():
        raise ValueError("Existing runtime inputs refused; inspect current deployment binding")
    maintenance = json.loads((private / "tls-backup-002/public-result.json").read_text())
    if maintenance.get("certificate_bindings_match") is not True:
        raise ValueError("Completed approved TLS renewal required")
    opa = private / "opa-linux-arm64"
    digest = hashlib.sha256(opa.read_bytes()).hexdigest()
    products = Path(__file__).resolve().parents[2] / "config/demo/imp03/products.json"
    if digest != json.loads(products.read_text())["opa"]["linux_arm64_static_sha256"]:
        raise ValueError("Pinned Linux OPA artifact required")
    with httpx.Client(
        transport=PinnedAddressTransport(
            provider.BASE, "127.0.0.1", str(private / "tls-renewal/ca.crt")
        ),
        trust_env=False,
        follow_redirects=False,
    ) as client:
        state = provider.bootstrap(
            client, shared_secret("keycloak_admin_password"), private / "provider-state.json"
        )
    data = binding(
        state, {role: secrets.token_urlsafe(32) for role in ("identity", "data")}, digest
    )
    password = shared_secret("postgres_password")
    admin = {
        role + "_admin_dsn": make_conninfo(
            host="postgres.care-link-imp02-002.svc.cluster.local",
            hostaddr="127.0.0.1",
            port=5432,
            user="postgres",
            password=password,
            dbname="postgres",
            sslmode="verify-full",
            sslrootcert=CONFIG + "/" + role + "/shared-ca.crt",
        )
        for role in ("identity", "data")
    }
    private_write(private / "inputs.json", json.dumps({"binding": data, "admin": admin}, indent=2))
    browser = provider.browser_config(
        state,
        help_origin="https://help.localhost:19443",
        static_origin="https://static.localhost:21443",
        ignore_https_errors=True,
    )
    private_write(private / "browser.json", json.dumps(browser, indent=2))
    summary = provider.public_summary(state)
    summary.update(
        actor_registry_sha256=hashlib.sha256(
            json.dumps(provider.actor_registry(state), sort_keys=True).encode()
        ).hexdigest(),
        browser_certificate_profile="Temporary CA exception; browser CA trust remains unqualified",
        backend_tls_profile="verify-full with renewed transport CA; no TLS bypass",
        placement=(
            "Docker protected source-launcher qualification; "
            "not new-application Kubernetes/Calico evidence"
        ),
    )
    private_write(private / "issuance-summary.json", json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("issue", "prepare-volumes", "dependencies", "provision", "applications")
    )
    parser.add_argument("--private", type=Path, default=PRIVATE)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args()
    actions = {
        "issue": issue_inputs,
        "prepare-volumes": deployment.prepare_volumes,
        "dependencies": deployment.dependencies,
        "provision": deployment.provision,
        "applications": deployment.applications,
    }
    result = actions[args.action](args.private)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
