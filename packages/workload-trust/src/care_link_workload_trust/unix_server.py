"""HTTP ext_authz listener available only on an owner-protected Unix socket."""

import ctypes
import os
import socket
import socketserver
import stat
import struct
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

from .fence import TrustDenied
from .socket_custody import SocketCustody
from .verification import WorkloadEnforcer


@runtime_checkable
class PeerSocket(Protocol):
    @property
    def family(self) -> int: ...
    def fileno(self) -> int: ...
    def getsockopt(self, level: int, option: int, length: int) -> bytes: ...


class _GetPeerEid(Protocol):
    argtypes: list[object]
    restype: object

    def __call__(self, fd: int, uid: object, gid: object) -> int: ...


def peer_uid(connection: PeerSocket) -> int | None:
    """OS kernel credentials, never source IP or a caller-supplied HTTP header."""
    try:
        if sys.platform.startswith("linux"):
            option: object = getattr(socket, "SO_PEERCRED", None)
            if not isinstance(option, int):
                return None
            _pid, uid, _gid = struct.unpack(
                "3i", connection.getsockopt(socket.SOL_SOCKET, option, struct.calcsize("3i"))
            )
            return uid
        if sys.platform == "darwin":
            libc = ctypes.CDLL(None, use_errno=True)
            function = cast(_GetPeerEid, libc.getpeereid)
            function.argtypes = [
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(ctypes.c_uint),
            ]
            function.restype = ctypes.c_int
            uid, gid = ctypes.c_uint(), ctypes.c_uint()
            if function(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0:
                return uid.value
        return None
    except (OSError, ValueError, struct.error, AttributeError):
        return None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(0.5)

    def log_message(self, format: str, *args: object) -> None:
        # No raw headers, paths, certificates or identities in default access logs.
        return

    def _check(self) -> None:
        server = cast(AuthorizationServer, self.server)
        headers = self.headers.get_all("x-forwarded-client-cert", [])
        try:
            if (
                len(headers) != 1
                or len(self.headers) > 32
                or self.headers.get("transfer-encoding")
                or int(self.headers.get("content-length", "0")) != 0
            ):
                raise TrustDenied("invalid authorization request")
            result = server.enforcer.authorize(
                peer_uid(self.connection), self.command, self.path, headers[0]
            )
            self.send_response(200)
            self.send_header("x-care-link-verified-spiffe", result.spiffe_id)
            self.send_header("x-care-link-fence-generation", str(result.fence_generation))
            self.send_header("x-care-link-certificate-digest", result.certificate_digest)
            self.send_header(
                "x-care-link-certificate-expires-at",
                result.certificate_expires_at.isoformat().replace("+00:00", "Z"),
            )
        except (TrustDenied, ValueError):
            self.send_response(403)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.close_connection = True

    do_GET = _check
    do_POST = _check
    do_PUT = _check
    do_PATCH = _check
    do_DELETE = _check
    do_HEAD = _check
    do_OPTIONS = _check


class AuthorizationServer(socketserver.UnixStreamServer):
    """Blocking local server; composition root owns lifecycle and process identity.

    It only recovers its own refused stale socket under an exclusive file lease.
    The containing 0710 owner/proxy-access-group directory and 0660 socket
    permit a distinct proxy UID to connect. Group membership never grants
    authorization: the OS peer UID must match the exact proxy UID per request.
    The group's membership and backend socket isolation remain host-qualified.
    """

    allow_reuse_address = False

    def __init__(
        self, path: Path, enforcer: WorkloadEnforcer, owner_uid: int, proxy_gid: int
    ) -> None:
        metadata = path.parent.stat()
        if (
            metadata.st_uid != owner_uid
            or metadata.st_gid != proxy_gid
            or stat.S_IMODE(metadata.st_mode) != 0o710
            or path.parent.is_symlink()
            or owner_uid == enforcer.proxy_uid
            or proxy_gid < 0
        ):
            raise ValueError(
                "distinct proxy UID and protected owner/group Unix socket custody required"
            )
        self.enforcer = enforcer
        self.custody = SocketCustody(path, owner_uid, proxy_gid)
        super().__init__(str(path), _Handler, bind_and_activate=False)
        try:
            self.server_bind()
            self.custody.bound()
            os.chown(path, -1, proxy_gid)
            os.chmod(path, 0o660)
            self.server_activate()
        except BaseException:
            self.server_close()
            raise

    def server_close(self) -> None:
        super().server_close()
        self.custody.close()
