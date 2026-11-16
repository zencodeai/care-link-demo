"""Bounded authenticated metadata-only policy/journal/channel process adapters."""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import httpx
from care_link_contracts import ContractError, parse_contract, validate_contract
from care_link_domain import JournalState, ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .config import Record, record, unique


def canonical(value: Record) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class Remote:
    def __init__(self, client: httpx.Client, origin: str) -> None:
        url = httpx.URL(origin)
        if url.scheme != "https" or url.path != "/" or url.query or url.userinfo or url.fragment:
            raise ValueError("Exact HTTPS authority required")
        self.client, self.origin = client, origin.rstrip("/")

    def call(self, path: str, value: Record) -> Record:
        try:
            reply = self.client.post(
                self.origin + path, json=value, timeout=0.8, follow_redirects=False
            )
            if (
                reply.status_code != 200
                or len(reply.content) > 65536
                or not reply.headers.get("content-type", "").startswith("application/json")
            ):
                raise ValueError("Dependency unavailable")
            return record(json.loads(reply.content, object_pairs_hook=unique))
        except (httpx.HTTPError, ValueError) as error:
            raise ManualError("manual.dependency_unavailable", 503) from error


class HttpPolicy(Remote):
    def evaluate(self, request: Record) -> Record:
        validate_contract("PolicyInput", request)
        value = self.call("/internal/v1/policy/evaluate", request)
        try:
            return cast(Record, parse_contract("PolicyDecision", json.dumps(value)))
        except ContractError as error:
            raise ManualError("manual.policy_unavailable", 503) from error


class HttpJournal(Remote):
    def __init__(self, client: httpx.Client, origin: str, key: Ed25519PublicKey) -> None:
        super().__init__(client, origin)
        self.key = key

    def _state(self, path: str, command: Record | None = None) -> JournalState:
        nonce = str(uuid4())
        value = self.call(path, {"nonce": nonce, "command": command})
        try:
            if set(value) != {"state", "nonce", "signature"} or value["nonce"] != nonce:
                raise ValueError("Journal response binding mismatch")
            signature = str(value["signature"])
            unsigned = {k: v for k, v in value.items() if k != "signature"}
            self.key.verify(
                base64.b64decode(
                    signature + "=" * (-len(signature) % 4), altchars=b"-_", validate=True
                ),
                canonical(unsigned),
            )
            state = record(value["state"])
            if set(state) != {
                "journal_id",
                "generation",
                "tip",
                "tip_digest",
                "restriction_barrier",
                "serving_generation",
                "observed_at",
            }:
                raise ValueError("Invalid journal state")
            observed = datetime.fromisoformat(str(state["observed_at"]).replace("Z", "+00:00"))
            if abs(datetime.now(UTC) - observed) > timedelta(seconds=1):
                raise ValueError("Stale journal response")
            return JournalState(
                str(state["journal_id"]),
                int(str(state["generation"])),
                int(str(state["tip"])),
                str(state["tip_digest"]),
                int(str(state["restriction_barrier"])),
                int(str(state["serving_generation"])),
                observed,
            )
        except (InvalidSignature, KeyError, ValueError, TypeError) as error:
            raise ManualError("manual.journal_unavailable", 503) from error

    def head(self) -> JournalState:
        return self._state("/internal/v1/journal/head")

    def append(self, request: Record) -> JournalState:
        validate_contract("JournalAppend", request)
        return self._state("/internal/v1/journal/append", request)


class HttpChannels(Remote):
    def current(
        self, account_id: str, browser_session_digest: str, transport_generation: int
    ) -> bool:
        value = self.call(
            "/internal/v1/channels/current",
            {
                "account_id": account_id,
                "browser_session_digest": browser_session_digest,
                "transport_generation": transport_generation,
            },
        )
        if set(value) != {"current"} or type(value["current"]) is not bool:
            raise ManualError("manual.channel_unavailable", 503)
        return value["current"] is True
