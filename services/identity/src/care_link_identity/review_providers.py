"""Private, same-authority provider profiles for isolated review actor issuers."""

import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import fields, replace
from pathlib import Path
from threading import RLock
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from .domain import IdentityError, Provider
from .provider import OIDCConfig, OIDCProvider
from .review_context import ReviewContext


def _origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.netloc


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate provider profile")
        result[key] = value
    return result


class ReviewProviders:
    """Context selects an issued subject; that subject selects a private issuer/client.

    The existing verified TLS HTTP client is reused. All issuer endpoints remain
    on its already pinned provider authority; no new trust or egress is introduced.
    """

    def __init__(
        self,
        base: OIDCProvider,
        contexts: Callable[[], Mapping[str, ReviewContext]],
        path: Path,
    ) -> None:
        self.base, self.contexts, self.path = base, contexts, path
        self._providers: dict[tuple[str, str], OIDCProvider] = {}
        self._lock = RLock()

    def _read(self) -> tuple[dict[str, OIDCConfig], str]:
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_size > 262144
                ):
                    raise ValueError("Owner-only private provider catalog required")
                raw = stream.read(262145)
            value: object = json.loads(raw, object_pairs_hook=_unique)
            if not isinstance(value, dict):
                raise ValueError("Bounded exact provider catalog required")
            source = cast(dict[str, object], value)
            if len(source) > 64:
                raise ValueError("Bounded exact provider catalog required")
            result: dict[str, OIDCConfig] = {}
            allowed = {field.name for field in fields(OIDCConfig)}
            required = allowed - {"access_token_type"}
            for subject, raw_configuration in source.items():
                if str(UUID(subject)) != subject or not isinstance(raw_configuration, dict):
                    raise ValueError("Issued subject and exact OIDC profile required")
                configuration = cast(dict[str, object], raw_configuration)
                if not required <= set(configuration) <= allowed or any(
                    not isinstance(item, str) for item in configuration.values()
                ):
                    raise ValueError("Exact string OIDC fields required")
                config = OIDCConfig(**cast(dict[str, str], configuration))
                for endpoint in (
                    config.issuer,
                    config.authorization_endpoint,
                    config.token_endpoint,
                    config.jwks_uri,
                    config.introspection_endpoint,
                    config.revocation_endpoint,
                ):
                    if _origin(endpoint) != _origin(self.base.config.issuer):
                        raise ValueError("Review provider must retain pinned authority")
                result[subject] = config
            return result, hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError, TypeError) as error:
            raise IdentityError("identity.review_provider_catalog_unavailable", 503) from error

    def __call__(self, origin: str) -> Provider:
        context = self.contexts().get(origin)
        if context is None:
            raise IdentityError("identity.review_origin_denied")
        profiles, fingerprint = self._read()
        selected = profiles.get(context.provider_subject or "", self.base.config)
        with self._lock:
            key = origin, fingerprint
            provider = self._providers.get(key)
            if provider is None:
                provider = OIDCProvider(
                    replace(selected, redirect_uri=origin + "/v1/auth/callback"),
                    self.base.client,
                )
                # Keep one immutable current profile per registered origin.
                self._providers = {
                    old_key: old for old_key, old in self._providers.items() if old_key[0] != origin
                }
                self._providers[key] = provider
            return provider
