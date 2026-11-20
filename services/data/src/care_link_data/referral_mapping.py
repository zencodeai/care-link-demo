"""Admitted technical mapping, kept outside directory/model/user content."""

import base64
import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .values import canonical


@dataclass(frozen=True)
class SimulatorMapping:
    origin: str
    service_ids: frozenset[str]
    revision: int

    @classmethod
    def verify(
        cls, value: dict[str, object], keys: dict[str, Ed25519PublicKey]
    ) -> SimulatorMapping:
        """Signature establishes configuration custody, not consent or human approval."""
        import httpx

        if set(value) != {
            "key_id",
            "signature",
            "revision",
            "origin",
            "service_ids",
            "workload_id",
            "tags",
        }:
            raise ValueError("Exact signed simulator mapping required")
        key = keys.get(str(value["key_id"]))
        if key is None:
            raise ValueError("Untrusted simulator mapping key")
        try:
            encoded = str(value["signature"])
            raw = base64.b64decode(encoded, validate=True)
            if base64.b64encode(raw).decode() != encoded:
                raise ValueError("Noncanonical mapping signature")
            key.verify(
                raw, canonical({k: v for k, v in value.items() if k != "signature"}).encode()
            )
        except InvalidSignature as error:
            raise ValueError("Invalid simulator mapping signature") from error
        origin = value["origin"]
        if not isinstance(origin, str):
            raise ValueError("Fixed HTTPS origin required")
        url = httpx.URL(origin)
        if (
            url.scheme != "https"
            or not url.host
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.username
            or url.password
            or value["tags"] != {"environment": "demo", "population": "synthetic"}
            or value["workload_id"] != "spiffe://care-link.demo/demo/receiver"
            or type(value["revision"]) is not int
            or value["revision"] < 1
        ):
            raise ValueError("Invalid simulator mapping boundary")
        services = value["service_ids"]
        if not isinstance(services, list):
            raise ValueError("Bounded simulator services required")
        services = cast(list[object], services)
        if not 1 <= len(services) <= 100:
            raise ValueError("Bounded simulator services required")
        for service in services:
            if not isinstance(service, str) or str(UUID(service)) != service:
                raise ValueError("Canonical simulator service UUID required")
        ids = frozenset(cast(list[str], services))
        if len(ids) != len(services):
            raise ValueError("Duplicate simulator service ID")
        return cls(origin.rstrip("/"), ids, value["revision"])


def read_mapping(raw: str, keys: dict[str, Ed25519PublicKey]) -> SimulatorMapping:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate simulator mapping field")
            result[key] = value
        return result

    if len(raw.encode()) > 32768:
        raise ValueError("Mapping too large")
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Mapping object required")
    return SimulatorMapping.verify(cast(dict[str, object], value), keys)
