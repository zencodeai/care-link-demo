"""Pinned HTTPS authority carried through the protected local Envoy egress socket."""

from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from pathlib import Path
from urllib.request import Request

import httpx


class _NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie: Cookie, request: Request) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: Request) -> bool:
        return False


def explicit_credentials_only() -> CookieJar:
    """Mesh credentials belong to each explicit request, never a shared jar."""
    return CookieJar(policy=_NoCookies())


class MeshTransport(httpx.BaseTransport):
    """Only the exact configured authority can use this workload's mTLS proxy.

    HTTP is confined to the permission-protected Unix socket. Envoy performs
    upstream TLS/SVID verification; this adapter cannot disable network TLS.
    """

    def __init__(self, socket: Path, authority: str) -> None:
        url = httpx.URL(authority)
        if url.scheme != "https" or url.path != "/" or url.query or url.userinfo:
            raise ValueError("Exact mesh HTTPS origin required")
        self.authority = url
        self.transport = httpx.HTTPTransport(uds=str(socket), retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.scheme != self.authority.scheme
            or request.url.host != self.authority.host
            or request.url.port != self.authority.port
        ):
            raise ValueError("Unconfigured mesh authority")
        local = httpx.Request(
            request.method,
            request.url.copy_with(scheme="http"),
            headers=request.headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return self.transport.handle_request(local)

    def close(self) -> None:
        self.transport.close()
