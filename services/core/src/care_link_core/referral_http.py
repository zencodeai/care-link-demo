"""Named signed data-gateway adapter for current referral operations."""

from uuid import uuid4

from care_link_domain import Actor

from .planning_http import HttpPlanningGateway
from .referral_ports import Record


class HttpReferralGateway(HttpPlanningGateway):
    def referral_draft(self, actor: Actor, key: str, data: Record, session_id: str) -> Record:
        return self._result(
            actor, "referral_draft", key, data, {"session_id": session_id}, "ReferralView"
        )

    def referral_sources(self, actor: Actor, session_id: str) -> Record:
        return self._result(
            actor,
            "referral_sources",
            str(uuid4()),
            {},
            {"session_id": session_id},
            "ReferralSourcePage",
        )

    def referral_read(self, actor: Actor, referral_id: str) -> Record:
        return self._result(
            actor, "referral_read", str(uuid4()), {}, {"referral_id": referral_id}, "ReferralView"
        )

    def referral_context(self, actor: Actor, referral_id: str) -> Record:
        return self._result(
            actor,
            "referral_context",
            str(uuid4()),
            {},
            {"referral_id": referral_id},
            "ReferralContext",
        )

    def referral_review(self, actor: Actor, key: str, data: Record, referral_id: str) -> Record:
        return self._result(
            actor, "referral_review", key, data, {"referral_id": referral_id}, "ReviewView"
        )

    def referral_dispatch(self, actor: Actor, key: str, data: Record, referral_id: str) -> Record:
        return self._result(
            actor, "referral_dispatch", key, data, {"referral_id": referral_id}, "DispatchView"
        )

    def dispatcher_send(self, actor: Actor, key: str, data: Record, dispatch_id: str) -> Record:
        return self._result(
            actor, "dispatcher_send", key, data, {"dispatch_id": dispatch_id}, "DispatchView"
        )

    def dispatch_read(self, actor: Actor, dispatch_id: str) -> Record:
        return self._result(
            actor, "dispatch_read", str(uuid4()), {}, {"dispatch_id": dispatch_id}, "DispatchView"
        )

    def receipt_read(self, actor: Actor, dispatch_id: str) -> Record:
        return self._result(
            actor, "receipt_read", str(uuid4()), {}, {"dispatch_id": dispatch_id}, "ReceiptView"
        )

    def dispatch_reconcile(self, actor: Actor, key: str, data: Record, dispatch_id: str) -> Record:
        return self._result(
            actor, "dispatch_reconcile", key, data, {"dispatch_id": dispatch_id}, "DispatchView"
        )
