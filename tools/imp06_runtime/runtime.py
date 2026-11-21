"""Explicit runtime composition, restricted to the authenticated Core broker."""

import ssl
from pathlib import Path

from care_link_runtime import HttpBrokerTransport, RuntimeClient
from care_link_runtime.worker import RuntimeWorker

from tools.imp02_application.mesh import MeshTransport


def runtime_worker(
    tls: ssl.SSLContext, *, core_socket: Path | None = None
) -> tuple[RuntimeWorker, HttpBrokerTransport]:
    transport = HttpBrokerTransport(
        tls,
        transport=(
            MeshTransport(core_socket, "https://core:8443") if core_socket is not None else None
        ),
    )
    return RuntimeWorker(RuntimeClient(transport), transport.poll_work), transport
