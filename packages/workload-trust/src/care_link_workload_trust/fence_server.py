"""Kernel-authenticated restriction custodian: readers cannot append or unfence."""

import json
import os
import socketserver
import stat
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import cast

from .fence import FenceState, FenceStore, TrustDenied
from .fence_protocol import valid_command
from .socket_custody import SocketCustody
from .unix_server import peer_uid


def state_wire(state: FenceState) -> dict[str, object]:
    return {
        "generation": state.generation,
        "allowed": sorted(state.allowed),
        "denied": sorted(state.denied),
        "commands": [list(pair) for pair in state.commands],
        "head": state.head,
    }


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise TrustDenied("duplicate fence field")
        value[key] = item
    return value


class FenceHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(1)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _request(self) -> None:
        server = cast(FenceServer, self.server)
        try:
            uid = peer_uid(self.connection)
            if uid is None or uid not in server.read_uids | {server.restrict_uid}:
                raise TrustDenied("fence peer denied")
            if self.headers.get("transfer-encoding") or len(self.headers) > 16:
                raise TrustDenied("invalid fence protocol")
            lengths = self.headers.get_all("content-length", [])
            if len(lengths) > 1:
                raise TrustDenied("ambiguous fence request")
            size = int(lengths[0]) if lengths else 0
            result: object
            if self.command == "GET" and size == 0 and self.path == "/v1/fence":
                result = state_wire(server.store.read())
            elif (
                self.command == "GET" and size == 0 and self.path.startswith("/v1/fence/commands/")
            ):
                command = self.path.removeprefix("/v1/fence/commands/")
                if not valid_command(command):
                    raise TrustDenied("invalid fence command")
                state = server.store.durable_read()
                target = next((peer for key, peer in state.commands if key == command), None)
                result = (
                    None
                    if target is None
                    else {
                        "command_id": command,
                        "peer": target,
                        "generation": state.generation,
                        "durable": True,
                    }
                )
            elif (
                self.command == "POST"
                and self.path == "/v1/fence/restrict"
                and uid == server.restrict_uid
                and 0 < size <= 4096
                and self.headers.get("content-type") == "application/json"
            ):
                value: object = json.loads(self.rfile.read(size), object_pairs_hook=_unique)
                if not isinstance(value, dict) or set(cast(dict[str, object], value)) != {
                    "peer",
                    "command_id",
                    "expected_generation",
                }:
                    raise TrustDenied("invalid restriction shape")
                data = cast(dict[str, object], value)
                command, peer, generation = (
                    data["command_id"],
                    data["peer"],
                    data["expected_generation"],
                )
                if (
                    not isinstance(command, str)
                    or not valid_command(command)
                    or not isinstance(peer, str)
                    or type(generation) is not int
                    or generation < 0
                ):
                    raise TrustDenied("invalid restriction")
                state = server.store.restrict(peer, command, generation)
                result = {
                    "command_id": command,
                    "peer": peer,
                    "generation": state.generation,
                    "durable": True,
                }
            else:
                raise TrustDenied("fence operation denied")
            raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(200)
        except (TrustDenied, ValueError, OSError, UnicodeError):
            raw = b'{"error":"fence_denied"}'
            self.send_response(403)
            self.close_connection = True
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _request
    do_POST = _request
    do_PUT = _request
    do_DELETE = _request


class FenceServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """Dedicated owner process and group socket; kernel UID selects exact duty.

    No handler provisions identities or resets/releases restrictions. The private
    ledger stays 0700/0600 under the custodian; client UIDs see only this socket.
    """

    daemon_threads = True

    def __init__(
        self,
        path: Path,
        store: FenceStore,
        *,
        owner_uid: int,
        access_gid: int,
        read_uids: frozenset[int],
        restrict_uid: int,
    ) -> None:
        metadata = path.parent.stat()
        if (
            owner_uid != os.geteuid()
            or owner_uid != store.owner_uid
            or owner_uid == restrict_uid
            or owner_uid in read_uids
            or restrict_uid in read_uids
            or restrict_uid < 0
            or not read_uids
            or any(uid < 0 for uid in read_uids)
            or path.parent.is_symlink()
            or metadata.st_uid != owner_uid
            or metadata.st_gid != access_gid
            or stat.S_IMODE(metadata.st_mode) != 0o710
        ):
            raise ValueError(
                "distinct custodian/restrict/read UIDs and protected group socket required"
            )
        self.store, self.read_uids, self.restrict_uid = store, read_uids, restrict_uid
        self.custody = SocketCustody(path, owner_uid, access_gid)
        super().__init__(str(path), FenceHandler, bind_and_activate=False)
        try:
            self.server_bind()
            self.custody.bound()
            os.chown(path, -1, access_gid)
            os.chmod(path, 0o660)
            self.server_activate()
        except BaseException:
            self.server_close()
            raise

    def server_close(self) -> None:
        super().server_close()
        self.custody.close()
