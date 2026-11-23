"""Private dependency fixtures for the opt-in SPIRE/Envoy Docker check."""

from __future__ import annotations

import errno
import json
import os
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast
from uuid import uuid4

if TYPE_CHECKING:
    from care_link_inference import BrokerRequest
    from care_link_runtime import HttpBrokerTransport
    from care_link_workload_trust import BackendVerifier
    from fastapi import FastAPI

BASE = "/run/qualification"
ROLES = ("runtime", "core", "data", "inference", "host-inference-bridge")
FENCE_OWNER, FENCE_GROUP, FENCE_RESTRICT = 26300, 26301, 26302
CLAIM = "/internal/v1/broker/work"
MANUAL_CHANNEL = "/internal/v1/channels/current"
FIXTURE_ACCOUNT = "11111111-1111-4111-8111-111111111111"
FENCE_PATH = Path(BASE + "/fence/fence.sock")
GATE_PATH = Path(BASE + "/backend")
Record = dict[str, object]


@dataclass(frozen=True)
class Uids:
    app: int
    proxy: int
    authorization: int


UID = {role: Uids(26100 + i * 3, 26101 + i * 3, 26102 + i * 3) for i, role in enumerate(ROLES)}


def spiffe(role: str) -> str:
    return "spiffe://care-link.demo/demo/" + role


def app_mounts(role: str) -> tuple[tuple[str, bool], ...]:
    if role == "runtime":
        return (("outbound", True),)
    if role == "host-inference-bridge":
        return (("backend", False),)
    return (("backend", False), ("outbound", True))


def destinations(role: str) -> dict[str, frozenset[tuple[str, str]]]:
    from tools.imp06_runtime.routes import outbound

    if role == "data":
        return {"core": frozenset({("POST", MANUAL_CHANNEL)})}
    if role == "host-inference-bridge":
        return {}
    return outbound(role)


def folder(path: Path, uid: int, group: int, mode: int) -> None:
    path.mkdir(exist_ok=True)
    os.chown(path, uid, group)
    path.chmod(mode)


def write(path: Path, value: str, uid: int, *, private: bool = True) -> None:
    with path.open("x") as stream:
        stream.write(value)
    path.chmod(0o600 if private else 0o644)
    os.chown(path, uid, uid)


def seed() -> None:
    root = Path("/seed")
    for role in ROLES:
        owners = UID[role]
        path = root / role
        for suffix, owner, group, mode in (
            ("backend", owners.app, owners.proxy, 0o2710),
            ("authorization", owners.authorization, owners.proxy, 0o710),
            ("proxy", owners.proxy, owners.proxy, 0o700),
            ("outbound", owners.proxy, owners.app, 0o2710),
            ("spire", 0, 0, 0o755),
            ("agent", 0, 0, 0o700),
        ):
            folder(path / suffix, owner, group, mode)
    folder(root / "issuer/config", 0, 0, 0o700)
    folder(root / "issuer/data", 0, 0, 0o700)
    folder(root / "fence/ledger", FENCE_OWNER, FENCE_OWNER, 0o700)
    # The root of the fresh named volume already exists.
    (root / "fence").chmod(0o710)
    os.chown(root / "fence", FENCE_OWNER, FENCE_GROUP)
    write(root / "issuer/config/server.conf", sys.stdin.read(), 0)


def configure(role: str) -> None:
    value = cast(Record, json.load(sys.stdin))
    owners = UID[role]
    path = Path("/seed") / role
    write(path / "agent/agent.conf", str(value["agent"]), 0)
    write(path / "agent/join.token", str(value["token"]), 0)
    write(path / "agent/bundle.crt", str(value["bundle"]), 0)
    write(path / "authorization/bundle.pem", str(value["bundle"]), owners.authorization)
    write(path / "proxy/envoy.json", json.dumps(value["envoy"]), owners.proxy)


def fence() -> None:
    from care_link_workload_trust import FenceServer, FenceStore

    fence_store = FenceStore(FENCE_PATH.parent / "ledger", FENCE_OWNER)
    fence_store.initialize(frozenset(spiffe(role) for role in ROLES))
    with FenceServer(
        FENCE_PATH,
        fence_store,
        owner_uid=FENCE_OWNER,
        access_gid=FENCE_GROUP,
        read_uids=frozenset(
            uid
            for role in ROLES
            if role != "runtime"
            for uid in (UID[role].app, UID[role].authorization)
        ),
        restrict_uid=FENCE_RESTRICT,
    ) as server:
        server.serve_forever()


def authorize(role: str) -> None:
    from care_link_workload_trust import AuthorizationServer, UnixFenceClient, WorkloadEnforcer
    from cryptography import x509

    from tools.imp06_runtime.routes import inbound

    owners = UID[role]
    directory = Path(BASE + "/authorization")
    roots = tuple(x509.load_pem_x509_certificates((directory / "bundle.pem").read_bytes()))
    enforcer = WorkloadEnforcer(
        owners.proxy,
        roots,
        inbound(role),
        UnixFenceClient(FENCE_PATH, FENCE_OWNER),
        local_spiffe_id=spiffe(role),
    )
    with AuthorizationServer(
        directory / "auth.sock", enforcer, owners.authorization, owners.proxy
    ) as server:
        server.serve_forever()


