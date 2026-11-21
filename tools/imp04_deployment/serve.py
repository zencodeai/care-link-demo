"""Protected Unix serving and bounded loopback bridges for the IMP-04 target."""

from __future__ import annotations

import argparse
import json
import os
import socket
import threading
from pathlib import Path
from typing import cast

import uvicorn
from care_link_data import AESGCMContentCipher, ManualService, PostgresStore
from care_link_data.app import SignedGatewaySecurity, create_app
from care_link_data.directory_admission import VerifiedDirectoryAdmission
from care_link_data.store import Transaction
from care_link_domain import Actor
from care_link_policy_input import DelegationVerifier
from care_link_workload_trust import ProtectedUnixH11Protocol, SocketCustody
from starlette.types import ASGIApp

from tools.imp02_application.config import public_key
from tools.imp03_runtime.__main__ import process_start
from tools.imp03_runtime.compose import Composition
from tools.imp03_runtime.config import ROLES, Record, integer, load, record, text
from tools.imp03_runtime.prepare import check_config, write
from tools.imp03_runtime.remote import HttpChannels, HttpJournal, HttpPolicy
from tools.imp03_shared.relay import ThreadedLoopbackBridge

from .diagnostics import install
from .qualification import DIRECTORY, TimingBarrier

ROOT = Path("/run/care-link-imp03-002/configuration")


class QualificationPolicy:
    def __init__(
        self, delegate: HttpPolicy, barrier: TimingBarrier, local: threading.local
    ) -> None:
        self.delegate, self.barrier, self.local = delegate, barrier, local

    def evaluate(self, request: Record) -> Record:
        actor = record(request["actor"])
        self.local.operation_id = text(request, "operation_id")
        self.barrier.enter(
            "before_policy",
            text(request, "action"),
            text(actor, "principal_id"),
            self.local.operation_id,
        )
        return self.delegate.evaluate(request)


class QualificationService(ManualService):
    qualification_barrier: TimingBarrier
    qualification_local: threading.local

    def _check_output_authority(
        self,
        tx: Transaction,
        actor: Actor,
        action: str,
        result: Record,
        snapshot: Record,
        policy_scope: Record,
        arguments: Record | None = None,
    ) -> None:
        self.qualification_barrier.enter(
            "before_final_output",
            action,
            actor.account_id,
            str(getattr(self.qualification_local, "operation_id", "")),
        )
        super()._check_output_authority(
            tx, actor, action, result, snapshot, policy_scope, arguments
        )


class QualificationComposition(Composition):
    def _compose(self) -> ASGIApp:
        if self.role != "data":
            raise ValueError("Timing adapter is exclusive to the new data target")
        cfg = self.config
        if cfg.get("imp04_target") != "care-link-imp04-002":
            raise ValueError("Exact IMP-04 target required")
        barrier = TimingBarrier(DIRECTORY)
        local = threading.local()
        identity = self.identity()
        admissions = cast(list[Record], cfg.get("directory_signed_admissions", []))
        pins = record(cfg.get("directory_trusted_keys", {}))
        admission = VerifiedDirectoryAdmission(
            admissions, {key: public_key(str(path)) for key, path in pins.items()}
        )
        service = QualificationService(
            PostgresStore(text(cfg, "store_dsn")),
            identity,
            QualificationPolicy(HttpPolicy(*self.remote("pdp")), barrier, local),
            HttpJournal(*self.remote("journal"), public_key(text(cfg, "journal_public_key"))),
            AESGCMContentCipher(Path(text(cfg, "content_key")).read_bytes()),
            channel=HttpChannels(*self.remote("core")),
            disclosure_templates=cast(dict[str, Record], cfg["disclosures"]),
            cursor_key=Path(text(cfg, "cursor_key")).read_bytes(),
            directory_admission=admission,
        )
        service.qualification_barrier, service.qualification_local = barrier, local
        delegation = DelegationVerifier(
            public_key(text(cfg, "core_public_key")),
            public_key(text(cfg, "identity_public_key")),
            identity.resolve,
        )
        return create_app(service, SignedGatewaySecurity(delegation, self.verify))


def serve(root: Path, role: str) -> None:
    if root != ROOT or role not in ROLES:
        raise ValueError("Exact IMP-04 container configuration root/role required")
    cfg = check_config(root, role)
    if cfg.get("imp04_target") != "care-link-imp04-002":
        raise ValueError("Target identity must be explicitly bound")
    enabled = os.environ.get("CARE_LINK_IMP04_QUALIFICATION")
    if enabled and (enabled != "plans-002" or role != "data"):
        raise ValueError("Wrong qualification adapter activation")
    app = QualificationComposition(cfg) if enabled else Composition(cfg)
    install(root, role, app.clients)
    path = Path(text(cfg, "backend_socket"))
    parent = path.parent
    if (
        not path.is_absolute()
        or path.is_symlink()
        or parent.is_symlink()
        or parent.stat().st_uid != os.geteuid()
        or parent.stat().st_mode & 0o007
    ):
        raise ValueError("Application-owned protected backend parent required")
    custody = SocketCustody(path, os.geteuid(), integer(cfg, "proxy_uid"))
    listener = socket.socket(socket.AF_UNIX)
    receipt = root / role / "process.json"
    receipt_owned = False
    try:
        if receipt.exists():
            old = load(receipt)
            if (
                old.get("root") != str(root)
                or old.get("role") != role
                or old.get("target") != "care-link-imp04-002"
            ):
                raise ValueError("Unknown stale serving receipt")
            receipt.unlink()
        write(
            receipt,
            json.dumps(
                {
                    "pid": os.getpid(),
                    "uid": os.geteuid(),
                    "role": role,
                    "root": str(root),
                    "session": "imp03-002",
                    "target": "care-link-imp04-002",
                    "starttime": process_start(os.getpid()),
                    "qualification_enabled": bool(enabled),
                }
            ).encode(),
        )
        receipt_owned = True
        listener.bind(str(path))
        custody.bound()
        os.chown(path, -1, integer(cfg, "proxy_uid"))
        os.chmod(path, 0o660)
        listener.listen(128)
        uvicorn.Server(
            uvicorn.Config(
                app,
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
        if receipt_owned:
            receipt.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--forward", nargs=3, action="append", default=[])
    args = parser.parse_args()
    bridges: list[ThreadedLoopbackBridge] = []
    try:
        for port, uid, path in args.forward:
            bridge = ThreadedLoopbackBridge(Path(path), int(port), server_uid=int(uid))
            bridges.append(bridge)
            bridge.start()
        serve(args.root, args.role)
    finally:
        for bridge in bridges:
            bridge.close()


if __name__ == "__main__":
    main()
