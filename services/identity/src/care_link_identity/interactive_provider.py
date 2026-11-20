"""Explicitly simulated review authentication, never evidence of provider MFA."""

import secrets
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from threading import RLock

from .crypto import digest, token
from .domain import IdentityError, Principal
from .review_context import ReviewContext
from .session_policy import InteractiveReviewPolicy


class AutomaticReviewProvider:
    """Opaque single-use exchanges behind ordinary identity callback guards."""

    def __init__(
        self,
        policy: InteractiveReviewPolicy,
        contexts: Callable[[], Mapping[str, ReviewContext]],
        clock: Callable[[], datetime],
    ) -> None:
        self.policy, self.contexts, self.clock = policy, contexts, clock
        self._pending: dict[str, tuple[str, str, bool, datetime]] = {}
        self._codes: dict[str, str] = {}
        self._tokens: dict[str, datetime] = {}
        self._lock = RLock()

    def check(self) -> None:
        try:
            current = self.contexts().get(self.policy.context.origin)
        except (OSError, ValueError) as error:
            raise IdentityError("identity.interactive_review_registry_unavailable", 503) from error
        self.policy.check(current, self.clock())

    def authorization_url(self, state: str, nonce: str, verifier: str, fresh: bool) -> str:
        self.check()
        with self._lock:
            now = self.clock()
            self._pending = {key: row for key, row in self._pending.items() if row[3] > now}
            self._codes = {
                key: value for key, value in self._codes.items() if value in self._pending
            }
            if len(self._pending) >= 128:
                raise IdentityError("identity.interactive_review_capacity", 503)
            self._pending[state] = (
                nonce,
                digest(verifier),
                fresh,
                min(now + timedelta(minutes=5), self.policy.expires_at),
            )
        # Consumed inside the server helper. This is not an actual provider URL.
        return self.policy.context.origin + "/__simulated_review/" + state

    def complete(self, authorization_url: str) -> tuple[str, str]:
        self.check()
        prefix = self.policy.context.origin + "/__simulated_review/"
        if not authorization_url.startswith(prefix):
            raise IdentityError("identity.interactive_review_exchange_denied")
        state = authorization_url.removeprefix(prefix)
        with self._lock:
            pending = self._pending.get(state)
            if pending is None or pending[3] <= self.clock() or state in self._codes.values():
                raise IdentityError("identity.interactive_review_exchange_denied")
            code = token()
            self._codes[code] = state
        return state, code

    def exchange(self, code: str, verifier: str, nonce: str, fresh: bool) -> Principal:
        self.check()
        with self._lock:
            state = self._codes.pop(code, None)
            row = self._pending.pop(state, None) if state is not None else None
            now = self.clock()
            if (
                row is None
                or row[3] <= now
                or not secrets.compare_digest(row[0], nonce)
                or not secrets.compare_digest(row[1], digest(verifier))
                or row[2] != fresh
            ):
                raise IdentityError("identity.interactive_review_exchange_denied")
            self._tokens = {key: expiry for key, expiry in self._tokens.items() if expiry > now}
            if len(self._tokens) >= 1024:
                raise IdentityError("identity.interactive_review_capacity", 503)
            access = token()
            self._tokens[digest(access)] = self.policy.expires_at
        subject = self.policy.context.provider_subject
        if subject is None:
            raise IdentityError("identity.interactive_review_actor_denied")
        return Principal(subject, now, True, ("simulated_review",), access, self.policy.expires_at)

    def active(self, access_token: str, subject: str) -> bool:
        self.check()
        with self._lock:
            expiry = self._tokens.get(digest(access_token))
        return (
            subject == self.policy.context.provider_subject
            and expiry is not None
            and expiry > self.clock()
        )

    def revoke(self, access_token: str) -> None:
        with self._lock:
            self._tokens.pop(digest(access_token), None)