def excluded(*_args: object) -> NoReturn:
    raise RuntimeError("unscheduled fixture operation")


class FixtureAuthority:
    def resolve(self, request: Record) -> Record:
        return excluded()

    def current(self, request: Record) -> bool:
        if request != {"fixture": "no_business_authority"}:
            raise ValueError("exact fixture probe required")
        return False


class FixtureProvider:
    def complete(self, payload: Record, deadline: datetime) -> bytes:
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if payload != {"fixture": "bridge_transport"} or not 0 < remaining <= 30:
            raise ValueError("exact fixture probe required")
        return b'{"fixture":"provider_response","model_called":false}'


def core(verify: BackendVerifier) -> FastAPI:
    from care_link_core.assistance_broker import InferenceBroker
    from care_link_core.assistance_broker.ports import Coordinator, InferencePort
    from care_link_core.assistance_broker.routes import attach_broker_routes
    from care_link_core.manual_channels import ManualChannels
    from care_link_domain import WorkloadPeer
    from fastapi import FastAPI, Request
    from starlette.responses import JSONResponse

    from tools.imp06_runtime.trust import runtime_verifier

    class FixtureBroker(InferenceBroker):
        def claim_work(self, peer: WorkloadPeer) -> Record:
            if (GATE_PATH / "claim-armed").exists():
                (GATE_PATH / "claim-entered").touch()
                deadline = time.monotonic() + 20
                while not (GATE_PATH / "claim-finish").exists():
                    if time.monotonic() >= deadline:
                        raise RuntimeError("qualification claim gate timed out")
                    time.sleep(0.025)
            return super().claim_work(peer)

    app = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)
    broker = FixtureBroker(
        cast(Coordinator, None),
        cast(InferencePort, None),
        actor_for_task=excluded,
        release=excluded,
    )
    attach_broker_routes(app, broker, runtime_verifier(verify))
    channels = ManualChannels()

    async def manual(request: Request) -> JSONResponse:
        # Exercise the manual channel authority separately from AI task custody.
        if not verify(request, "data"):
            return JSONResponse({"current": False}, status_code=403)
        return JSONResponse({"current": channels.current(FIXTURE_ACCOUNT, "a" * 64, 1)})

    manual.__annotations__["request"] = Request
    app.add_api_route(MANUAL_CHANNEL, manual, methods=["POST"], response_model=None)
    return app


def data(verify: BackendVerifier) -> FastAPI:
    from unittest.mock import create_autospec

    from care_link_data import ManualService, attach_inference_ledger_gateway
    from care_link_data.app import GatewaySecurity, create_app
    from care_link_data.assistance_jobs import PostgresJobLedger

    service = create_autospec(ManualService, instance=True, replay_evaluator=None)
    app = create_app(service, cast(GatewaySecurity, None))
    attach_inference_ledger_gateway(
        app,
        cast(PostgresJobLedger, None),
        verify,
        FixtureAuthority(),
    )
    return app


def no_evaluated_context(_value: Record) -> BrokerRequest:
    from care_link_inference import InferenceDenied

    raise InferenceDenied("qualification_no_serving_release")


def inference(verify: BackendVerifier) -> FastAPI:
    from care_link_inference import InferenceGateway, create_app

    return create_app(cast(InferenceGateway, None), verify, no_evaluated_context)


def bridge(verify: BackendVerifier) -> FastAPI:
    from care_link_inference_bridge import create_app

    return create_app(FixtureProvider(), verify)


def serve(role: str) -> None:
    if role == "runtime":
        # docker exec runs the real Runtime transport in this isolated app namespace.
        while True:
            time.sleep(1800)
    import uvicorn
    from care_link_domain import ManualError
    from care_link_workload_trust import BackendVerifier, ProtectedUnixH11Protocol, UnixFenceClient
    from fastapi import Request
    from starlette.responses import JSONResponse, Response

    from tools.imp06_runtime.routes import inbound

    owners = UID[role]
    verify = BackendVerifier(
        owners.proxy,
        inbound(role),
        UnixFenceClient(FENCE_PATH, FENCE_OWNER),
        backend_uid=owners.app,
        local_spiffe_id=spiffe(role),
    )
    app = {"core": core, "data": data, "inference": inference, "host-inference-bridge": bridge}[
        role
    ](verify)

    async def deny(_request: Request, error: Exception) -> JSONResponse:
        if not isinstance(error, ManualError):
            raise error
        return JSONResponse({"code": error.code}, status_code=error.status)

    app.add_exception_handler(ManualError, deny)

    # Evidence-only headers expose no credentials or content. They are minted
    # exclusively on real app replies to already verified mesh requests.
    async def observed(request: Request, next_handler: object) -> Response:
        from collections.abc import Awaitable, Callable

        respond = cast(Callable[[Request], Awaitable[Response]], next_handler)
        response = await respond(request)
        peer = request.headers.get("x-care-link-verified-spiffe", "").rsplit("/", 1)[-1]
        if verify(request, peer):
            response.headers["x-qualification-peer"] = spiffe(peer)
            response.headers["x-qualification-svid-sha256"] = request.headers[
                "x-care-link-certificate-digest"
            ]
        return response

    app.middleware("http")(observed)
    with socket.socket(socket.AF_UNIX) as listener:
        path = Path(BASE + "/backend/service.sock")
        listener.bind(str(path))
        path.chmod(0o660)
        listener.listen()
        uvicorn.Server(
            uvicorn.Config(
                app,
                http=ProtectedUnixH11Protocol,
                log_level="critical",
                access_log=False,
            )
        ).run(sockets=[listener])


