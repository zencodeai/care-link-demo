"""Help application service: fresh authority before every spool operation."""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

from care_link_contracts import validate_contract

from .model import (
    Action,
    Authority,
    BrowserContext,
    Clock,
    HelpError,
    ReceiptVerifier,
    Wire,
    digest,
    now_utc,
    timestamp,
)
from .spool import Spool


class HelpService:
    def __init__(
        self,
        spool: Spool,
        authority: Authority,
        verifier: ReceiptVerifier,
        *,
        clock: Clock = now_utc,
    ) -> None:
        self.spool = spool
        self.authority = authority
        self.verifier = verifier
        self.clock = clock

    def prepare_create(self, body: Wire, context: BrowserContext, proof: Callable[[], str]) -> Wire:
        """Recover the same logical key across session rotation and lost replies.

        A concurrent loser reauthorizes for the winner's exact target. Positive
        authority is never reused when selecting a different target.
        """
        validate_contract("HelpCreate", body)
        for _ in range(3):
            candidate = self.spool.intents.candidate(context.account_id)
            request: Wire = {
                "operation_id": candidate.operation_id,
                "help_id": candidate.help_id,
                "action": "create",
                "request_digest": digest(body),
                "browser_proof_ref": proof(),
                "nonce": str(uuid4()),
                "deadline": timestamp(self.clock() + timedelta(seconds=1)),
            }
            validate_contract("HelpAuthorityRequest", request)
            receipt = self.authority.authorize(request)
            decision = self.verifier.verify(request, receipt, context.account_id)
            try:
                operation_id = self.spool.intents.save(candidate, digest(body), context, decision)
                result: Wire = {"operation_id": operation_id}
                validate_contract("HelpCreateIntent", result)
                return result
            except HelpError as error:
                if error.code != "help.intent_race":
                    raise
        raise HelpError("help.intent_busy", 409)

    def execute(
        self,
        *,
        action: Action,
        operation_id: str,
        help_id: str | None,
        body: Wire,
        context: BrowserContext,
        proof_ref: str,
    ) -> Wire:
        UUID(operation_id)
        UUID(proof_ref)
        validate_contract(
            "HelpCreate"
            if action == "create"
            else "RevisionCommand"
            if action in {"accept", "cancel"}
            else "Empty",
            body,
        )
        # A stable opaque target for retry: knowing it confers no access. The
        # random idempotency UUID is never an identity or ownership credential.
        target = str(uuid5(UUID(operation_id), "care-link-help")) if action == "create" else help_id
        if target is None:
            raise HelpError("help.not_found", 404)
        UUID(target)
        request: Wire = {
            "operation_id": operation_id,
            "help_id": target,
            "action": action,
            "request_digest": digest(body),
            "browser_proof_ref": proof_ref,
            "nonce": str(uuid4()),
            "deadline": timestamp(self.clock() + timedelta(seconds=1)),
        }
        validate_contract("HelpAuthorityRequest", request)
        receipt = self.authority.authorize(request)
        decision = self.verifier.verify(request, receipt, context.account_id)
        revision = body.get("expected_revision")
        return self.spool.apply(
            action=action,
            help_id=target,
            operation_id=operation_id,
            body_digest=digest(body),
            context=context,
            decision=decision,
            expected_revision=revision if isinstance(revision, str) else None,
        )
