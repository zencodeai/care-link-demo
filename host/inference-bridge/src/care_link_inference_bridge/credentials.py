"""Read an operator-provisioned provider credential in the host bridge only."""

import os
import stat
from pathlib import Path

_MAX_BYTES = 512


def read_api_token(path: Path) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) not in (0o400, 0o600)
            or not 0 < metadata.st_size <= _MAX_BYTES
        ):
            raise ValueError("private host-owned LM Studio credential file required")
        raw = source.read(_MAX_BYTES + 1)
    token = raw.decode("ascii").removesuffix("\n")
    if not token or len(raw) > _MAX_BYTES or any(not "!" <= char <= "~" for char in token):
        raise ValueError("invalid LM Studio credential")
    return token
