"""Cookie BFF adapter with exact Origin/CSRF verification by fresh identity authority."""

from typing import Protocol

from care_link_domain import Actor, ManualError
from fastapi import Request


class IdentityBrowserPort(Protocol):
    def authenticate(self, raw_session: str) -> Actor: ...
    def csrf(self, actor: Actor, origin: str | None, supplied: str | None) -> None: ...


class CookieSecurity:
    def __init__(
        self, identity: IdentityBrowserPort, *, cookie: str = "__Host-care-link-session"
    ) -> None:
        self.identity = identity
        self.cookie = cookie

    def authenticate(self, request: Request) -> Actor:
        # Reject ambiguous duplicate cookie names before any authority lookup.
        names = [
            item.strip().split("=", 1)[0] for item in request.headers.get("cookie", "").split(";")
        ]
        raw = request.cookies.get(self.cookie)
        if names.count(self.cookie) != 1 or not raw:
            raise ManualError("manual.session_required", 401)
        actor = self.identity.authenticate(raw)
        if actor.review_origin and actor.review_origin != "https://" + request.headers.get(
            "host", ""
        ):
            raise ManualError("manual.review_origin_denied")
        return actor

    def csrf(self, request: Request, actor: Actor) -> None:
        self.identity.csrf(
            actor, request.headers.get("origin"), request.headers.get("x-csrf-token")
        )
