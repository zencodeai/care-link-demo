"""Pinned Ed25519 authority receipts and an authenticated HTTP authority adapter."""

import base64
import json
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

import httpx
from care_link_contracts import ContractError, parse_contract, validate_contract
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .model import BrowserContext, Clock, Decision, HelpError, Wire, canonical, digest, now_utc

logger = logging.getLogger(__name__)


def _diagnostic(stage: str, status: int | None) -> None:
    # Stages are fixed internal constants. Never log upstream bodies, credential
    # headers, cookies, request identities, URLs or full HTTP exception strings.
    logger.warning("Identity HTTP adapter failed: stage=%s status=%s", stage, status)


class SignedReceipts:
    def __init__(
        self,
        keys: Mapping[str, Ed25519PublicKey],
        *,
        issuer: str = "care-link-identity",
        audience: str = "care-link-help",
        clock: Clock = now_utc,
    ) -> None:
        self.keys = dict(keys)
        self.issuer = issuer
        self.audience = audience
        self.clock = clock

    def verify(self, request: Wire, receipt: Wire, principal_id: str) -> Decision:
        try:
            validate_contract("HelpAuthorityRequest", request)
            validate_contract("FreshHelpAuthority", receipt)
            key = self.keys[cast(str, receipt["key_id"])]
            signed = {k: v for k, v in receipt.items() if k != "signature"}
            encoded = cast(str, receipt["signature"])
            if "=" in encoded:
                raise ValueError("noncanonical signature")
            raw = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
            if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != encoded:
                raise ValueError("noncanonical signature")
            key.verify(raw, canonical(signed))
            issued = datetime.fromisoformat(cast(str, receipt["issued_at"]))
            expires = datetime.fromisoformat(cast(str, receipt["expires_at"]))
            deadline = datetime.fromisoformat(cast(str, request["deadline"]))
            now = self.clock()
            if not (issued <= now < expires <= deadline <= now + timedelta(seconds=1)):
                raise ValueError("expired authority")
            if expires - issued > timedelta(seconds=1):
                raise ValueError("authority budget")
            if receipt["issuer_id"] != self.issuer or receipt["audience"] != self.audience:
                raise ValueError("untrusted authority")
            for field in ("operation_id", "help_id", "request_digest", "action"):
                if receipt[field] != request[field]:
                    raise ValueError("binding mismatch")
            if receipt["one_use_nonce"] != request["nonce"]:
                raise ValueError("nonce mismatch")
            if receipt["principal_id"] != principal_id or receipt["decision"] != "PERMIT":
                raise ValueError("denied")
            return Decision(
                principal_id, cast(str, receipt["one_use_nonce"]), expires, digest(receipt)
            )
        except (ContractError, KeyError, ValueError, InvalidSignature) as error:
            raise HelpError("help.authority_denied") from error


class HttpAuthority:
    """Client must carry the independently attested help mTLS identity.

    A preconfigured HTTPS client is injected by the composition root; certificate
    custody, proxy fencing and CNI qualification remain deployment obligations.
    No request can choose the authority URL, headers or TLS verification policy.
    """

    def __init__(self, client: httpx.Client, origin: str) -> None:
        url = httpx.URL(origin)
        if (
            url.scheme != "https"
            or url.path not in ("", "/")
            or url.query
            or url.fragment
            or url.username
            or url.password
        ):
            raise ValueError("authority must be a pinned HTTPS origin")
        self.client = client
        self.url = str(url).rstrip("/") + "/internal/v1/identity/help-authorize"

    def authorize(self, request: Wire) -> Wire:
        status = None
        try:
            response = self.client.post(self.url, json=request, timeout=1, follow_redirects=False)
            status = response.status_code
            if status in {401, 403}:
                _diagnostic("authorize", status)
                raise HelpError("help.authority_denied", 403)
            response.raise_for_status()
            return cast(Wire, parse_contract("FreshHelpAuthority", response.text))
        except (httpx.HTTPError, ContractError) as error:
            _diagnostic("authorize", status)
            raise HelpError("help.identity_unavailable", 503) from error


def _unique(pairs: list[tuple[str, object]]) -> Wire:
    result: Wire = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate identity field")
        result[key] = value
    return result


class HttpBrowserSessions:
    """Resolve only host-held session cookies over the pinned workload channel.

    These headers are credentials to the internal identity listener. Its proxy
    must authenticate the help workload before reading them; browser-controlled
    forwarded identity/proof headers never enter this adapter.
    """

    def __init__(self, client: httpx.Client, identity_origin: str, help_origin: str) -> None:
        self.authority = HttpAuthority(client, identity_origin)
        self.base = self.authority.url.removesuffix("help-authorize")
        self.origin = help_origin

    def _request(self, operation: str, cookie: str) -> Wire:
        stage = {
            "help-browser-context": "browser_context",
            "help-browser-proof": "browser_proof",
        }[operation]
        status = None
        try:
            response = self.authority.client.post(
                self.base + operation,
                headers={"X-Help-Session": cookie, "X-Help-Origin": self.origin},
                json={},
                timeout=1,
                follow_redirects=False,
            )
            status = response.status_code
            if status in {401, 403}:
                _diagnostic(stage, status)
                raise HelpError(
                    "help.login_required" if status == 401 else "help.authority_denied", status
                )
            response.raise_for_status()
            value: object = json.loads(response.text, object_pairs_hook=_unique)
            if not isinstance(value, dict):
                raise ValueError("identity object required")
            return cast(Wire, value)
        except (httpx.HTTPError, ValueError) as error:
            _diagnostic(stage, status)
            raise HelpError("help.identity_unavailable", 503) from error

    def context(self, cookie: str) -> BrowserContext:
        value = self._request("help-browser-context", cookie)
        if set(value) != {"account_id", "role", "csrf_token"}:
            _diagnostic("browser_context_schema", 200)
            raise HelpError("help.identity_unavailable", 503)
        if not all(isinstance(value[key], str) and value[key] for key in value):
            _diagnostic("browser_context_schema", 200)
            raise HelpError("help.identity_unavailable", 503)
        account = cast(str, value["account_id"])
        try:
            if str(UUID(account)) != account:
                raise ValueError("noncanonical identity")
        except ValueError as error:
            _diagnostic("browser_context_schema", 200)
            raise HelpError("help.identity_unavailable", 503) from error
        return BrowserContext(account, cast(str, value["role"]), cast(str, value["csrf_token"]))

    def proof(self, cookie: str, origin: str) -> str:
        if origin != self.origin:
            raise HelpError("help.authority_denied")
        value = self._request("help-browser-proof", cookie)
        proof = value.get("proof_ref")
        if set(value) != {"proof_ref"} or not isinstance(proof, str):
            _diagnostic("browser_proof_schema", 200)
            raise HelpError("help.identity_unavailable", 503)
        try:
            if str(UUID(proof)) != proof:
                raise ValueError("noncanonical proof")
        except ValueError as error:
            _diagnostic("browser_proof_schema", 200)
            raise HelpError("help.identity_unavailable", 503) from error
        return proof
