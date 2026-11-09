"""Offline managed SQLite page/WAL cleanup, never physical-device erasure."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime

from .model import timestamp


def cleanup_managed_copies(
    connect: Callable[[], sqlite3.Connection], restrict: Callable[[], None], now: datetime
) -> str:
    """Retry safely after committed unlinkage; old reader snapshots stay pending.

    VACUUM rebuilds pages which predate secure_delete activation. Both surrounding
    TRUNCATE checkpoints must finish: an old WAL reader can still possess deleted
    bytes, even when the live SQL rows no longer contain them. A crash before the
    successful status update leaves the transaction's durable pending marker.
    """
    with closing(connect()) as connection:
        state = "pending_error"
        try:
            for vacuum_after in (True, False):
                checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint[0] != 0 or checkpoint[1] != 0 or checkpoint[2] != 0:
                    state = "pending_busy_or_reader"
                    break
                if vacuum_after:
                    connection.execute("VACUUM")
            else:
                state = "complete"
        except sqlite3.Error as error:
            if getattr(error, "sqlite_errorcode", None) in (
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            ):
                state = "pending_busy_or_reader"
        finally:
            restrict()
        # This small post-cleanup record contains no account/request identifiers.
        # A final status WAL frame cannot revive the already-truncated old frames.
        try:
            connection.execute(
                "UPDATE help_managed_copy_cleanup SET state=?,checked_at=? WHERE singleton=1",
                (state, timestamp(now)),
            )
        except sqlite3.Error:
            # The previously committed pending marker remains authoritative.
            return "pending_error"
        finally:
            restrict()
        return state
