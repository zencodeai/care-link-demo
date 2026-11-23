"""Start provisioned IMP-06 roles on their protected backend or broker socket."""

import os
import socket
import ssl
import time
from pathlib import Path
from typing import Literal

import uvicorn
from care_link_workload_trust import (
    BackendVerifier,
    ProtectedUnixH11Protocol,
    SocketCustody,
    UnixFenceClient,
)
from starlette.types import ASGIApp

from .bridge import bridge_application
from .inference import inference_application
from .releases import ReleaseBindings
from .routes import inbound
from .runtime import runtime_worker

BackendRole = Literal["core", "data", "inference", "host-inference-bridge"]


def backend_verifier(
    role: BackendRole,
    *,
    proxy_uid: int,
    fence_socket: Path,
    fence_uid: int,
    training_enabled: bool = False,
) -> BackendVerifier:
    if not fence_socket.is_absolute():
        raise ValueError("absolute protected fence socket required")
    return BackendVerifier(
        proxy_uid,
        inbound(role, training_enabled=training_enabled),
        UnixFenceClient(fence_socket, fence_uid),
        backend_uid=os.geteuid(),
        local_spiffe_id=f"spiffe://care-link.demo/demo/{role}",
    )


def serve_backend(app: ASGIApp, *, backend_socket: Path, proxy_uid: int) -> None:
    """Use the existing exclusive custody lease and kernel peer transport."""
    if not backend_socket.is_absolute() or proxy_uid == os.geteuid() or proxy_uid < 0:
        raise ValueError("absolute application socket and distinct proxy UID required")
    custody = SocketCustody(backend_socket, os.geteuid(), proxy_uid)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(backend_socket))
            custody.bound()
            os.chown(backend_socket, -1, proxy_uid)
            os.chmod(backend_socket, 0o660)
            listener.listen(128)
            server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    http=ProtectedUnixH11Protocol,
                    proxy_headers=False,
                    access_log=False,
                    server_header=False,
                    log_level="critical",
                    timeout_graceful_shutdown=3,
                )
            )
            server.run(sockets=[listener])
            if not server.started:
                raise RuntimeError("protected role startup failed")
    finally:
        custody.close()


def start_inference(
    releases: ReleaseBindings,
    verifier: BackendVerifier,
    *,
    backend_socket: Path,
    data_socket: Path,
    bridge_socket: Path,
) -> None:
    if verifier.local_spiffe_id != "spiffe://care-link.demo/demo/inference":
        raise ValueError("exact inference backend verifier required")
    if (
        not data_socket.is_absolute()
        or not bridge_socket.is_absolute()
        or data_socket == bridge_socket
    ):
        raise ValueError("distinct protected Data and bridge egress sockets required")
    tls = ssl.create_default_context()
    app = inference_application(
        releases,
        data_tls=tls,
        bridge_tls=tls,
        verify=verifier,
        data_socket=data_socket,
        bridge_socket=bridge_socket,
    )
    serve_backend(app, backend_socket=backend_socket, proxy_uid=verifier.proxy_uid)


def start_host_bridge(
    releases: ReleaseBindings,
    verifier: BackendVerifier,
    *,
    backend_socket: Path,
    artifact_directory: Path,
    model_index: Path,
    lmstudio_token_file: Path,
) -> None:
    if verifier.local_spiffe_id != "spiffe://care-link.demo/demo/host-inference-bridge":
        raise ValueError("exact host bridge backend verifier required")
    app = bridge_application(
        releases,
        verifier,
        artifact_directory=artifact_directory,
        model_index=model_index,
        lmstudio_token_file=lmstudio_token_file,
    )
    serve_backend(app, backend_socket=backend_socket, proxy_uid=verifier.proxy_uid)


def start_runtime(releases: ReleaseBindings, *, core_socket: Path, once: bool = False) -> None:
    if not core_socket.is_absolute():
        raise ValueError("absolute protected Core egress socket required")
    releases.release("worker_summary")
    worker, transport = runtime_worker(ssl.create_default_context(), core_socket=core_socket)
    try:
        while releases.current():
            worker.run_once()
            if once:
                return
            time.sleep(1)
    finally:
        transport.close()
