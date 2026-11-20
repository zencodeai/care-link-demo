"""Server-observed app transport liveness; reconnect fences prior channel ACKs."""

import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace

from care_link_domain import Actor, ManualError


@dataclass
class _Connection:
    generation: int
    observed: float
    active: bool


class ManualChannels:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        # A fresh unpredictable boot namespace prevents restored DB ACKs matching
        # a new process. Within a boot each replacement/disconnect increments.
        self._initial_generation = secrets.randbelow(2**62) + 1
        self._connections: dict[tuple[str, str], _Connection] = {}

    @staticmethod
    def _key(actor: Actor) -> tuple[str, str]:
        return actor.account_id, actor.browser_session_digest

    def bind(self, actor: Actor) -> Actor:
        with self._lock:
            state = self._connections.get(self._key(actor))
            generation = state.generation if state else self._initial_generation
            return replace(actor, transport_generation=generation)

    @staticmethod
    def _advance(state: _Connection) -> None:
        if state.generation >= 9223372036854775807:
            state.active = False
            raise ManualError("manual.channel_generation_exhausted", 503)
        state.generation += 1

    @contextmanager
    def open(self, actor: Actor) -> Iterator[Actor]:
        key = self._key(actor)
        with self._lock:
            state = self._connections.get(key)
            if state is None:
                state = _Connection(self._initial_generation, self.clock(), False)
                self._connections[key] = state
            self._advance(state)
            state.observed, state.active = self.clock(), True
            connected = replace(actor, transport_generation=state.generation)
        try:
            yield connected
        finally:
            with self._lock:
                current = self._connections[key]
                if current.generation == connected.transport_generation:
                    current.active = False
                    self._advance(current)

    def invalidate(self, actor: Actor) -> None:
        """Explicit page takeover fences the prior transport without changing owner."""
        self.invalidate_binding(actor.account_id, actor.browser_session_digest)

    def invalidate_binding(self, account_id: str, browser_session_digest: str) -> None:
        """Retire only the exact server-owned browser transport binding."""
        with self._lock:
            state = self._connections.get((account_id, browser_session_digest))
            if state:
                state.active = False
                self._advance(state)

    def heartbeat(self, actor: Actor) -> None:
        with self._lock:
            connection = self._connections.get(self._key(actor))
            if (
                connection
                and connection.active
                and connection.generation == actor.transport_generation
            ):
                connection.observed = self.clock()

    def current(
        self, account_id: str, browser_session_digest: str, transport_generation: int
    ) -> bool:
        with self._lock:
            connection = self._connections.get((account_id, browser_session_digest))
            return bool(
                connection
                and connection.active
                and connection.generation == transport_generation
                and self.clock() - connection.observed < 10
            )
