"""Exact public origin routing; labels select a workspace, never actor authority."""

import json
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from care_link_domain import ManualError

Record = dict[str, object]


class ReviewContexts:
    def __init__(self, path: Path, legacy_origin: str) -> None:
        self.path, self.legacy_origin = path, legacy_origin

    def entries(self) -> dict[str, Record]:
        if self.path.is_symlink() or self.path.stat().st_size > 262144:
            raise ManualError("manual.review_registry_invalid", 503)
        value = json.loads(self.path.read_text())
        if not isinstance(value, dict):
            raise ManualError("manual.review_registry_invalid", 503)
        return cast(dict[str, Record], value)

    def origin(self, host: str) -> str:
        origin = "https://" + host
        parsed = urlsplit(origin)
        if (
            parsed.netloc != host
            or parsed.path
            or parsed.username
            or parsed.fragment
            or parsed.query
        ):
            raise ManualError("manual.review_origin_denied")
        if origin != self.legacy_origin and origin not in self.entries():
            raise ManualError("manual.review_origin_denied")
        return origin

    def context(self, host: str) -> Record:
        origin = self.origin(host)
        if origin == self.legacy_origin:
            return {"enabled": False}
        entry = self.entries()[origin]
        if entry.get("state") not in {"active", "closing", "closed"}:
            raise ManualError("manual.review_context_unavailable", 503)
        return {
            "enabled": True,
            "origin": origin,
            "run_id": entry["run_id"],
            "slot_id": entry["slot_id"],
            "account_id": entry["account_id"],
            "role": entry["role"],
            "run_state": entry["state"],
        }
