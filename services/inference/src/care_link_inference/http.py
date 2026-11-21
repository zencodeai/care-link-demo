"""Fixed authenticated inference transport adapters."""

import ssl
from collections.abc import Callable
from datetime import datetime
from typing import cast

import httpx
from care_link_contracts import ContractError, parse_contract
from fastapi import FastAPI, Request, Response
from starlette.concurrency import run_in_threadpool

from .admission import InferenceDenied
from .gateway import BrokerRequest, InferenceGateway

BRIDGE_ENDPOINT = "https://host-inference-bridge:8443/internal/v1/inference/execute"


class HttpBridge:
    def __init__(
        self,
        tls: ssl.SSLContext,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if tls.verify_mode != ssl.CERT_REQUIRED or not tls.check_hostname:
            raise ValueError("authenticated bridge TLS required")
        self.client = httpx.Client(
            verify=tls,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        )

    def complete(self, payload: dict[str, object], deadline: datetime) -> bytes:
        from datetime import UTC

        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if not 0 < remaining <= 30:
            raise TimeoutError("inference deadline expired")
        try:
            with self.client.stream(
                "POST",
                BRIDGE_ENDPOINT,
                json={"payload": payload, "deadline": deadline.isoformat().replace("+00:00", "Z")},
                timeout=remaining,
            ) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > 65536 or datetime.now(UTC) >= deadline:
                        raise OSError("bridge response completion unverified")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPError as error:
            raise OSError("bridge completion unverified") from error

    def close(self) -> None:
        self.client.close()


def create_app(
    gateway: InferenceGateway,
    verify: Callable[[Request, str], bool],
    resolve: Callable[[dict[str, object]], BrokerRequest],
) -> FastAPI:
    """Only authenticated broker input can be resolved to current stored scope.

    resolve must compare all supplied pins/items to server-owned task context;
    a valid transport envelope does not itself establish business authority.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    async def execute(request: Request) -> Response:
        if not verify(request, "core"):
            return Response(status_code=403)
        raw = await request.body()
        if len(raw) > 262144:
            return Response(status_code=413)
        try:
            body = cast(dict[str, object], parse_contract("InferenceRequest", raw.decode()))
            scoped = await run_in_threadpool(resolve, body)
            if (
                body["task_id"] != scoped.task_id
                or body["step_id"] != scoped.step_id
                or body["fence"] != scoped.fence
                or body["function"] != scoped.function
                or body["model_digest"] != gateway.manifest.artifact_digest
                or body["job_id"] != scoped.job_id
                or body["items"] != list(scoped.items)
                or body["deadline"] != scoped.deadline.isoformat().replace("+00:00", "Z")
                or cast(dict[str, object], body["budgets"])["context_tokens"]
                != scoped.context_tokens
                or cast(dict[str, object], body["budgets"])["output_tokens"] != scoped.output_tokens
                or body["prompt_digest"]
                != gateway.manifest.admit(
                    scoped.function, release_verified=gateway.release_verified()
                ).prompt_digest
            ):
                raise InferenceDenied("server_context_mismatch")
            result = await run_in_threadpool(gateway.execute, "broker", scoped)
            from dataclasses import asdict

            from .context import canonical

            response = asdict(result)
            response["model_digest"] = gateway.manifest.artifact_digest
            from care_link_contracts import validate_contract

            validate_contract("InferenceResult", response)
            return Response(canonical(response), media_type="application/json")
        except (ContractError, UnicodeDecodeError, ValueError):
            return Response(status_code=400)
        except InferenceDenied:
            return Response(status_code=503)

    app.add_api_route("/internal/v1/inference/jobs", execute, methods=["POST"])
    return app


INFERENCE_ENDPOINT = "https://inference:8443/internal/v1/inference/jobs"


class HttpInferencePort:
    """Core composition owns this adapter; runtime gets no gateway credentials."""

    def __init__(
        self,
        tls: ssl.SSLContext,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if tls.verify_mode != ssl.CERT_REQUIRED or not tls.check_hostname:
            raise ValueError("authenticated inference TLS required")
        self.client = httpx.Client(
            verify=tls,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
        )

    def infer(self, request: dict[str, object]) -> dict[str, object]:
        from datetime import UTC

        from care_link_contracts import validate_contract

        validate_contract("InferenceRequest", request)
        deadline = datetime.fromisoformat(str(request["deadline"]).replace("Z", "+00:00"))
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if not 0 < remaining <= 30:
            raise InferenceDenied("inference_deadline_expired")
        try:
            with self.client.stream(
                "POST",
                INFERENCE_ENDPOINT,
                json=request,
                timeout=remaining,
            ) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > 65536:
                        raise InferenceDenied("inference_response_too_large")
                    chunks.append(chunk)
            return cast(
                dict[str, object], parse_contract("InferenceResult", b"".join(chunks).decode())
            )
        except (httpx.HTTPError, ContractError, UnicodeDecodeError) as error:
            raise InferenceDenied("inference_unavailable") from error

    def close(self) -> None:
        self.client.close()
