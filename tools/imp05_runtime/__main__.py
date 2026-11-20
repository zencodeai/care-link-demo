"""Serve one explicitly provisioned IMP-05 role through its protected Unix socket."""

import argparse
import os
import socket
from pathlib import Path

import uvicorn
from care_link_workload_trust import ProtectedUnixH11Protocol, SocketCustody

from tools.imp03_runtime.compose import Composition
from tools.imp03_runtime.config import ROLES, Record, integer, load, text


def configuration(path: Path) -> Record:
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("Absolute owner-only role configuration required")
    cfg = load(path)
    role = text(cfg, "role")
    if (
        role not in (*ROLES, "receiver")
        or cfg.get("session") != "imp05-001"
        or cfg.get("referral_enabled") is not True
        or integer(cfg, "uid") != os.geteuid()
    ):
        raise ValueError("Exact IMP-05 role, feature and custodian binding required")
    allowed_credentials: dict[str, set[str]] = {
        "core": {"core_signing_key"},
        "data": {"store_dsn", "content_key", "cursor_key"},
        "receiver": {"store_dsn", "content_key"},
        "identity": {"store_dsn", "custody_key", "signing_key", "oidc"},
        "pdp": set(),
        "journal": {"signing_key"},
    }
    credentials = {
        "store_dsn",
        "content_key",
        "cursor_key",
        "core_signing_key",
        "custody_key",
        "signing_key",
        "oidc",
    }
    if (set(cfg) & credentials) - allowed_credentials[role]:
        raise ValueError("Cross-role credential in process configuration")
    for name in (set(cfg) & credentials) - {"store_dsn", "oidc"}:
        key = Path(text(cfg, name))
        info = key.lstat()
        if (
            key.is_symlink()
            or not key.is_file()
            or info.st_mode & 0o077
            or info.st_uid != os.geteuid()
            or not key.resolve().is_relative_to(path.parent.resolve())
        ):
            raise ValueError("Role-local owner-only key custody required")
    return cfg


def serve(path: Path) -> None:
    cfg = configuration(path)
    endpoint = Path(text(cfg, "backend_socket"))
    if (
        not endpoint.is_absolute()
        or endpoint.parent.is_symlink()
        or endpoint.parent.stat().st_uid != os.geteuid()
        or endpoint.parent.stat().st_mode & 0o007
    ):
        raise ValueError("Exclusive protected role socket directory required")
    application = Composition(cfg)
    custody = SocketCustody(endpoint, os.geteuid(), integer(cfg, "proxy_uid"))
    listener = socket.socket(socket.AF_UNIX)
    try:
        listener.bind(str(endpoint))
        custody.bound()
        os.chown(endpoint, -1, integer(cfg, "proxy_uid"))
        os.chmod(endpoint, 0o660)
        listener.listen(128)
        uvicorn.Server(
            uvicorn.Config(
                application,
                http=ProtectedUnixH11Protocol,
                proxy_headers=False,
                access_log=False,
                server_header=False,
                log_level="critical",
                timeout_graceful_shutdown=3,
            )
        ).run(sockets=[listener])
    finally:
        listener.close()
        custody.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    serve(parser.parse_args().config)


if __name__ == "__main__":
    main()
