"""Temporary lab address routing while retaining verified HTTPS authority/SNI."""

import ssl

import httpx


class PinnedAddressTransport(httpx.BaseTransport):
    def __init__(self, origin: str, address: str, ca_file: str) -> None:
        self.origin = httpx.URL(origin)
        if self.origin.scheme != "https" or self.origin.path != "/" or self.origin.userinfo:
            raise ValueError("Exact pinned HTTPS authority required")
        self.address = address
        self.transport = httpx.HTTPTransport(verify=ssl.create_default_context(cafile=ca_file))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (request.url.scheme, request.url.host, request.url.port) != (
            self.origin.scheme,
            self.origin.host,
            self.origin.port,
        ):
            raise ValueError("Unconfigured TLS authority")
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = self.origin.host
        routed = httpx.Request(
            request.method,
            request.url.copy_with(host=self.address),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        return self.transport.handle_request(routed)

    def close(self) -> None:
        self.transport.close()
