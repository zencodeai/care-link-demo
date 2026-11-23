"""Start exactly one independently provisioned IMP-10 protected role."""

import argparse
import os
from pathlib import Path

from care_link_workload_trust import SOCKET_PEER_SCOPE_KEY, SocketPeer
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from tools.imp03_runtime.compose import Composition
from tools.imp03_runtime.config import ROLES, Record, integer, load, text
from tools.imp06_runtime.role_process import serve_backend

PROTECTED_PROFILE = "imp10-protected"
PROTECTED_ROLES = (*ROLES, "receiver", "training", "help")


def application(role: str, config: Record) -> ASGIApp:
    if role not in PROTECTED_ROLES or config.get("session") != PROTECTED_PROFILE:
        raise ValueError("An explicit IMP-10 protected profile and role are required")
    uid, proxy_uid = integer(config, "uid"), integer(config, "proxy_uid")
    if uid == 0 or uid != os.geteuid() or uid == proxy_uid or text(config, "role") != role:
        raise ValueError("The role, process owner, and independent proxy must match")
    if role == "help":
        from tools.imp02_application.__main__ import compose

        help_app = compose("help", config)

        async def protected_help(scope: Scope, receive: Receive, send: Send) -> None:
            peer = scope.get(SOCKET_PEER_SCOPE_KEY)
            if scope["type"] == "http" and (
                not isinstance(peer, SocketPeer) or peer.uid != proxy_uid
            ):
                await JSONResponse({"state": "workload_denied"}, status_code=403)(
                    scope, receive, send
                )
                return
            await help_app(scope, receive, send)

        return protected_help
    return Composition(config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=PROTECTED_ROLES, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.config.is_absolute():
            raise ValueError("An absolute owner-only configuration path is required")
        cfg = load(args.config)
        backend = Path(text(cfg, "backend_socket"))
        if not backend.is_absolute():
            raise ValueError("An absolute protected socket path is required")
        serve_backend(
            application(args.role, cfg),
            backend_socket=backend,
            proxy_uid=integer(cfg, "proxy_uid"),
        )
    except (KeyError, OSError, ValueError):
        # Configurations contain database and identity credentials.
        raise SystemExit("IMP-10 protected startup denied by configuration or custody") from None


if __name__ == "__main__":
    main()
