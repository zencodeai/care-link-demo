"""Temporary local operator transport; no application review is launched."""

import json
import os
import threading
from contextlib import contextmanager

import httpx
import pytest

from tools.imp04_review.operator import OperatorServer, request
from tools.imp04_review.storage import write_json


class Manager:
    target_id = "temporary-test-store"
    environment_id = "synthetic-test"

    def __init__(self):
        self.calls = 0

    def inspect(self):
        self.calls += 1
        return {"state": "absent"}


@contextmanager
def running(tmp_path):
    manager = Manager()
    parent = tmp_path / "operator"
    # macOS Unix path length is bounded; pytest's long hierarchy can exceed it.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="imp04-", dir="/tmp") as temporary:
        from pathlib import Path

        parent = Path(temporary)
        try:
            server = OperatorServer(parent / "operator.sock", manager)
        except PermissionError:
            pytest.skip(
                "Sandbox denies temporary Unix socket binding; handler checks tested in memory"
            )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield manager, server, parent / "operator.sock"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_owner_peer_can_inspect_only_exact_target(tmp_path):
    with running(tmp_path) as (manager, _server, socket):
        config = socket.parent / "config.json"
        write_json(
            config,
            {
                "environment": "synthetic-review",
                "environment_id": manager.environment_id,
                "target_id": manager.target_id,
                "operator_socket": str(socket),
            },
        )
        assert request(config, "inspect") == {"state": "absent"}
        assert manager.calls == 1
        wrong = json.loads(config.read_text())
        wrong["target_id"] = "foreign-target"
        write_json(config, wrong)
        with pytest.raises(httpx.HTTPStatusError):
            request(config, "inspect")
        assert manager.calls == 1


def test_nonowner_peer_is_denied_before_dispatch(tmp_path):
    with running(tmp_path) as (manager, server, socket):
        server.owner_uid = os.geteuid() + 1
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket)), trust_env=False
        ) as client:
            response = client.post(
                "http://operator/internal/plans-review/operator",
                json={
                    "target_id": manager.target_id,
                    "environment_id": manager.environment_id,
                    "command": "inspect",
                },
            )
        assert response.status_code == 503
        assert response.json() == {"state": "operator_unconfirmed"}
        assert manager.calls == 0


@pytest.mark.parametrize("peer", ["owner", "wrong", "tcp", "unknown"])
def test_server_checks_peer_before_any_dispatch(monkeypatch, peer):
    import io
    from types import SimpleNamespace

    from tools.imp04_review.operator import OperatorHandler

    manager = Manager()
    handler = object.__new__(OperatorHandler)
    body = json.dumps(
        {
            "target_id": manager.target_id,
            "environment_id": manager.environment_id,
            "command": "inspect",
        }
    ).encode()
    handler.server = SimpleNamespace(manager=manager, owner_uid=os.geteuid())
    handler.connection = object()
    handler.path = "/internal/plans-review/operator"
    handler.headers = {"content-length": str(len(body)), "content-type": "application/json"}
    handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
    statuses = []
    handler.send_response = statuses.append
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None

    def peer_identity(_connection):
        if peer == "tcp":
            raise OSError("Not an authenticated Unix peer")
        if peer == "unknown":
            return None
        return os.geteuid() if peer == "owner" else os.geteuid() + 1

    monkeypatch.setattr("tools.imp04_review.operator.peer_uid", peer_identity)
    handler.do_POST()
    assert statuses == [200 if peer == "owner" else 503]
    assert manager.calls == (1 if peer == "owner" else 0)
