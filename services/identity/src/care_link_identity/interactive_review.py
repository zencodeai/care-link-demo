"""Server-only simulated review flows over existing login and ceremony guards."""

from . import stepup
from .domain import IdentityError, text
from .interactive_provider import AutomaticReviewProvider
from .service import IdentityService


def configured(service: IdentityService) -> AutomaticReviewProvider:
    provider = service.provider
    if service.interactive_policy is None or not isinstance(provider, AutomaticReviewProvider):
        raise IdentityError("identity.interactive_review_disabled", 404)
    provider.check()
    return provider


def login(
    service: IdentityService,
    binding: str,
    previous_raw_session: str | None,
) -> tuple[dict[str, object], str]:
    provider = configured(service)
    context = provider.policy.context
    intent, _state = service.login_start(
        context.role,
        binding,
        previous_raw_session=previous_raw_session,
    )
    state, code = provider.complete(text(intent, "authorization_url"))
    view, raw, _proof = service.callback(state, code, binding)
    if raw is None:
        raise IdentityError("identity.interactive_review_exchange_denied")
    return view, raw


def verify(
    service: IdentityService,
    raw_session: str,
    binding: str,
    request: dict[str, object],
) -> tuple[dict[str, object], str]:
    provider = configured(service)
    if request.get("purpose") != "plan_edit":
        raise IdentityError("identity.interactive_review_purpose_denied")
    ceremony = stepup.start(service, raw_session, binding, request)
    state, code = provider.complete(text(ceremony, "authorization_url"))
    view, replacement, proof = service.callback(state, code, binding)
    if replacement is None or proof is None:
        raise IdentityError("identity.interactive_review_exchange_denied")
    result = stepup.confirm(
        service,
        replacement,
        {
            "ceremony_id": ceremony["ceremony_id"],
            "proof_intent_id": proof,
            "expected_revision": view["revision"],
        },
    )
    return result, replacement
