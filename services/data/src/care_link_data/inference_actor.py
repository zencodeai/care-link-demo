"""Data consumes only an exact, fresh Identity proof from its protected Core peer."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import httpx
from care_link_contracts import parse_contract
from care_link_domain import INFERENCE_ACTOR_PATH, Actor, InferenceActorRequest, ManualError

from .store import Record


class InferenceIdentity(Protocol):
    def resolve(self, evidence: Record) -> Actor: ...


class HttpInferenceActor:
    def __init__(
        self,
        client: httpx.Client,
        origin: str,
        identity: InferenceIdentity,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        target = httpx.URL(origin)
        if (
            target.scheme != "https"
            or not target.host
            or target.userinfo
            or target.path != "/"
            or target.query
            or target.fragment
        ):
            raise ValueError("fixed protected Core origin required")
        self.client, self.identity, self.clock = client, identity, clock
        self.url = str(target).rstrip("/") + INFERENCE_ACTOR_PATH

    def __call__(self, command: InferenceActorRequest) -> Actor:
        # The transport terminates only at the authenticated Core workload.
        try:
            with self.client.stream(
                "POST", self.url, json=command.record(), timeout=1, follow_redirects=False
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise ValueError("closed Identity proof required")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if len(raw) + len(chunk) > 8192:
                        raise ValueError("bounded Identity proof required")
                    raw.extend(chunk)
            proof = cast(Record, parse_contract("IdentityEvidence", raw.decode()))
            issued = datetime.fromisoformat(str(proof["verified_at"]))
            expiry = datetime.fromisoformat(str(proof["expires_at"]))
            if (
                proof["kind"] != "human_identity"
                or proof["action"] != command.action
                or proof["nonce"] != command.nonce
                or proof["request_digest"] != command.digest
                or proof["resource_id"] != command.task_id
                or not issued <= self.clock() < expiry <= issued + timedelta(seconds=1)
            ):
                raise ManualError("assistance.inference_actor_denied", 403)
            actor = self.identity.resolve(proof)
            if (
                actor.identity_evidence_id != proof["id"]
                or actor.credential_ref != proof["id"]
                or actor.account_id != proof["principal_id"]
                or actor.role != proof["role"]
                or str(actor.identity_revision) != proof["identity_revision"]
                or str(actor.role_revision) != proof["role_revision"]
                or actor.request_deadline is None
                or not self.clock() < actor.request_deadline <= expiry
            ):
                raise ManualError("assistance.inference_actor_denied", 403)
            return actor
        except httpx.HTTPStatusError as error:
            if 400 <= error.response.status_code < 500:
                raise ManualError("assistance.inference_actor_denied", 403) from error
            raise ManualError("assistance.inference_actor_unavailable", 503) from error
        except (httpx.HTTPError, ValueError) as error:
            raise ManualError("assistance.inference_actor_unavailable", 503) from error
