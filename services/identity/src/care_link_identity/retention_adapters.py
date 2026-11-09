"""Explicit current operator and pinned Keycloak cleanup adapters."""

from datetime import timedelta
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .crypto import digest
from .domain import IdentityError, instant, text
from .retention_ports import RetentionGrant
from .service import IdentityService


class SessionRetentionAuthority:
    def __init__(self, identity: IdentityService, owner_account_id: str) -> None:
        if str(UUID(owner_account_id)) != owner_account_id:
            raise ValueError("actual main account UUID required")
        self.identity, self.owner_account_id = identity, owner_account_id

    def authorize(self, actor_proof: str, action: str, account_id: str) -> RetentionGrant:
        UUID(account_id)
        session = self.identity.current(actor_proof)
        if (
            session.get("account_id") != self.owner_account_id
            or session.get("role") != "operator"
            or session.get("mfa") is not True
            or self.identity.clock() - instant(session["auth_time"]) > timedelta(minutes=5)
        ):
            raise IdentityError("identity.retention_operator_denied")
        now = self.identity.clock()
        return RetentionGrant(
            self.owner_account_id,
            self.identity.issuer,
            text(session, "revision"),
            text(session, "role_revision"),
            digest(actor_proof),
            action,
            account_id,
            now,
            now + timedelta(seconds=1),
        )


class AdminToken(Protocol):
    def current(self) -> str:
        """Get a freshly authorized separate Keycloak lifecycle service credential."""
        ...


class KeycloakCleanup:
    """Exact-user disable/logout/delete only; no realm/role administration API.

    Composition must provision an appropriately constrained Keycloak service
    client separately. Missing current credential or uncertain HTTP leaves the
    caller's durable cleanup operation pending. No token enters returned records.
    """

    def __init__(
        self, users_endpoint: str, issuer_origin: str, tokens: AdminToken, client: httpx.Client
    ) -> None:
        target, issuer = urlsplit(users_endpoint), urlsplit(issuer_origin)
        if (
            target.scheme != "https"
            or target.netloc != issuer.netloc
            or issuer.scheme != "https"
            or not target.path.startswith("/admin/realms/")
            or not target.path.endswith("/users")
            or target.query
            or target.fragment
            or target.username
            or issuer.username
        ):
            raise ValueError("pinned same-issuer Keycloak users endpoint required")
        self.endpoint, self.tokens, self.client = users_endpoint, tokens, client

    def _url(self, subject: str) -> str:
        if str(UUID(subject)) != subject:
            raise IdentityError("identity.cleanup_subject_denied")
        return self.endpoint + "/" + subject

    def disable(self, subject: str, command_id: str) -> bool:
        headers = {"Authorization": "Bearer " + self.tokens.current(), "X-Operation-Id": command_id}
        try:
            url = self._url(subject)
            response = self.client.put(
                url, json={"enabled": False}, headers=headers, timeout=3, follow_redirects=False
            )
            if response.status_code == 404:
                return True
            response.raise_for_status()
            logout = self.client.post(
                url + "/logout", headers=headers, timeout=3, follow_redirects=False
            )
            if logout.status_code != 404:
                logout.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    def delete_profile(self, subject: str, command_id: str) -> bool:
        headers = {"Authorization": "Bearer " + self.tokens.current(), "X-Operation-Id": command_id}
        try:
            response = self.client.delete(
                self._url(subject), headers=headers, timeout=3, follow_redirects=False
            )
            if response.status_code != 404:
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False


class KeycloakServiceCredentials:
    """Fresh client-credentials token for the separately scoped cleanup client."""

    def __init__(
        self,
        token_endpoint: str,
        issuer_origin: str,
        client_id: str,
        client_secret: str,
        client: httpx.Client,
    ) -> None:
        target, issuer = urlsplit(token_endpoint), urlsplit(issuer_origin)
        if (
            target.scheme != "https"
            or issuer.scheme != "https"
            or target.netloc != issuer.netloc
            or not target.path.endswith("/protocol/openid-connect/token")
            or target.query
            or target.fragment
            or target.username
            or not client_id
            or not client_secret
        ):
            raise ValueError("fixed same-issuer client-credentials endpoint required")
        self.endpoint, self.client_id, self._secret, self.client = (
            token_endpoint,
            client_id,
            client_secret,
            client,
        )

    def current(self) -> str:
        from typing import cast

        try:
            response = self.client.post(
                self.endpoint,
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self._secret),
                timeout=3,
                follow_redirects=False,
            )
            response.raise_for_status()
            if len(response.content) > 32 * 1024:
                raise ValueError("oversized credentials response")
            data = cast(dict[str, object], response.json())
            raw = data.get("access_token")
            if not isinstance(raw, str) or not raw or data.get("token_type") != "Bearer":
                raise ValueError("invalid credentials response")
            return raw
        except (httpx.HTTPError, ValueError) as error:
            raise IdentityError("identity.cleanup_credential_unavailable", 503) from error
