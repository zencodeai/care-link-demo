"""Select verified immutable evaluators by the current guarded request digest."""

from collections.abc import Iterable
from types import MappingProxyType

from care_link_domain import ManualError

from .opa import OpaPolicy


class GovernedPolicies:
    """Explicit composition custody; no policy fetching or permission caching.

    Stage verified evaluator bytes before ACK. The central activation chooses a
    digest; every evaluation verifies the exact source and executable again.
    Missing staged bytes fail closed rather than falling back to an old policy.
    """

    def __init__(self, policies: Iterable[OpaPolicy]) -> None:
        selected = {policy.bundle_digest: policy for policy in policies}
        if not selected:
            raise ValueError("Explicit signed evaluators required")
        self._policies = MappingProxyType(selected)

    def evaluate(self, request: dict[str, object]) -> dict[str, object]:
        digest = request.get("bundle_digest")
        policy = self._policies.get(digest) if isinstance(digest, str) else None
        if policy is None:
            raise ManualError("manual.policy_bundle_not_staged", 503)
        return policy.evaluate(request)
