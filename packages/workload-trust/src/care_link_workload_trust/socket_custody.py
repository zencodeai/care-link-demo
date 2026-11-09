"""Exclusive listener lease and recovery of only an owned, refused stale socket."""

import errno
import fcntl
import os
import socket
import stat
from pathlib import Path

from .fence import TrustDenied


class SocketCustody:
    def __init__(self, path: Path, owner_uid: int, access_gid: int) -> None:
        self.path, self.owner_uid = path, owner_uid
        self.directory_fd = -1
        self.lease_fd = -1
        self.bound_identity: tuple[int, int] | None = None
        try:
            self.directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            metadata = os.fstat(self.directory_fd)
            if (
                owner_uid != os.geteuid()
                or metadata.st_uid != owner_uid
                or metadata.st_gid != access_gid
                or stat.S_IMODE(metadata.st_mode) != 0o710
            ):
                raise TrustDenied("unsafe listener custody")
            self.lease_fd = os.open(
                "." + path.name + ".lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=self.directory_fd,
            )
            lease = os.fstat(self.lease_fd)
            if (
                lease.st_uid != owner_uid
                or not stat.S_ISREG(lease.st_mode)
                or stat.S_IMODE(lease.st_mode) != 0o600
            ):
                raise TrustDenied("unsafe listener lease")
            fcntl.flock(self.lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._recover()
        except BaseException:
            self.close()
            raise

    def _recover(self) -> None:
        try:
            old = os.stat(self.path.name, dir_fd=self.directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(old.st_mode) or old.st_uid != self.owner_uid:
            raise TrustDenied("listener path is not an owned socket")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(0.25)
            try:
                connection.connect(str(self.path))
            except OSError as error:
                if error.errno != errno.ECONNREFUSED:
                    raise TrustDenied("listener state not established") from error
            else:
                raise TrustDenied("listener already active")
        finally:
            connection.close()
        current = os.stat(self.path.name, dir_fd=self.directory_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (old.st_dev, old.st_ino):
            raise TrustDenied("listener changed during recovery")
        os.unlink(self.path.name, dir_fd=self.directory_fd)

    def bound(self) -> None:
        metadata = os.stat(self.path.name, dir_fd=self.directory_fd, follow_symlinks=False)
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != self.owner_uid:
            raise TrustDenied("listener binding custody changed")
        self.bound_identity = (metadata.st_dev, metadata.st_ino)

    def close(self) -> None:
        if self.bound_identity is not None and self.directory_fd >= 0:
            try:
                metadata = os.stat(self.path.name, dir_fd=self.directory_fd, follow_symlinks=False)
                if (metadata.st_dev, metadata.st_ino) == self.bound_identity:
                    os.unlink(self.path.name, dir_fd=self.directory_fd)
            except FileNotFoundError:
                pass
            self.bound_identity = None
        if self.lease_fd >= 0:
            os.close(self.lease_fd)
            self.lease_fd = -1
        if self.directory_fd >= 0:
            os.close(self.directory_fd)
            self.directory_fd = -1
