"""Fixed HTTPS simulator adapter. Never receives receiver database credentials."""

from typing import cast

import httpx
from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import ManualError

from .store import Record


class HttpReceiverPort:
    def __init__(self, client: httpx.Client, origin: str, services: frozenset[str]) -> None:
        url = httpx.URL(origin)
        if (
            url.scheme != "https"
            or not url.host
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.username
            or url.password
            or not services
        ):
            raise ValueError("Explicit fixed HTTPS receiver and admitted service IDs required")
        self.client, self.origin, self.services = client, origin.rstrip("/"), services

    def _request(self, action: str, contract: str, service_id: str, data: Record) -> Record:
        if service_id not in self.services:
            raise ManualError("manual.simulator_mapping_denied")
        validate_contract(contract, data)
        try:
            reply = self.client.post(
                self.origin + "/internal/v1/receiver/" + action,
                json=data,
                headers={"Cookie": ""},
                timeout=1.0,
                follow_redirects=False,
            )
        except httpx.HTTPError as error:
            raise ConnectionError("Receiver result unknown") from error
        if reply.status_code != 200:
            if reply.status_code >= 500:
                raise ConnectionError("Receiver result unknown")
            raise ManualError("manual.receiver_denied", 409 if reply.status_code == 409 else 403)
        if len(reply.content) > 65536 or not reply.headers.get("content-type", "").startswith(
            "application/json"
        ):
            raise ConnectionError("Invalid receiver response")
        try:
            return cast(Record, parse_contract("ReceiptView", reply.text))
        except ContractError as error:
            raise ConnectionError("Invalid receiver evidence; result unknown") from error

    def send(self, service_id: str, package: Record) -> Record:
        return self._request(
            "send", "ReceiverSend", service_id, {"service_id": service_id, "package": package}
        )

    def lookup(self, service_id: str, dispatch_id: str, payload_digest: str) -> Record:
        return self._request(
            "lookup",
            "SimulatorLookup",
            service_id,
            {
                "service_id": service_id,
                "dispatch_id": dispatch_id,
                "payload_digest": payload_digest,
            },
        )
