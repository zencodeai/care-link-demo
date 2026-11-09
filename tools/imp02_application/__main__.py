"""Run one explicitly selected isolated lab role; no default private authority."""

import argparse
import os
import socket
from pathlib import Path

import httpx
import uvicorn
from care_link_help import (
    HelpConfig,
    HelpService,
    HttpAuthority,
    HttpBrowserSessions,
    SignedReceipts,
    Spool,
)
from care_link_help import create_app as create_help
from care_link_workload_trust import ProtectedUnixH11Protocol, SocketCustody
from fastapi import FastAPI
from starlette.types import ASGIApp

from .browser import add_auth_proxy, add_client, secure_surface
from .config import load, public_key, text
from .identity import IdentityApplication
from .mesh import MeshTransport, explicit_credentials_only


def compose(role: str, config: dict[str, object]) -> ASGIApp:
    if role == "identity":
        return IdentityApplication(config)
    if role == "static":
        from care_link_static import PublicationStore, create_app

        return create_app(
            PublicationStore(
                Path(text(config, "publication_directory")),
                public_key(text(config, "review_public_key")),
                allow_owner_demo=config.get("allow_owner_demo") is True,
            ),
            allow_owner_demo=config.get("allow_owner_demo") is True,
        )
    authority, origin = text(config, "identity_origin"), text(config, "origin")
    client = httpx.Client(
        transport=MeshTransport(Path(text(config, "outbound_socket")), authority),
        cookies=explicit_credentials_only(),
        trust_env=False,
    )
    help_api = None
    if role == "help":
        service = HelpService(
            Spool(Path(text(config, "spool"))),
            HttpAuthority(client, authority),
            SignedReceipts(
                {text(config, "signing_key_id"): public_key(text(config, "signing_public_key"))}
            ),
        )
        help_api = create_help(
            HelpConfig(origin, static_url=text(config, "static_origin") + "/fallback"),
            service,
            HttpBrowserSessions(client, authority, origin),
        )
    elif role != "main":
        raise ValueError("Unknown role")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    add_auth_proxy(app, client, authority, role)
    if role == "main":
        from care_link_core import create_app as create_core

        app.router.routes.extend(create_core().router.routes)
    add_client(app, Path(text(config, "web_directory")), help_surface=role == "help")
    return secure_surface(app, help_api)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("identity", "main", "help", "static"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load(args.config)
    app = compose(args.role, config)
    if args.role == "static" and config.get("public_port") == 8444:
        uvicorn.run(
            app,
            host="0.0.0.0",  # noqa: S104 - loopback-only published container port
            port=8444,
            proxy_headers=False,
            access_log=False,
            server_header=False,
            ssl_certfile=text(config, "tls_certificate"),
            ssl_keyfile=text(config, "tls_private_key"),
        )
        return
    path = Path(text(config, "backend_socket"))
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Absolute protected backend socket required")
    if path.parent.stat().st_uid != os.geteuid() or path.parent.stat().st_mode & 0o007:
        raise ValueError(
            "Backend directory must be application-owned and private to assigned group"
        )
    custody = SocketCustody(path, os.geteuid(), 21002)
    listener = socket.socket(socket.AF_UNIX)
    try:
        listener.bind(str(path))
        custody.bound()
        os.chown(path, -1, 21002)
        os.chmod(path, 0o660)
        listener.listen(128)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                http=ProtectedUnixH11Protocol,
                proxy_headers=False,
                access_log=False,
                server_header=False,
            )
        )
        server.run(sockets=[listener])
    finally:
        listener.close()
        custody.close()


if __name__ == "__main__":
    main()
