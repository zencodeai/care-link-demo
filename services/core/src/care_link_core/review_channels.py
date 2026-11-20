"""Per-page control leases; an authenticated cookie alone never identifies a tab."""

import secrets
import threading
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from care_link_domain import Actor, ManualError

from .manual_channels import ManualChannels

Record = dict[str, object]


@dataclass
class View:
    key: tuple[str, str, str, str]
    handle: str
    revision: int


class ReviewViews:
    def __init__(self, channels: ManualChannels) -> None:
        self.channels = channels
        self._lock = threading.RLock()
        self._views: dict[str, View] = {}
        self._owners: dict[tuple[str, str, str, str], str] = {}
        self._revisions: dict[tuple[str, str, str, str], int] = {}

    @staticmethod
    def key(actor: Actor) -> tuple[str, str, str, str]:
        if not actor.review_run_id or not actor.review_slot_id:
            raise ManualError("manual.review_context_required")
        return (
            actor.review_run_id,
            actor.review_slot_id,
            actor.account_id,
            actor.browser_session_digest,
        )

    def _result(self, view: View) -> Record:
        state: Literal["active", "observer"] = (
            "active" if self._owners.get(view.key) == view.handle else "observer"
        )
        return {"view_id": view.handle, "state": state, "revision": str(self._revisions[view.key])}

    def register(self, actor: Actor) -> Record:
        with self._lock:
            key = self.key(actor)
            view = View(key, str(uuid4()), self._revisions.setdefault(key, 0))
            self._views[view.handle] = view
            if key not in self._owners:
                self._owners[key] = view.handle
                self._revisions[key] += 1
            return self._result(view)

    def inspect(self, actor: Actor, handle: str) -> Record:
        with self._lock:
            view = self._views.get(handle)
            if view is None or view.key != self.key(actor):
                raise ManualError("manual.review_view_unknown", 409)
            return self._result(view)

    def claim(self, actor: Actor, handle: str, revision: str) -> Record:
        with self._lock:
            self.inspect(actor, handle)
            key = self.key(actor)
            if str(self._revisions[key]) != revision:
                raise ManualError("manual.review_view_stale", 409)
            if self._owners.get(key) != handle:
                self.channels.invalidate(actor)
                self._owners[key] = handle
                self._revisions[key] += 1
            return self._result(self._views[handle])

    def require(self, actor: Actor, handle: str) -> None:
        with self._lock:
            view = self._views.get(handle)
            if (
                not handle
                or view is None
                or view.key != self.key(actor)
                or not secrets.compare_digest(self._owners.get(view.key, ""), handle)
            ):
                raise ManualError("manual.review_observer", 409)

    def retire_run(self, run_id: str) -> int:
        """Fence old pages during explicit operator cleanup; preserve other runs."""
        with self._lock:
            handles = [handle for handle, view in self._views.items() if view.key[0] == run_id]
            keys = {self._views[handle].key for handle in handles}
            for key in keys:
                self.channels.invalidate_binding(key[2], key[3])
                self._owners.pop(key, None)
                self._revisions.pop(key, None)
            for handle in handles:
                del self._views[handle]
            return len(handles)