def runtime_transport() -> HttpBrokerTransport:
    from care_link_runtime import HttpBrokerTransport

    from tools.imp02_application.mesh import MeshTransport

    origin = "https://core:8443"
    return HttpBrokerTransport(
        ssl.create_default_context(),
        transport=MeshTransport(
            Path(BASE + "/outbound/core.sock"),
            origin,
        ),
    )


def claim() -> Record:
    transport = runtime_transport()
    try:
        return dict(transport.poll_work())
    finally:
        transport.close()


def post(destination: str, path: str, *, direct: bool = False) -> Record:
    import httpx

    from tools.imp02_application.mesh import MeshTransport

    url = "https://" + destination + ":8443"
    if direct:
        transport: httpx.BaseTransport = httpx.HTTPTransport(uds=BASE + "/backend/service.sock")
        url = "http://backend"
    else:
        transport = MeshTransport(Path(BASE + "/outbound/" + destination + ".sock"), url)
    headers = {"Idempotency-Key": str(uuid4())}
    if direct:
        headers |= {
            "X-Care-Link-Verified-Spiffe": spiffe("runtime"),
            "X-Care-Link-Fence-Generation": "0",
            "X-Care-Link-Certificate-Expires-At": (
                datetime.now(UTC) + timedelta(minutes=1)
            ).isoformat(),
            "X-Care-Link-Certificate-Digest": "a" * 64,
        }
    with httpx.Client(transport=transport, trust_env=False, timeout=24) as client:
        response = client.post(url + path, json=json.load(sys.stdin), headers=headers)
    return {
        "status": response.status_code,
        "body": response.json()
        if response.headers.get("content-type", "").startswith("application/json")
        else None,
        "authenticated_peer": response.headers.get("x-qualification-peer"),
        "peer_certificate_digest": response.headers.get("x-qualification-svid-sha256"),
    }


def isolation(address: str) -> Record:
    route_rows = Path("/proc/net/route").read_text().splitlines()
    status = Path("/proc/self/status").read_text().splitlines()
    effective = next(line.split()[1] for line in status if line.startswith("CapEff:"))
    active = sorted(
        name
        for _, name in socket.if_nameindex()
        if int((Path("/sys/class/net") / name / "flags").read_text().strip(), 16) & 1
    )
    denies: dict[str, str] = {}
    for target, port in ((address, 8443), ("192.0.2.1", 443), ("2001:db8::1", 443)):
        try:
            with socket.create_connection((target, port), timeout=0.5):
                raise RuntimeError("network-none app acquired direct TCP")
        except OSError as error:
            if error.errno != errno.ENETUNREACH:
                raise
            denies[target] = "network_unreachable"
    return {
        "uid": os.geteuid(),
        "active_interfaces": active,
        "no_ipv4_routes": len(route_rows) == 1,
        "effective_capabilities": int(effective, 16),
        "direct_tcp": list(denies.values()),
        "mounted_socket_directories": sorted(item.name for item in Path(BASE).iterdir()),
    }


def restrict() -> Record:
    from care_link_workload_trust import UnixFenceClient

    result = UnixFenceClient(FENCE_PATH, FENCE_OWNER).restrict(spiffe("runtime"), str(uuid4()), 0)
    return {"generation": result.generation, "peer": result.peer, "durable": result.durable}


def main() -> None:
    action, *arguments = sys.argv[1:]
    if action == "seed":
        seed()
    elif action == "configure":
        configure(arguments[0])
    elif action == "fence":
        fence()
    elif action == "authorize":
        authorize(arguments[0])
    elif action == "serve":
        serve(arguments[0])
    elif action == "claim":
        print(json.dumps(claim()), flush=True)
    elif action in {"post", "direct"}:
        print(json.dumps(post(arguments[0], arguments[1], direct=action == "direct")), flush=True)
    elif action == "isolation":
        print(json.dumps(isolation(arguments[0])), flush=True)
    elif action == "restrict":
        print(json.dumps(restrict()), flush=True)
    elif action in {"claim-armed", "claim-finish"}:
        (GATE_PATH / action).touch(exist_ok=False)
    elif action == "claim-entered":
        if not (GATE_PATH / action).exists():
            raise SystemExit(1)
    else:
        raise SystemExit("closed fixture command required")


if __name__ == "__main__":
    main()
