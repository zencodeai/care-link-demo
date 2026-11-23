"""Synthetic browser-origin probes for the protected Kind G-10 deployment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from time import monotonic, sleep, time
from urllib.parse import parse_qs, urljoin, urlsplit
from uuid import uuid4

import httpx

from tools.demo.secrets import totp
from tools.imp02_application.tls import PinnedAddressTransport

from .deployed_fixtures import ID_ORIGIN, ISSUER, MAIN_ORIGIN, SCOPE, STATE, Record, artifact
from .deployed_help import login_form


class BrowserTransport(httpx.BaseTransport):
    def __init__(self) -> None:
        self.routes = {
            origin: PinnedAddressTransport(origin, "127.0.0.1", str(STATE / "browser-ca.pem"))
            for origin in (MAIN_ORIGIN, ID_ORIGIN)
        }

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        origin = str(request.url.copy_with(path="/", query=None, fragment=None)).removesuffix("/")
        if request.url.userinfo or origin not in self.routes:
            raise ValueError("Unexpected synthetic browser origin")
        return self.routes[origin].handle_request(request)

    def close(self) -> None:
        for route in self.routes.values():
            route.close()


def require(condition: object, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def checked(response: httpx.Response, expected: int = 200) -> Record:
    if response.status_code != expected:
        try:
            key = response.json().get("message_key", "unclassified")
        except (ValueError, AttributeError):
            key = "non_json"
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path}: {response.status_code} ({key})"
        )
    return {} if not response.content else response.json()


@dataclass
class Browser:
    username: str
    role: str
    client: httpx.Client = field(
        default_factory=lambda: httpx.Client(
            transport=BrowserTransport(), trust_env=False, timeout=12
        ),
        repr=False,
    )
    csrf: str = field(init=False, default="", repr=False)

    def login(self) -> None:
        passwords = json.loads((STATE / "browser-users.json").read_text())
        seeds = json.loads((STATE / "browser-totp.json").read_text())
        self.csrf = self.get("/v1/auth/csrf")["csrf_token"]
        return_route = {
            "pid": "participant",
            "worker": "workforce",
            "receiver": "workforce",
            "trainer": "training",
            "governance": "governance",
        }[self.role]
        start = self.post(
            "/v1/auth/login", {"role": self.role, "return_route": return_route, "locale": "en-CA"}
        )
        auth = start["authorization_url"]
        callback = MAIN_ORIGIN + "/v1/auth/callback"
        params = parse_qs(urlsplit(auth).query)
        require(
            auth.startswith(ISSUER + "/protocol/openid-connect/auth?")
            and params.get("client_id") == [f"care-link-{SCOPE}-main"]
            and params.get("redirect_uri") == [callback]
            and params.get("code_challenge_method") == ["S256"],
            "Wrong Main OIDC binding",
        )
        response = self.client.get(auth)
        used: set[str] = set()
        for _ in range(8):
            if response.is_redirect:
                target = urljoin(str(response.request.url), response.headers.get("location", ""))
                require(
                    target.startswith(ISSUER + "/") or target.startswith(callback + "?"),
                    "Unexpected Main login redirect",
                )
                response = self.client.get(target, headers={"Accept": "text/html"})
                if target.startswith(callback):
                    require(
                        response.status_code == 303,
                        f"Main callback returned {response.status_code}",
                    )
                    break
                continue
            target, fields, names = login_form(response)
            method = "password" if "password" in names else "otp"
            require(method not in used, "Main login factor denied")
            used.add(method)
            if method == "password":
                fields.update(username=self.username, password=passwords[self.username])
            else:
                if time() % 30 > 21:
                    sleep(30 - time() % 30 + 0.3)
                fields["otp"], _ = totp(seeds[self.username])
            response = self.client.post(target, data=fields)
        else:
            raise ValueError("Main login exceeded its bounded redirect budget")
        view = self.get("/v1/auth/session")
        require(
            view.get("role") == self.role
            and used == {"password", "otp"}
            and bool(self.client.cookies),
            "Current scoped Main browser session required",
        )
        self.csrf = self.get("/v1/auth/csrf")["csrf_token"]

    def get(self, path: str, expected: int = 200) -> Record:
        return checked(self.client.get(MAIN_ORIGIN + path), expected)

    def post(
        self, path: str, data: Record, expected: int = 200, *, key: str | None = None
    ) -> Record:
        return checked(
            self.client.post(
                MAIN_ORIGIN + path,
                json=data,
                headers={
                    "Origin": MAIN_ORIGIN,
                    "X-CSRF-Token": self.csrf,
                    "Idempotency-Key": key or str(uuid4()),
                },
            ),
            expected,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Browser:
        self.login()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def normal() -> Record:
    receipts: Record = {}
    route = "/v1/training/scenarios"
    cancelled = {
        "artifact_digest": hashlib.sha256(
            artifact("config/demo/imp10/training-artifact.json")
        ).hexdigest(),
        "locale": "fr-CA",
        "fixture_mode": "partial",
        "business_clock_at": "2001-01-01T00:00:00Z",
    }
    with (
        Browser(f"{SCOPE}-worker", "worker") as worker,
        Browser(f"{SCOPE}-trainer", "trainer") as trainer,
        Browser(f"{SCOPE}-trainer-1", "trainer") as other,
    ):
        worker.post(route, cancelled, 403)
        created = trainer.post(route, cancelled)
        scenario = str(created["resource_id"])
        target = route + "/" + scenario
        own = trainer.get(target)
        require(own["state"] == "completed", "Training capture did not complete")
        other.get(target, 404)
        trainer.post("/v1/identity-links", {}, 403)
        receipts["training"] = {
            "scenario": scenario,
            "same_owner": 200,
            "other_owner": 404,
            "worker_create": 403,
            "disabled_identity_link": 403,
            "state": own["state"],
            "evidence_digest": own["evidence_digest"],
        }
    with Browser(f"{SCOPE}-pid-1", "pid") as browser:
        start = monotonic()
        result = browser.post(
            "/v1/sessions",
            {
                "tags": {"environment": "demo", "population": "synthetic"},
                "participant_kind": "pid",
                "jurisdiction": None,
                "locale": "en-CA",
                "channel": "web",
                "persona_id": None,
                "fixture_id": None,
            },
        )
        view = browser.get("/v1/sessions/" + result["id"])
        require(view["id"] == result["id"], "Protected Core/Data round trip diverged")
        receipts["participant"] = {
            "create_read_ms": round((monotonic() - start) * 1000, 3),
            "state": view["service_phase"],
            "exact_id_round_trip": True,
        }
    return receipts


def stage_replay(settings: Record, training: Record) -> Record:
    """Admit one exact synthetic completed recording by the scope owner."""
    from datetime import datetime
    from uuid import UUID

    from care_link_data import AESGCMContentCipher
    from care_link_data.training_replay import capture, sha256, training_bundle
    from care_link_domain import canonical_training

    from .deployed_fixtures import file_pin, write
    from .deployed_roles import k, role_inputs, secret

    scenario = str(UUID(training["scenario"]))
    owner = next(
        a["account_id"] for a in settings["accounts"] if a["username"] == f"{SCOPE}-trainer"
    )
    query = (
        "SELECT row_to_json(s)::text FROM training.scenario s WHERE "  # noqa: S608 - UUID-only
        f"id='{scenario}' AND owner_id='{str(UUID(owner))}' AND state='completed' "
        "AND expired_at IS NULL"
    )
    sql_output = k(
        "exec",
        "deployment/postgres",
        "--",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        "training",
        "-Atc",
        query,
    )
    row = json.loads(sql_output)
    projected = json.loads(
        AESGCMContentCipher((STATE / "training-content").read_bytes()).decrypt(
            row["projection_ciphertext"]
        )
    )
    require(
        sha256(canonical_training(projected))
        == training["evidence_digest"]
        == row["evidence_digest"],
        "Stored synthetic evidence differs from current browser capture",
    )
    pinned = artifact("config/demo/imp10/training-artifact.json")
    bundle = training_bundle(
        {
            "artifact": pinned,
            "runner": artifact("packages/domain/src/care_link_domain/training.py"),
            "contracts": artifact("packages/contracts/python/src/care_link_contracts/schema.json"),
        }
    )
    sealed = capture(
        scenario,
        row["fixture"],
        projected,
        datetime.fromisoformat(row["created_at"]),
        bundle=bundle,
        owner_id=owner,
        reviewers=frozenset(),
    )
    documents = {
        "capture-manifest.json": sealed.manifest,
        "capture-observations.json": sealed.observations,
    }
    directory = STATE / "replay"
    directory.mkdir(mode=0o700, exist_ok=False)
    for name, data in documents.items():
        write(directory / name, data)
    catalog = canonical_training(
        {
            "version": 1,
            "artifact_digest": sha256(pinned),
            "bundle_digest": bundle,
            "captures": [
                {
                    "owner_id": owner,
                    "reviewers": [],
                    "manifest": file_pin("/config/capture-manifest.json", sealed.manifest),
                    "observations": file_pin(
                        "/config/capture-observations.json", sealed.observations
                    ),
                }
            ],
        }
    )
    write(directory / "replay-catalog.json", catalog)
    request = {
        "scenario_id": scenario,
        "input_manifest_digest": sha256(sealed.manifest),
        "recorded_outputs_digest": sha256(sealed.observations),
        "bundle_digest": bundle,
    }
    write(directory / "request.json", canonical_training(request))
    k("replace", "-f", "-", payload=secret("data-app", role_inputs("data", settings, "unused")))
    k("rollout", "restart", "deployment/data")
    k("rollout", "status", "deployment/data", "--timeout=70s", timeout=75)
    return request


def replay(request: Record) -> Record:
    route = "/v1/evaluation/replays"
    with (
        Browser(f"{SCOPE}-trainer", "trainer") as owner,
        Browser(f"{SCOPE}-trainer-1", "trainer") as other,
    ):
        started = monotonic()
        key = str(uuid4())
        result = owner.post(route, request, key=key)
        exact = owner.post(route, request, key=key)
        snapshot = owner.get(f"{route}/{result['id']}")
        require(
            result == exact == snapshot
            and result["state"] == "completed"
            and result["clinical_claim"] is False,
            "Replay exact retry or classification differs",
        )
        denial = other.client.post(
            MAIN_ORIGIN + route,
            json=request,
            headers={
                "Origin": MAIN_ORIGIN,
                "X-CSRF-Token": other.csrf,
                "Idempotency-Key": str(uuid4()),
            },
        )
        require(denial.status_code in {403, 404}, "Other trainer gained access to replay")
        return {
            "state": result["state"],
            "exact_retry": True,
            "read_matches": True,
            "duration_ms": round((monotonic() - started) * 1000, 3),
            "other_owner": denial.status_code,
            "clinical_claim": result["clinical_claim"],
        }


if __name__ == "__main__":
    print(json.dumps(normal(), indent=2))
