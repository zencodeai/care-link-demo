"""Exact origin-to-actor composition over the existing identity custody store."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from threading import RLock

from .crypto import digest
from .domain import IdentityError, Provider, text
from .provider import OIDCProvider
from .review_context import ReviewContext
from .service import IdentityService

ContextLoader = Callable[[], Mapping[str, ReviewContext]]
ProviderFactory = Callable[[str], Provider]


class ReviewIdentityRegistry:
    def __init__(
        self,
        base: IdentityService,
        contexts: ContextLoader,
        provider_for_origin: ProviderFactory | None = None,
    ) -> None:
        self.base, self.contexts = base, contexts
        self.provider_for_origin = provider_for_origin or self._provider
        self._custom_provider = provider_for_origin is not None
        self._providers: dict[str, Provider] = {}
        self._lock = RLock()

    def _provider(self, origin: str) -> Provider:
        provider = self.base.provider
        if not isinstance(provider, OIDCProvider):
            raise ValueError("Explicit review provider factory required")
        return OIDCProvider(
            replace(provider.config, redirect_uri=origin + "/v1/auth/callback"),
            provider.client,
        )

    def browser_service(self, origin: str) -> IdentityService:
        try:
            contexts = self.contexts()
        except (ValueError, OSError) as error:
            raise IdentityError("identity.review_registry_unavailable", 503) from error
        context = contexts.get(origin)
        if context is None or context.origin != origin:
            raise IdentityError("identity.review_origin_denied")
        if self._custom_provider:
            provider = self.provider_for_origin(origin)
        else:
            with self._lock:
                provider = self._providers.get(origin)
                if provider is None:
                    provider = self.provider_for_origin(origin)
                    self._providers[origin] = provider
        return IdentityService(
            self.base.store,
            provider,
            self.base.custody,
            self.base.signer,
            provider.config.issuer if isinstance(provider, OIDCProvider) else self.base.issuer,
            origin,
            self.base.clock,
            review_context=context,
        )

    def session_service(self, raw_session: str) -> IdentityService:
        with self.base.store.transaction() as tx:
            session = tx.get("session", digest(raw_session))
        if session is None:
            raise IdentityError("identity.session_unavailable", 401)
        origin = text(session, "origin")
        if origin == self.base.origin and session.get("review_run_id") is None:
            return self.base
        service = self.browser_service(origin)
        context = service.review_context
        if context is None or any(session.get(k) != v for k, v in context.binding().items()):
            raise IdentityError("identity.review_context_changed", 401)
        return service
