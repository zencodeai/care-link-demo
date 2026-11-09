"""Pinned Uvicorn 0.38.0 H11 connection hook for protected backend Unix sockets."""

import asyncio
import socket
from collections.abc import MutableMapping
from typing import cast

from uvicorn._types import ASGI3Application, ASGIReceiveCallable, ASGISendCallable, Scope
from uvicorn.protocols.http.h11_impl import H11Protocol

from .backend import SOCKET_PEER_SCOPE_KEY, socket_peer
from .unix_server import PeerSocket


class ProtectedUnixH11Protocol(H11Protocol):
    """Capture kernel identity once for each actual accepted Unix connection.

    The backend verifier still checks that exact UID, current fence and expiry on
    each operation. Proxy headers never create the scope capsule. TCP, unknown
    socket APIs and unverified local peers cannot create a trusted capsule.
    """

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        if not isinstance(transport, asyncio.Transport):
            transport.close()
            return
        super().connection_made(transport)
        connection: object = transport.get_extra_info("socket")
        capsule = (
            socket_peer(connection)
            if isinstance(connection, PeerSocket) and connection.family == socket.AF_UNIX
            else None
        )
        application = cast(ASGI3Application, self.app)

        async def trusted_scope(
            scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable
        ) -> None:
            mutable = cast(MutableMapping[str, object], scope)
            mutable.pop(SOCKET_PEER_SCOPE_KEY, None)
            if capsule is not None and capsule.uid is not None:
                mutable[SOCKET_PEER_SCOPE_KEY] = capsule
            await application(scope, receive, send)

        self.app = trusted_scope
        if capsule is None or capsule.uid is None:
            transport.close()
