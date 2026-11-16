"""Private BFF transport. Composition injects current authenticated workload peers.

There is deliberately no module-global application with permissive defaults.
TLS/proxy and independently retained account policy qualification remain deployment
inputs; source construction alone grants no participant admission.
"""

import secrets
from collections.abc import Callable
from typing import cast
from uuid import UUID, uuid4

import psycopg
from care_link_contracts import ContractError, parse_contract, validate_contract
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse, Response

from . import stepup
from .crypto import digest, token
from .domain import IdentityError, instant, stamp, text
from .service import IdentityService
from .signals import SignalReceiver

BINDING_COOKIE = "__Host-care-link-binding"
SESSION_COOKIE = "__Host-care-link-session"
BODY_LIMIT = 64 * 1024


def create_app(
    service: IdentityService | None = None,
    *,
    signals: SignalReceiver | None = None,
    workload_verifier: Callable[[Request, str], bool] | None = None,
    session_cookie: str = SESSION_COOKIE,
    ui_return_url: str | None = None,
) -> FastAPI:
    if ui_return_url is not None:
        from urllib.parse import urlsplit

        if (
            service is None
            or not ui_return_url.startswith(service.origin + "/")
            or urlsplit(ui_return_url).fragment
        ):
            raise ValueError("UI return must be a fixed same-origin HTTPS route")
    app = FastAPI(
        title="CARE-Link private identity", docs_url=None, redoc_url=None, openapi_url=None
    )

    def configured() -> IdentityService:
        if service is None:
            raise IdentityError("identity.unconfigured", 503)
        return service

    async def identity_error(_request: Request, error: Exception) -> Response:
        if isinstance(error, IdentityError):
            status, key = error.status, error.code
        elif isinstance(error, ContractError):
            status, key = 422, "identity.invalid_request"
        else:
            status, key = 503, "identity.store_unavailable"
        if (
            _request.url.path == "/v1/auth/callback"
            and service is not None
            and service.review_context is not None
            and ui_return_url is not None
        ):
            separator = "&" if "?" in ui_return_url else "?"
            return RedirectResponse(
                ui_return_url + separator + "auth_error=sign_in_interrupted",
                status_code=303,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        code = (
            "AUTHORITY_UNAVAILABLE"
            if status >= 500
            else (
                "UNAUTHENTICATED"
                if status == 401
                else "NOT_AUTHORIZED"
                if status == 403
                else "INVALID_REQUEST"
            )
        )
        payload: dict[str, object] = {
            "code": code,
            "request_id": str(uuid4()),
            "retryable": status >= 500,
            "message_key": key,
            "operation_id": None,
            "retry_after_ms": None,
        }
        validate_contract("Error", payload)
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    app.add_exception_handler(IdentityError, identity_error)
    app.add_exception_handler(ContractError, identity_error)
    app.add_exception_handler(psycopg.Error, identity_error)

    def respond(name: str, value: dict[str, object]) -> JSONResponse:
        validate_contract(name, value)
        return JSONResponse(
            value,
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            },
        )

    async def body(request: Request, name: str) -> dict[str, object]:
        if request.headers.get("content-encoding") is not None:
            raise IdentityError("identity.compression_denied", 415)
        if request.headers.get("content-type", "").lower().replace(" ", "") not in {
            "application/json",
            "application/json;charset=utf-8",
        }:
            raise IdentityError("identity.json_required", 415)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > BODY_LIMIT:
                raise IdentityError("identity.body_too_large", 413)
        try:
            return cast(
                dict[str, object], parse_contract(name, raw.decode("utf-8", errors="strict"))
            )
        except UnicodeError as error:
            raise IdentityError("identity.invalid_json", 400) from error

    def raw_cookie(request: Request) -> str:
        raw = request.cookies.get(session_cookie)
        if raw is None:
            raise IdentityError("identity.session_unavailable", 401)
        return raw

    def csrf(request: Request, anonymous: bool = False, logout_only: bool = False) -> None:
        authority = configured()
        if request.headers.get("origin") != authority.origin:
            raise IdentityError("identity.origin_denied")
        supplied = request.headers.get("x-csrf-token", "")
        if anonymous and request.cookies.get(session_cookie):
            with authority.store.transaction() as tx:
                session_record = tx.get("session", digest(raw_cookie(request)))
                if session_record and session_record.get("origin") == authority.origin:
                    expected = text(session_record, "csrf")
                    if supplied and secrets.compare_digest(supplied, expected):
                        return
        if anonymous:
            binding = request.cookies.get(BINDING_COOKIE, "")
            with authority.store.transaction() as tx:
                record = tx.get("proof", "csrf:" + digest(binding))
                if record is None or instant(record["expires_at"]) <= authority.clock():
                    raise IdentityError("identity.csrf_denied")
                expected = text(record, "csrf")
        elif logout_only:
            with authority.store.transaction() as tx:
                session_record = tx.get("session", digest(raw_cookie(request)))
                if session_record is None or session_record.get("origin") != authority.origin:
                    raise IdentityError("identity.csrf_denied")
                expected = text(session_record, "csrf")
        else:
            expected = text(authority.current(raw_cookie(request)), "csrf")
        if not supplied or not secrets.compare_digest(supplied, expected):
            raise IdentityError("identity.csrf_denied")

    def internal(request: Request, peer: str) -> None:
        if workload_verifier is None or not workload_verifier(request, peer):
            raise IdentityError("identity.workload_denied")

    async def bootstrap(request: Request) -> JSONResponse:
        from datetime import timedelta

        authority = configured()
        raw = request.cookies.get(session_cookie)
        if raw:
            # CSRF metadata grants no permission. Local lookup permits protective
            # sign-out while upstream authority is down; private effects still
            # perform their fresh current() check independently.
            with authority.store.transaction() as tx:
                session_record = tx.get("session", digest(raw))
                if (
                    session_record
                    and session_record.get("origin") == authority.origin
                    and isinstance(session_record.get("csrf"), str)
                    and len(cast(str, session_record["csrf"])) >= 32
                ):
                    binding = request.cookies.get(BINDING_COOKIE, "")
                    response = respond("BrowserCsrf", {"csrf_token": session_record["csrf"]})
                    if not binding or digest(binding) != session_record.get("binding"):
                        # Possession of this origin's server session permits only
                        # rebinding protocol metadata. Fresh login/step-up still
                        # requires its own bound intent and provider validation.
                        binding = token()
                        session_record["binding"] = digest(binding)
                        tx.put("session", digest(raw), session_record)
                        response.set_cookie(
                            BINDING_COOKIE,
                            binding,
                            secure=True,
                            httponly=True,
                            samesite="lax",
                            max_age=3600,
                        )
                    return response
        existing_binding = request.cookies.get(BINDING_COOKIE, "")
        if existing_binding and authority.review_context is not None:
            with authority.store.transaction() as tx:
                existing = tx.get("proof", "csrf:" + digest(existing_binding))
                if (
                    existing
                    and existing.get("origin") == authority.origin
                    and instant(existing["expires_at"]) > authority.clock()
                ):
                    return respond("BrowserCsrf", {"csrf_token": text(existing, "csrf")})
        binding, proof = token(), token()
        with authority.store.transaction() as tx:
            tx.put(
                "proof",
                "csrf:" + digest(binding),
                {
                    "csrf": proof,
                    "expires_at": stamp(authority.clock() + timedelta(minutes=5)),
                    "origin": authority.origin,
                },
            )
        response = respond("BrowserCsrf", {"csrf_token": proof})
        response.set_cookie(
            BINDING_COOKIE, binding, secure=True, httponly=True, samesite="lax", max_age=3600
        )
        return response

    async def login(request: Request) -> JSONResponse:
        data = await body(request, "LoginStart")
        await run_in_threadpool(csrf, request, True)
        role = text(data, "role")
        routes = {
            "pid": "participant",
            "carer": "participant",
            "professional_participant": "participant",
            "worker": "workforce",
            "supervisor": "workforce",
            "receiver": "workforce",
            "operator": "operations",
            "security": "operations",
            "governance": "governance",
            "auditor": "audit",
            "trainer": "training",
        }
        if data["return_route"] != routes[role]:
            raise IdentityError("identity.return_route_denied")
        binding = request.cookies.get(BINDING_COOKIE, "")
        if not binding:
            raise IdentityError("identity.browser_binding_required")
        result, _state = await run_in_threadpool(
            configured().login_start,
            role,
            binding,
            previous_raw_session=request.cookies.get(session_cookie),
        )
        return respond("LoginIntent", result)

    async def callback(request: Request) -> Response:
        pairs = list(request.query_params.multi_items())
        values = dict(pairs)
        if len(pairs) != len(values) or not set(values) <= {
            "state",
            "code",
            "iss",
            "error",
            "error_description",
            "session_state",
        }:
            raise IdentityError("identity.callback_denied")
        if not values.get("state") or not 32 <= len(values["state"]) <= 512:
            raise IdentityError("identity.callback_denied")
        if "error" in values and "code" in values:
            raise IdentityError("identity.callback_denied")
        limits = {
            "iss": 512,
            "error": 128,
            "error_description": 512,
            "session_state": 512,
            "code": 2048,
            "state": 512,
        }
        if any(
            len(value) > limits[key]
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            for key, value in values.items()
        ):
            raise IdentityError("identity.callback_denied")
        if "error" not in values:
            candidate: dict[str, object] = {
                "state": values["state"],
                "code": values.get("code", ""),
            }
            if "iss" in values:
                candidate["iss"] = values["iss"]
            validate_contract("LoginCallback", candidate)
        view, raw, proof_id = await run_in_threadpool(
            configured().callback,
            values["state"],
            values.get("code", ""),
            request.cookies.get(BINDING_COOKIE, ""),
            values.get("iss"),
            "error" in values,
        )
        response: Response
        if "text/html" in request.headers.get("accept", "") and ui_return_url is not None:
            response = RedirectResponse(
                ui_return_url, status_code=303, headers={"Cache-Control": "no-store"}
            )
        else:
            response = respond("BrowserSession", view)
        if raw:
            response.set_cookie(
                session_cookie, raw, secure=True, httponly=True, samesite="lax", max_age=3600
            )
            # The callback has just validated this exact binding. Renew it with
            # the replacement session so later ceremonies keep the same proof.
            response.set_cookie(
                BINDING_COOKIE,
                request.cookies[BINDING_COOKIE],
                secure=True,
                httponly=True,
                samesite="lax",
                max_age=3600,
            )
        if proof_id:
            response.headers["X-Proof-Intent-Id"] = proof_id
        return response

    async def session(request: Request) -> JSONResponse:
        view = await run_in_threadpool(configured().session_view, raw_cookie(request))
        response = respond("BrowserSession", view)
        authority = configured()
        with authority.store.transaction() as tx:
            candidates = [
                (key, item)
                for key, item in tx.items("ceremony")
                if item.get("session_hash") == digest(raw_cookie(request))
                and item.get("state") in {"pending", "cooling_off"}
                and instant(item["expires_at"]) > authority.clock()
            ]
        if candidates:
            ceremony_id, _ceremony = max(candidates, key=lambda pair: text(pair[1], "expires_at"))
            response.headers["X-Ceremony-Id"] = ceremony_id
        return response

    async def logout(request: Request) -> JSONResponse:
        await body(request, "Empty")
        await run_in_threadpool(csrf, request, False, True)
        try:
            operation_id = str(UUID(request.headers.get("idempotency-key", "")))
        except ValueError as error:
            raise IdentityError("identity.operation_id_required", 400) from error
        result = await run_in_threadpool(configured().logout, raw_cookie(request), operation_id)
        response = respond("CommandResult", result)
        response.delete_cookie(session_cookie, secure=True, httponly=True, samesite="lax")
        return response

    async def stepup_start(request: Request) -> JSONResponse:
        data = await body(request, "StepUpStart")
        await run_in_threadpool(csrf, request)
        binding = request.cookies.get(BINDING_COOKIE, "")
        if not binding:
            raise IdentityError("identity.browser_binding_required")
        result = await run_in_threadpool(
            stepup.start, configured(), raw_cookie(request), binding, data
        )
        return respond("Ceremony", result)

    async def stepup_confirm(request: Request) -> JSONResponse:
        data = await body(request, "CeremonyConfirm")
        await run_in_threadpool(csrf, request)
        result = await run_in_threadpool(stepup.confirm, configured(), raw_cookie(request), data)
        return respond("Ceremony", result)

    async def stepup_proof(request: Request) -> JSONResponse:
        authority = configured()
        await run_in_threadpool(authority.current, raw_cookie(request))
        pairs = list(request.query_params.multi_items())
        if len(pairs) != 1 or pairs[0][0] != "ceremony_id":
            raise IdentityError("identity.invalid_ceremony")
        ceremony_id = pairs[0][1]
        try:
            if str(UUID(ceremony_id)) != ceremony_id:
                raise ValueError("noncanonical ceremony UUID")
        except ValueError as error:
            raise IdentityError("identity.invalid_ceremony") from error
        with authority.store.transaction() as tx:
            ceremony = tx.get("ceremony", ceremony_id)
            if ceremony is None or ceremony.get("session_hash") != digest(raw_cookie(request)):
                raise IdentityError("identity.invalid_ceremony")
            candidates = [
                value
                for _key, value in tx.items("intent")
                if value.get("ceremony_id") == ceremony_id
                and value.get("state") == "completed"
                and value.get("proof_consumed") is False
            ]
        if not candidates:
            raise IdentityError("identity.proof_pending", 409)
        selected = max(candidates, key=lambda item: text(item, "proof_auth_time"))
        proof_id = text(selected, "id")
        UUID(proof_id)
        return respond("StepUpProof", {"proof_intent_id": proof_id})

    async def continuation_recovery(request: Request) -> JSONResponse:
        from .manual import start_recovery

        data = await body(request, "ContinuationRecoveryStart")
        await run_in_threadpool(csrf, request)
        binding = request.cookies.get(BINDING_COOKIE, "")
        if not binding:
            raise IdentityError("identity.browser_binding_required")
        result = await run_in_threadpool(
            start_recovery, configured(), raw_cookie(request), binding, data
        )
        return respond("Ceremony", result)

    async def help_authorize(request: Request) -> JSONResponse:
        internal(request, "help")
        data = await body(request, "HelpAuthorityRequest")
        result = await run_in_threadpool(configured().help_authorize, data)
        return respond("FreshHelpAuthority", result)

    async def signal_ingest(request: Request) -> JSONResponse:
        internal(request, "identity_provider")
        data = await body(request, "Signal")
        if signals is None:
            raise IdentityError("identity.signals_unconfigured", 503)
        result = await run_in_threadpool(signals.ingest, data)
        return respond("SignalAck", result)

    # Trusted BFF adapter endpoints do not expose browser proofs to browser callers.
    # The channel verifier binds service identity plus current fence per request.
    async def help_context(request: Request) -> JSONResponse:
        internal(request, "help")
        raw = request.headers.get("x-help-session", "")
        result = await run_in_threadpool(configured().browser_context, raw)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    async def help_proof(request: Request) -> JSONResponse:
        internal(request, "help")
        proof = await run_in_threadpool(
            configured().issue_help_proof,
            request.headers.get("x-help-session", ""),
            request.headers.get("x-help-origin", ""),
        )
        return JSONResponse({"proof_ref": proof}, headers={"Cache-Control": "no-store"})

    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "process_alive": True,
                "participant_admission": False,
                "configured": service is not None,
            },
            headers={"Cache-Control": "no-store"},
        )

    app.add_api_route("/v1/auth/csrf", bootstrap, methods=["GET"])
    app.add_api_route("/v1/auth/login", login, methods=["POST"])
    app.add_api_route("/v1/auth/callback", callback, methods=["GET"])
    app.add_api_route("/v1/auth/session", session, methods=["GET"])
    app.add_api_route("/v1/auth/logout", logout, methods=["POST"])
    app.add_api_route("/v1/auth/continuation-recovery", continuation_recovery, methods=["POST"])
    app.add_api_route("/v1/auth/step-up", stepup_start, methods=["POST"])
    app.add_api_route("/v1/auth/step-up/confirm", stepup_confirm, methods=["POST"])
    app.add_api_route("/v1/auth/step-up/proof", stepup_proof, methods=["GET"])
    app.add_api_route("/internal/v1/identity/help-authorize", help_authorize, methods=["POST"])
    app.add_api_route("/internal/v1/identity/signals", signal_ingest, methods=["POST"])
    app.add_api_route("/internal/v1/identity/help-browser-context", help_context, methods=["POST"])
    app.add_api_route("/internal/v1/identity/help-browser-proof", help_proof, methods=["POST"])
    app.add_api_route("/health/live", health, methods=["GET"])
    return app
