"""Start one protected role or prepare/provision an independently named IMP-03 target."""

import argparse
import json
import os
import signal
import socket
from collections.abc import Callable
from pathlib import Path
from typing import cast

import uvicorn
from care_link_workload_trust import ProtectedUnixH11Protocol, SocketCustody

from .config import FENCE_RESTRICT_UID, ROLES, integer, load, spiffe, text
from .prepare import check_config, prepare, write


def serve(root: Path, role: str) -> None:
    from .compose import Composition

    cfg = check_config(root, role)
    path = Path(text(cfg, "backend_socket"))
    directory = path.parent
    if (
        not path.is_absolute()
        or path.is_symlink()
        or directory.is_symlink()
        or directory.stat().st_uid != os.geteuid()
        or directory.stat().st_mode & 0o007
    ):
        raise ValueError("Application-owned, proxy-group-only backend directory required")
    app = Composition(cfg)
    custody = SocketCustody(path, os.geteuid(), integer(cfg, "proxy_uid"))
    listener = socket.socket(socket.AF_UNIX)
    pidfile = root / role / "process.json"
    receipt_owned = False
    try:
        if pidfile.exists() or pidfile.is_symlink():
            old = load(pidfile)
            if (
                old.get("role") != role
                or old.get("session") != "imp03-002"
                or old.get("root") != str(root)
            ):
                raise ValueError("Unrecognized stale process receipt")
            # Acquiring SocketCustody already established exclusive listener
            # lease and refused stale endpoint; no live server is displaced.
            pidfile.unlink()
        write(
            pidfile,
            json.dumps(
                {
                    "pid": os.getpid(),
                    "uid": os.geteuid(),
                    "role": role,
                    "root": str(root),
                    "session": "imp03-002",
                    "starttime": process_start(os.getpid()),
                }
            ).encode(),
        )
        receipt_owned = True
        listener.bind(str(path))
        custody.bound()
        os.chown(path, -1, integer(cfg, "proxy_uid"))
        os.chmod(path, 0o660)
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
    finally:
        listener.close()
        custody.close()
        if receipt_owned:
            pidfile.unlink(missing_ok=True)


def process_start(pid: int) -> str:
    return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]


def fault(root: Path, role: str, action: str) -> None:
    if role not in {"identity", "pdp", "journal"}:
        raise ValueError("Only named dependency processes support the local fault barrier")
    cfg = load(root / role / "config.json", owned=False)
    process = load(root / role / "process.json", owned=False)
    pid = integer(process, "pid")
    if (
        process.get("role") != role
        or process.get("root") != str(root)
        or process.get("session") != "imp03-002"
    ):
        raise ValueError("Exact owned process receipt required")
    opener = cast(Callable[[int], int], getattr(os, "pidfd_" + "open"))
    sender = cast(Callable[[int, int], None], getattr(signal, "pidfd_" + "send_signal"))
    descriptor = opener(pid)
    try:
        proc = Path("/proc") / str(pid)
        if proc.stat().st_uid != integer(cfg, "uid"):
            raise ValueError("Process UID differs from assigned custodian")
        command = (proc / "cmdline").read_bytes().split(b"\0")
        expected = [
            b"-m",
            b"tools.imp03_runtime",
            b"serve",
            b"--root",
            str(root).encode(),
            b"--role",
            role.encode(),
        ]
        if not any(command[i : i + len(expected)] == expected for i in range(len(command))):
            raise ValueError("PID no longer runs the exact leased role command")
        if process.get("starttime") != process_start(pid):
            raise ValueError("Process birth identity differs from receipt")
        sender(descriptor, signal.SIGSTOP if action == "pause" else signal.SIGCONT)
    finally:
        os.close(descriptor)
    print(json.dumps({"role": role, "action": action, "session": "imp03-002"}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--bindings", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--assign-ownership", action="store_true")
    renderer = commands.add_parser("render-mesh")
    renderer.add_argument("--bindings", type=Path, required=True)
    renderer.add_argument("--output", type=Path, required=True)
    trust_parser = commands.add_parser("trust")
    trust_parser.add_argument("--role", choices=("authorization", "fence"), required=True)
    trust_parser.add_argument("--config", type=Path, required=True)
    for name in ("serve", "check"):
        command = commands.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--role", choices=ROLES, required=True)
    provision_parser = commands.add_parser("provision")
    provision_parser.add_argument("--root", type=Path, required=True)
    provision_parser.add_argument("--admin-config", type=Path, required=True)
    restriction = commands.add_parser("restrict")
    restriction.add_argument("--fence-socket", type=Path, required=True)
    restriction.add_argument("--fence-uid", type=int, required=True)
    restriction.add_argument("--peer", choices=ROLES, required=True)
    restriction.add_argument("--command-id", required=True)
    restriction.add_argument("--expected-generation", type=int, required=True)
    faults = commands.add_parser("fault")
    faults.add_argument("--root", type=Path, required=True)
    faults.add_argument("--role", choices=("identity", "pdp", "journal"), required=True)
    faults.add_argument("--action", choices=("pause", "resume"), required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(load(args.bindings), args.output, assign_ownership=args.assign_ownership)
    elif args.command == "render-mesh":
        from .mesh import render
        from .prepare import validate_binding

        binding = load(args.bindings)
        validate_binding(binding)
        render(binding, args.output)
    elif args.command == "trust":
        from .trust import serve as trust_serve

        trust_serve(args.role, load(args.config))
    elif args.command == "provision":
        from .provision import provision

        provision(args.root, load(args.admin_config))
    elif args.command == "restrict":
        from care_link_workload_trust import UnixFenceClient

        if os.geteuid() != FENCE_RESTRICT_UID:
            raise ValueError("Separate restriction custodian UID required")
        receipt = UnixFenceClient(args.fence_socket, args.fence_uid).restrict(
            spiffe(args.peer), args.command_id, args.expected_generation
        )
        print(
            json.dumps(
                {
                    "command_id": receipt.command_id,
                    "generation": receipt.generation,
                    "durable": receipt.durable,
                }
            )
        )
    elif args.command == "check":
        from .compose import Composition

        cfg = check_config(args.root, args.role)
        app = Composition(cfg)
        for client in app.clients:
            client.close()
        print(
            json.dumps({"role": args.role, "configuration": "valid", "live_trust": "not_checked"})
        )
    elif args.command == "serve":
        serve(args.root, args.role)
    else:
        fault(args.root, args.role, args.action)


if __name__ == "__main__":
    main()
