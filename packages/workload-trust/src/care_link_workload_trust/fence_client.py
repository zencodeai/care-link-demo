"""Fresh cross-custodian fence calls with kernel-verified server identity."""

import http.client
import json
import socket
from pathlib import Path
from typing import cast

from .fence import FenceState, TrustDenied
from .fence_protocol import FenceReceipt, valid_command
from .unix_server import PeerSocket, peer_uid


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path: Path, server_uid: int) -> None:
        super().__init__("localhost", timeout=1)
        self.path, self.server_uid = path, server_uid

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(1)
            connection.connect(str(self.path))
            if peer_uid(cast(PeerSocket, connection)) != self.server_uid:
                raise TrustDenied("unverified fence custodian")
            self.sock = connection
        except BaseException:
            connection.close()
            raise


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise TrustDenied("ambiguous fence response")
        value[key] = item
    return value


def _strings(value: object) -> frozenset[str]:
    if not isinstance(value, list):
        raise TrustDenied("invalid fence response")
    items = cast(list[object], value)
    if any(not isinstance(item, str) for item in items):
        raise TrustDenied("invalid fence response")
    result = frozenset(cast(list[str], items))
    if len(result) != len(items):
        raise TrustDenied("duplicate fence peer")
    return result


class UnixFenceClient:
    """One fresh protected connection per call; never caches positive authority."""

    def __init__(self, path: Path, server_uid: int) -> None:
        if not path.is_absolute() or server_uid < 0:
            raise ValueError("explicit fence socket/custodian required")
        self.path, self.server_uid = path, server_uid

    def _call(self, method: str, path: str, body: dict[str, object] | None = None) -> object:
        connection = _UnixHTTP(self.path, self.server_uid)
        try:
            raw = None if body is None else json.dumps(body, separators=(",", ":")).encode()
            connection.request(method, path, raw, {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200 or response.getheader("transfer-encoding"):
                raise TrustDenied("fence call denied")
            size = int(response.getheader("content-length", "-1"))
            if not 0 <= size <= 1024 * 1024:
                raise TrustDenied("invalid fence response size")
            payload = response.read(size + 1)
            if len(payload) != size:
                raise TrustDenied("incomplete fence response")
            result: object = json.loads(payload, object_pairs_hook=_unique)
            return result
        except (OSError, ValueError, http.client.HTTPException) as error:
            raise TrustDenied("fence call unavailable") from error
        finally:
            connection.close()

    def current(self) -> FenceState:
        raw = self._call("GET", "/v1/fence")
        if not isinstance(raw, dict):
            raise TrustDenied("invalid fence state")
        value = cast(dict[str, object], raw)
        if set(value) != {"generation", "allowed", "denied", "commands", "head"}:
            raise TrustDenied("invalid fence state fields")
        generation, head, commands = value["generation"], value["head"], value["commands"]
        allowed, denied = _strings(value["allowed"]), _strings(value["denied"])
        if (
            type(generation) is not int
            or generation < 0
            or not isinstance(head, str)
            or len(head) != 64
            or not isinstance(commands, list)
            or not denied <= allowed
        ):
            raise TrustDenied("invalid fence state values")
        pairs: list[tuple[str, str]] = []
        for item in cast(list[object], commands):
            if not isinstance(item, list) or len(cast(list[object], item)) != 2:
                raise TrustDenied("invalid fence command pair")
            command, peer = cast(list[object], item)
            if not isinstance(command, str) or not isinstance(peer, str) or peer not in denied:
                raise TrustDenied("invalid fence command values")
            pairs.append((command, peer))
        if len(pairs) != generation or len({key for key, _ in pairs}) != generation:
            raise TrustDenied("inconsistent fence generation")
        return FenceState(generation, allowed, denied, tuple(pairs), head)

    def read(self) -> FenceState:
        """FenceReader compatibility for backend/ext-authz enforcement."""
        return self.current()

    @staticmethod
    def _receipt(raw: object, command_id: str, peer: str | None = None) -> FenceReceipt:
        if not isinstance(raw, dict):
            raise TrustDenied("invalid fence receipt")
        value = cast(dict[str, object], raw)
        if set(value) != {"command_id", "peer", "generation", "durable"}:
            raise TrustDenied("invalid fence receipt fields")
        generation, target = value["generation"], value["peer"]
        if (
            value["command_id"] != command_id
            or not isinstance(target, str)
            or (peer is not None and peer != target)
            or type(generation) is not int
            or generation < 1
            or value["durable"] is not True
        ):
            raise TrustDenied("unconfirmed fence receipt")
        return FenceReceipt(command_id, target, generation, True)

    def restrict(self, peer: str, command_id: str, expected_generation: int) -> FenceReceipt:
        if not valid_command(command_id):
            raise ValueError("canonical restriction command required")
        raw = self._call(
            "POST",
            "/v1/fence/restrict",
            {
                "peer": peer,
                "command_id": command_id,
                "expected_generation": expected_generation,
            },
        )
        return self._receipt(raw, command_id, peer)

    def receipt(self, command_id: str) -> FenceReceipt | None:
        if not valid_command(command_id):
            raise ValueError("canonical restriction command required")
        raw = self._call("GET", "/v1/fence/commands/" + command_id)
        return None if raw is None else self._receipt(raw, command_id)
