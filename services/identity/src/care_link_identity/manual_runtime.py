"""Authenticated remote manual identity authority; browser credentials stay in custody.

Every resolution rechecks the current provider and durable account/session state.
Request references expire with the original signed evidence and cannot renew it.
"""

import json
import re
import secrets
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import cast
from uuid import uuid4

import psycopg
from care_link_contracts import ContractError, validate_contract
from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .crypto import canonical
from .domain import IdentityError, instant, stamp, text
from .manual import ManualIdentityAuthority
from .service import IdentityService

Record = dict[str, object]
PREFIX = "/internal/v1/manual-identity/"


def _actor_record(actor: Actor) -> Record:
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


def _no_duplicates(pairs: list[tuple[str, object]]) -> Record:
    result: Record = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def create_manual_identity_app(
    service: IdentityService,
    workload_verifier: Callable[[Request, str], bool],
    *,
    service_for_session: Callable[[str], IdentityService] | None = None,
) -> FastAPI:
    """Expose exact core/data mesh routes; never mount on a browser origin."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def selected(raw: str) -> IdentityService:
        return service_for_session(raw) if service_for_session else service

    async def failed(_request: Request, error: Exception) -> JSONResponse:
        status = error.status if isinstance(error, (ManualError, IdentityError)) else 503
        return JSONResponse(
            {"state": "identity_denied" if status < 500 else "identity_unavailable"},
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    for kind in (ManualError, IdentityError, psycopg.Error):
        app.add_exception_handler(kind, failed)

    def lookup(reference: str) -> tuple[Actor, Record]:
        with service.store.transaction() as tx:
            proof = tx.get("proof", reference)
        if (
            proof is None
            or proof.get("audience") != "care-link-data-manual"
            or instant(proof["expires_at"]) <= service.clock()
        ):
            raise ManualError("manual.identity_evidence_expired")
        raw = service.custody.decrypt(text(proof, "credential"))
        actor = ManualIdentityAuthority(selected(raw)).authenticate(raw)
        evidence = cast(Record, proof["evidence"])
        if (
            actor.account_id != evidence["principal_id"]
            or actor.role != evidence["role"]
            or str(actor.identity_revision) != evidence["identity_revision"]
            or str(actor.role_revision) != evidence["role_revision"]
            or any(
                getattr(actor, field) != evidence.get(field)
                for field in ("review_run_id", "review_slot_id", "review_origin")
            )
            or instant(proof["expires_at"]) <= service.clock()
        ):
            raise ManualError("manual.identity_changed")
        return replace(
            actor,
            transport_generation=int(text(proof, "transport_generation")),
            credential_ref=reference,
            identity_evidence_id=reference,
            request_deadline=instant(proof["expires_at"]),
        ), proof

    def execute(name: str, data: Record) -> Record:
        fields = {
            "authenticate": {"raw_session"},
            "csrf": {"raw_session", "origin", "supplied"},
            "evidence": {
                "raw_session",
                "transport_generation",
                "action",
                "request_digest",
                "nonce",
                "resource_id",
            },
            "resolve": {"evidence"},
            "current": {"credential_ref"},
            "recovery": {"credential_ref", "ceremony_id", "session_id", "family_id"},
            "consent-proof": {
                "credential_ref",
                "proof_id",
                "subject_id",
                "session_id",
                "purpose",
                "basis",
            },
        }
        if set(data) != fields[name]:
            raise ManualError("manual.invalid_identity_request", 422)
        if name in {"authenticate", "csrf", "evidence"}:
            active_service = selected(text(data, "raw_session"))
        else:
            active_service = service
        authority = ManualIdentityAuthority(active_service)
        if name == "authenticate":
            return _actor_record(authority.authenticate(text(data, "raw_session")))
        if name == "csrf":
            actor = authority.authenticate(text(data, "raw_session"))
            authority.csrf(
                actor, cast(str | None, data["origin"]), cast(str | None, data["supplied"])
            )
            return {"verified": True}
        if name == "evidence":
            generation = text(data, "transport_generation")
            if (
                not re.fullmatch(r"0|[1-9][0-9]{0,18}", generation)
                or int(generation) > 9223372036854775807
            ):
                raise ManualError("manual.invalid_identity_request", 422)
            actor = authority.authenticate(text(data, "raw_session"))
            now = service.clock()
            reference = str(uuid4())
            expires = min(now + timedelta(seconds=0.95), actor.expires_at)
            evidence: Record = {
                "id": reference,
                "principal_id": actor.account_id,
                "role": actor.role,
                "identity_revision": str(actor.identity_revision),
                "role_revision": str(actor.role_revision),
                "action": data["action"],
                "resource_id": data["resource_id"],
                "request_digest": data["request_digest"],
                "nonce": data["nonce"],
                "verified_at": stamp(now),
                "expires_at": stamp(expires),
                "kind": "human_identity",
            }
            if actor.review_run_id is not None:
                evidence.update(
                    {
                        "review_run_id": actor.review_run_id,
                        "review_slot_id": actor.review_slot_id,
                        "review_origin": actor.review_origin,
                    }
                )
            evidence["signature"] = active_service.signer.sign(evidence)
            validate_contract("IdentityEvidence", evidence)
            # Reuse the existing short-lived proof custody table, not a new
            # authority store or a bearer credential in business storage.
            with service.store.transaction() as tx:
                tx.put(
                    "proof",
                    reference,
                    {
                        "audience": "care-link-data-manual",
                        "expires_at": stamp(expires),
                        "session_hash": actor.browser_session_digest,
                        "account_id": actor.account_id,
                        "credential": service.custody.encrypt(actor.credential_ref),
                        "transport_generation": generation,
                        "evidence": evidence,
                    },
                )
            return evidence
        if name == "resolve":
            supplied_evidence = data["evidence"]
            if not isinstance(supplied_evidence, dict):
                raise ManualError("manual.invalid_identity_request", 422)
            value = cast(Record, supplied_evidence)
            validate_contract("IdentityEvidence", value)
            actor, proof = lookup(text(value, "id"))
            if not secrets.compare_digest(
                canonical(value), canonical(cast(Record, proof["evidence"]))
            ):
                raise ManualError("manual.identity_evidence_changed")
            return _actor_record(actor)
        actor, proof = lookup(text(data, "credential_ref"))
        if name == "consent-proof":
            raw = service.custody.decrypt(text(proof, "credential"))
            ManualIdentityAuthority(selected(raw)).consent_proof(
                replace(actor, credential_ref=raw),
                text(data, "proof_id"),
                text(data, "subject_id"),
                text(data, "session_id"),
                text(data, "purpose"),
                text(data, "basis"),
            )
            if actor.request_deadline is None or actor.request_deadline <= service.clock():
                raise ManualError("manual.identity_evidence_expired")
            return {"verified": True}
        if name == "recovery":
            raw = service.custody.decrypt(text(proof, "credential"))
            ManualIdentityAuthority(selected(raw)).recovery_proof(
                replace(actor, credential_ref=raw),
                text(data, "ceremony_id"),
                text(data, "session_id"),
                text(data, "family_id"),
            )
            if actor.request_deadline is None or actor.request_deadline <= service.clock():
                raise ManualError("manual.identity_evidence_expired")
            return {"verified": True}
        return _actor_record(actor)

    def route(name: str, peer: str) -> None:
        async def handler(request: Request) -> JSONResponse:
            if not workload_verifier(request, peer):
                raise ManualError("manual.workload_denied")
            if (
                request.query_params
                or request.headers.get("content-encoding") is not None
                or request.headers.get("content-type", "").lower().replace(" ", "")
                not in {"application/json", "application/json;charset=utf-8"}
            ):
                raise ManualError("manual.invalid_identity_request", 415)
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 65536:
                    raise ManualError("manual.body_too_large", 413)
            try:
                value: object = json.loads(raw, object_pairs_hook=_no_duplicates)
                if not isinstance(value, dict):
                    raise ValueError("object required")
                result = await run_in_threadpool(execute, name, cast(Record, value))
            except (ValueError, TypeError, KeyError, ContractError) as error:
                raise ManualError("manual.invalid_identity_request", 422) from error
            return JSONResponse(result, headers={"Cache-Control": "no-store"})

        app.add_api_route(PREFIX + name, handler, methods=["POST"])

    for name in ("authenticate", "csrf", "evidence"):
        route(name, "core")
    for name in ("resolve", "current", "recovery", "consent-proof"):
        route(name, "data")
    return app
