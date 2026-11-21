"""Disposable container end of the G-06 host-only provider relay."""

import json
import os
import socket
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import cast

from care_link_inference_bridge import TokenReceipt, create_app
from care_link_workload_trust import BackendVerifier, socket_peer
from care_link_workload_trust.unix_server import PeerSocket
from fastapi import FastAPI

from tools.imp06_verification import role_topology_processes as mesh
from tools.imp06_verification.g06_protected_wire import (
    EXECUTE,
    TOKENIZE_PATH,
    Record,
    checked_request,
    object_record,
    read_frame,
    tokenize_body,
    write_frame,
)

RELAY_PATH = Path(mesh.BASE + "/backend/host-provider.sock")


class HostRelay:
    """Forward only the bounded test case after the standard protected app verifier."""

    def invoke(self, operation: str, body: Record, timeout: float) -> Record:
        request: Record = {"operation": operation, "body": body}
        checked_request(request, operation)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(timeout)
            connection.connect(str(RELAY_PATH))
            with connection.makefile("rb") as reader, connection.makefile("wb") as writer:
                write_frame(writer, request)
                response = read_frame(reader)
        if set(response) != {"status", "body"} or response["status"] != 200:
            raise OSError("host qualification bridge denied the relay request")
        return object_record(response["body"])

    def count(self, messages: Sequence[Mapping[str, str]]) -> TokenReceipt:
        body = self.invoke(TOKENIZE_PATH, tokenize_body(messages), 8)
        return TokenReceipt(
            str(body["model_identifier"]),
            str(body["loaded_model_id"]),
            str(body["artifact_digest"]),
            str(body["tokenizer_digest"]),
            str(body["template_digest"]),
            cast(int, body["model_window"]),
            cast(int, body["input_tokens"]),
            cast(int, body["template_overhead"]),
            str(body["content_digest"]),
        )

    def complete(self, payload: Record, deadline: datetime) -> bytes:
        body = self.invoke(
            EXECUTE,
            {"payload": payload, "deadline": deadline.isoformat().replace("+00:00", "Z")},
            28,
        )
        return json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode()


def bridge(verify: BackendVerifier) -> FastAPI:
    relay = HostRelay()
    return create_app(relay, verify, counter=relay)


def courier() -> None:
    with socket.socket(socket.AF_UNIX) as listener:
        listener.settimeout(50)
        old_umask = os.umask(0o177)
        try:
            listener.bind(str(RELAY_PATH))
        finally:
            os.umask(old_umask)
        try:
            listener.listen(1)
            for operation in (TOKENIZE_PATH, EXECUTE):
                connection, _ = listener.accept()
                with connection:
                    if socket_peer(cast(PeerSocket, connection)).uid != os.geteuid():
                        raise PermissionError("exact bridge custodian required")
                    connection.settimeout(30)
                    with connection.makefile("rb") as reader, connection.makefile("wb") as writer:
                        request = read_frame(reader)
                        checked_request(request, operation)
                        write_frame(sys.stdout.buffer, request)
                        write_frame(writer, read_frame(sys.stdin.buffer))
        finally:
            RELAY_PATH.unlink(missing_ok=True)


def main() -> None:
    if sys.argv[1:] == ["courier"]:
        courier()
    elif sys.argv[1:] == ["courier-ready"]:
        raise SystemExit(0 if RELAY_PATH.is_socket() else 1)
    else:
        mesh.bridge = bridge
        mesh.main()


if __name__ == "__main__":
    main()
