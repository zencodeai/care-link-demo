"""Inference role has authenticated data/bridge transports and no DB credentials."""

import ssl
from collections.abc import Callable
from pathlib import Path

from care_link_inference import (
    DataTransport,
    HttpBridge,
    HttpContextAuthority,
    HttpJobLedger,
    HttpTokenCounter,
    InferenceGateway,
    create_app,
)
from fastapi import FastAPI, Request

from tools.imp02_application.mesh import MeshTransport

from .releases import ReleaseBindings


def inference_application(
    releases: ReleaseBindings,
    *,
    data_tls: ssl.SSLContext,
    bridge_tls: ssl.SSLContext,
    verify: Callable[[Request, str], bool],
    data_socket: Path | None = None,
    bridge_socket: Path | None = None,
) -> FastAPI:
    # No inference listener is constructed from missing artifact/tokenizer/
    # function evidence. Manual Core/Data surfaces remain independently usable.
    releases.release("worker_summary")
    if releases.manifest is None:
        raise ValueError("Admitted exact model manifest required")

    def bridge_egress() -> MeshTransport | None:
        if bridge_socket is None:
            return None
        return MeshTransport(bridge_socket, "https://host-inference-bridge:8443")

    data = DataTransport(
        data_tls,
        transport=(
            MeshTransport(data_socket, "https://data:8443") if data_socket is not None else None
        ),
    )
    authority = HttpContextAuthority(data)
    bridge = HttpBridge(bridge_tls, transport=bridge_egress())
    counter = HttpTokenCounter(bridge_tls, releases.manifest, transport=bridge_egress())
    gateway = InferenceGateway(
        releases.manifest,
        release_verified=releases.current,
        counter=counter,
        bridge=bridge,
        ledger=HttpJobLedger(data),
        broker_current=authority.current,
    )
    app = create_app(gateway, verify, authority.resolve)
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            counter.close()
            bridge.close()
            data.close()

    app.router.lifespan_context = lifespan
    return app
