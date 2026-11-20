"""Fixed simulator transport port, injected without receiver storage credentials."""

from typing import Protocol

Record = dict[str, object]


class ReceiverPort(Protocol):
    def send(self, service_id: str, package: Record) -> Record: ...
    def lookup(self, service_id: str, dispatch_id: str, payload_digest: str) -> Record: ...
