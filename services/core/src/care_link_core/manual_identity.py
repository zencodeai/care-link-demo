"""Exact HTTPS remote current identity port, without cached permission or cookies."""

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import httpx
from care_link_contracts import ContractError, parse_contract
from care_link_domain import Actor, ManualError
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

Record = dict[str, object]
PREFIX = "/internal/v1/manual-identity/"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fixed_origin(origin: str) -> str:
    url = httpx.URL(origin)
    if (
        url.scheme != "https"
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
        or url.userinfo
    ):
        raise ValueError("Exact HTTPS origin required")
    return origin.rstrip("/")


def _text(data: Record, key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value:
        raise ValueError("invalid identity field")
    return value


def _instant(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("UTC identity timestamp required")
    return datetime.fromisoformat(value)


def _number(data: Record, key: str) -> int:
    value = _text(data, key)
    if re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is None or int(value) > 9223372036854775807:
        raise ValueError("canonical identity revision required")
    return int(value)


def actor_record(actor: Actor) -> Record:
    def stamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    result: Record = {
        "account_id": actor.account_id,
        "role": actor.role,
        "identity_revision": str(actor.identity_revision),
        "role_revision": str(actor.role_revision),
        "auth_time": stamp(actor.auth_time),
        "mfa": actor.mfa,
        "browser_session_digest": actor.browser_session_digest,
        "transport_generation": str(actor.transport_generation),
        "credential_ref": actor.credential_ref,
        "expires_at": stamp(actor.expires_at),
        "identity_evidence_id": actor.identity_evidence_id,
        "request_deadline": stamp(actor.request_deadline) if actor.request_deadline else None,
    }

    if actor.review_run_id is not None:
        result.update(
            {
                "review_run_id": actor.review_run_id,
                "review_slot_id": actor.review_slot_id,
                "review_origin": actor.review_origin,
            }
        )
    return result


def parse_actor(data: Record) -> Actor:
    required = {
        "account_id",
        "role",
        "identity_revision",
        "role_revision",
        "auth_time",
        "mfa",
        "browser_session_digest",
        "transport_generation",
        "credential_ref",
        "expires_at",
        "identity_evidence_id",
        "request_deadline",
    }
    context_fields = {"review_run_id", "review_slot_id", "review_origin"}
    if set(data) not in (required, required | context_fields):
        raise ValueError("invalid identity actor fields")
    if context_fields <= set(data):
        if str(UUID(_text(data, "review_run_id"))) != data["review_run_id"]:
            raise ValueError("Canonical review run required")
        fixed_origin(_text(data, "review_origin"))
        slots = {
            "participant": "pid",
            "worker1": "worker",
            "worker2": "worker",
            "supervisor": "supervisor",
            "pid": "pid",
            "carer": "carer",
            "professional": "professional_participant",
        }
        if slots.get(str(data["review_slot_id"])) != data["role"]:
            raise ValueError("Known actor slot required")
    for field in ("account_id", "identity_evidence_id"):
        if str(UUID(_text(data, field))) != data[field]:
            raise ValueError("canonical identity UUID required")
    if (
        type(data["mfa"]) is not bool
        or re.fullmatch(r"[0-9a-f]{64}", _text(data, "browser_session_digest")) is None
    ):
        raise ValueError("invalid identity actor")
    if data["role"] not in {
        "pid",
        "carer",
        "professional_participant",
        "worker",
        "supervisor",
        "receiver",
        "operator",
        "governance",
        "auditor",
        "security",
        "trainer",
    }:
        raise ValueError("invalid identity role")
    return Actor(
        _text(data, "account_id"),
        _text(data, "role"),
        _number(data, "identity_revision"),
        _number(data, "role_revision"),
        _instant(data["auth_time"]),
        data["mfa"],
        _text(data, "browser_session_digest"),
        _number(data, "transport_generation"),
        _text(data, "credential_ref"),
        _instant(data["expires_at"]),
        _text(data, "identity_evidence_id"),
        _instant(data["request_deadline"]) if data["request_deadline"] is not None else None,
        _text(data, "review_run_id") if "review_run_id" in data else None,
        _text(data, "review_slot_id") if "review_slot_id" in data else None,
        _text(data, "review_origin") if "review_origin" in data else None,
    )


class HttpManualIdentity:
    def __init__(
        self,
        client: httpx.Client,
        origin: str,
        identity_public_key: Ed25519PublicKey,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client, self.origin, self.public_key = (
            client,
            fixed_origin(origin),
            identity_public_key,
        )
        self.clock = clock

    def _call(self, name: str, data: Record, contract: str | None = None) -> Record:
        try:
            response = self.client.post(
                self.origin + PREFIX + name,
                json=data,
                timeout=1.0,
                follow_redirects=False,
                headers={"Cookie": "", "Content-Type": "application/json"},
            )
            if response.status_code != 200:
                raise ManualError(
                    "manual.identity_denied"
                    if response.status_code < 500
                    else "manual.identity_unavailable",
                    401
                    if response.status_code == 401
                    else 403
                    if response.status_code < 500
                    else 503,
                )
            if len(response.content) > 65536 or not response.headers.get(
                "content-type", ""
            ).startswith("application/json"):
                raise ValueError("invalid identity response")
            # The contract parser rejects duplicate keys and non-JSON numbers.
            if contract is not None:
                return cast(Record, parse_contract(contract, response.text))

            def pairs(items: list[tuple[str, object]]) -> Record:
                result: Record = {}
                for key, value in items:
                    if key in result:
                        raise ValueError("duplicate identity field")
                    result[key] = value
                return result

            value: object = json.loads(response.text, object_pairs_hook=pairs)
            if not isinstance(value, dict):
                raise ValueError("identity object required")
            return cast(Record, value)
        except (httpx.HTTPError, ValueError, ContractError) as error:
            raise ManualError("manual.identity_unavailable", 503) from error

    def _actor(self, name: str, data: Record) -> Actor:
        try:
            result = parse_actor(self._call(name, data))
            if result.expires_at <= self.clock() or (
                result.request_deadline is not None and result.request_deadline <= self.clock()
            ):
                raise ValueError("identity expired")
            return result
        except (ValueError, TypeError, KeyError) as error:
            raise ManualError("manual.identity_unavailable", 503) from error

    def authenticate(self, raw_session: str) -> Actor:
        actor = self._actor("authenticate", {"raw_session": raw_session})
        if (
            actor.credential_ref != raw_session
            or actor.browser_session_digest != hashlib.sha256(raw_session.encode()).hexdigest()
        ):
            raise ManualError("manual.identity_unavailable", 503)
        return actor

    def csrf(self, actor: Actor, origin: str | None, supplied: str | None) -> None:
        if self._call(
            "csrf", {"raw_session": actor.credential_ref, "origin": origin, "supplied": supplied}
        ) != {"verified": True}:
            raise ManualError("manual.csrf_denied")

    def evidence(
        self, actor: Actor, action: str, request_digest: str, nonce: str, resource: object
    ) -> Record:
        result = self._call(
            "evidence",
            {
                "raw_session": actor.credential_ref,
                "transport_generation": str(actor.transport_generation),
                "action": action,
                "request_digest": request_digest,
                "nonce": nonce,
                "resource_id": resource,
            },
            "IdentityEvidence",
        )
        try:
            signature = _text(result, "signature")
            raw = base64.b64decode(
                signature + "=" * (-len(signature) % 4), altchars=b"-_", validate=True
            )
            if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != signature:
                raise ValueError("noncanonical signature")
            self.public_key.verify(
                raw, canonical({k: v for k, v in result.items() if k != "signature"})
            )
            if (
                result["principal_id"] != actor.account_id
                or result["role"] != actor.role
                or result["identity_revision"] != str(actor.identity_revision)
                or result["role_revision"] != str(actor.role_revision)
                or result["action"] != action
                or result["request_digest"] != request_digest
                or result["nonce"] != nonce
                or result["resource_id"] != resource
                or not _instant(result["verified_at"])
                <= self.clock()
                < _instant(result["expires_at"])
                or (
                    _instant(result["expires_at"]) - _instant(result["verified_at"])
                ).total_seconds()
                > 1
            ):
                raise ValueError("identity evidence mismatch")
        except (ValueError, KeyError, TypeError, InvalidSignature) as error:
            raise ManualError("manual.identity_evidence_denied") from error
        return result

    def resolve(self, evidence: Record) -> Actor:
        actor = self._actor("resolve", {"evidence": evidence})
        if actor.identity_evidence_id != evidence["id"] or actor.credential_ref != evidence["id"]:
            raise ManualError("manual.identity_evidence_denied")
        return actor

    def current(self, actor: Actor) -> Actor:
        fresh = self._actor("current", {"credential_ref": actor.credential_ref})
        # Preserve the original request deadline; a remote lookup cannot extend it.
        return replace(
            fresh,
            request_deadline=min(fresh.request_deadline, actor.request_deadline)
            if fresh.request_deadline and actor.request_deadline
            else actor.request_deadline or fresh.request_deadline,
        )

    def recovery_proof(
        self, actor: Actor, ceremony_id: str, session_id: str, family_id: str
    ) -> None:
        if self._call(
            "recovery",
            {
                "credential_ref": actor.credential_ref,
                "ceremony_id": ceremony_id,
                "session_id": session_id,
                "family_id": family_id,
            },
        ) != {"verified": True}:
            raise ManualError("manual.fresh_recovery_required")

    def consent_proof(
        self,
        actor: Actor,
        proof_id: str,
        subject_id: str,
        session_id: str,
        purpose: str,
        basis: str,
    ) -> None:
        if self._call(
            "consent-proof",
            {
                "credential_ref": actor.credential_ref,
                "proof_id": proof_id,
                "subject_id": subject_id,
                "session_id": session_id,
                "purpose": purpose,
                "basis": basis,
            },
        ) != {"verified": True}:
            raise ManualError("manual.consent_proof_required")

    def rights_proof(self, actor: Actor, ceremony_id: str, subject_id: str, kind: str) -> None:
        if self._call(
            "rights-proof",
            {
                "credential_ref": actor.credential_ref,
                "ceremony_id": ceremony_id,
                "subject_id": subject_id,
                "kind": kind,
            },
        ) != {"verified": True}:
            raise ManualError("manual.rights_proof_required")

    def rights_download_proof(self, actor: Actor, ceremony_id: str, subject_id: str) -> None:
        if self._call(
            "rights-download-proof",
            {
                "credential_ref": actor.credential_ref,
                "ceremony_id": ceremony_id,
                "subject_id": subject_id,
            },
        ) != {"verified": True}:
            raise ManualError("manual.rights_proof_required")
