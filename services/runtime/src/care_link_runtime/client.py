"""Untrusted runtime requests broker work using closed fenced references only."""

import json
import ssl
from collections.abc import Mapping
from typing import Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from care_link_contracts import parse_contract, validate_contract

OPERATIONS = {
    "inference_request": (
        "/internal/v1/broker/inference",
        "RuntimeInferenceRequest",
        "InferenceResult",
    ),
    "proposal_submit": ("/internal/v1/broker/proposals", "Proposal", "TaskView"),
    "tool_invoke": ("/internal/v1/broker/tools", "ToolInvoke", "Observation"),
    "step_lease": ("/internal/v1/tasks/{task_id}/lease", "LeaseCommand", "LeaseView"),
    "step_renew": ("/internal/v1/tasks/{task_id}/renew", "LeaseCommand", "LeaseView"),
}


class BrokerTransport(Protocol):
    def invoke(
        self,
        operation: str,
        body: Mapping[str, object],
        *,
        task_id: str | None = None,
    ) -> Mapping[str, object]: ...


class HttpBrokerTransport:
    """Runtime has only a fixed Core destination and no inference/data adapter."""

    def __init__(
        self, tls: ssl.SSLContext, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        if tls.verify_mode != ssl.CERT_REQUIRED or not tls.check_hostname:
            raise ValueError("authenticated broker TLS required")
        self.client = httpx.Client(
            verify=tls, transport=transport, trust_env=False, follow_redirects=False
        )

    def invoke(
        self,
        operation: str,
        body: Mapping[str, object],
        *,
        task_id: str | None = None,
    ) -> Mapping[str, object]:
        if operation not in OPERATIONS:
            raise ValueError("fixed broker operation required")
        path, contract, output = OPERATIONS[operation]
        validate_contract(contract, dict(body))
        if "{task_id}" in path:
            if task_id is None or str(UUID(task_id)) != task_id:
                raise ValueError("canonical task identity required")
            path = path.replace("{task_id}", task_id)
        elif task_id is not None:
            raise ValueError("unexpected task path identity")
        identity = json.dumps(
            [operation, task_id, dict(body)], sort_keys=True, separators=(",", ":")
        )
        key = str(uuid5(NAMESPACE_URL, identity))
        with self.client.stream(
            "POST",
            "https://core:8443" + path,
            json=dict(body),
            headers={"Idempotency-Key": key},
            timeout=30,
        ) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > 65536:
                    raise ValueError("bounded broker response required")
                chunks.append(chunk)
        return cast(Mapping[str, object], parse_contract(output, b"".join(chunks).decode()))

    def close(self) -> None:
        self.client.close()

    def poll_work(self) -> Mapping[str, object]:
        """Claim one metadata-only task; consumed work is never auto-retried."""
        validate_contract("RuntimeWorkRequest", {})
        with self.client.stream(
            "POST",
            "https://core:8443/internal/v1/broker/work",
            json={},
            headers={"Idempotency-Key": str(uuid4())},
            timeout=3,
        ) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_bytes():
                if len(raw) + len(chunk) > 4096:
                    raise ValueError("bounded work receipt required")
                raw.extend(chunk)
        return cast(Mapping[str, object], parse_contract("RuntimeWorkItem", raw.decode()))


class RuntimeClient:
    def __init__(self, broker: BrokerTransport) -> None:
        self.broker = broker

    def inference(
        self,
        *,
        task_id: str,
        step_id: str,
        fence: str,
        expected_task_revision: str,
    ) -> Mapping[str, object]:
        body: dict[str, object] = {
            "task_id": task_id,
            "step_id": step_id,
            "fence": fence,
            "expected_task_revision": expected_task_revision,
        }
        validate_contract("RuntimeInferenceRequest", body)
        return self.broker.invoke("inference_request", body)

    def lease(self, task_id: str, body: Mapping[str, object]) -> Mapping[str, object]:
        validate_contract("LeaseCommand", dict(body))
        return self.broker.invoke("step_lease", body, task_id=task_id)

    def renew(self, task_id: str, body: Mapping[str, object]) -> Mapping[str, object]:
        validate_contract("LeaseCommand", dict(body))
        return self.broker.invoke("step_renew", body, task_id=task_id)

    def propose(self, body: Mapping[str, object]) -> Mapping[str, object]:
        validate_contract("Proposal", dict(body))
        return self.broker.invoke("proposal_submit", body)

    def tool(self, body: Mapping[str, object]) -> Mapping[str, object]:
        validate_contract("ToolInvoke", dict(body))
        return self.broker.invoke("tool_invoke", body)

    def run_one_turn(
        self,
        task_id: str,
        task_revision: str,
        *,
        initial_fence: str = "0",
        renew_interval: float = 5.0,
    ) -> Mapping[str, object]:
        """Execute one bounded graph slice for a previously authorized task."""
        from .workflow import run_workflow

        return run_workflow(
            self,
            task_id,
            task_revision,
            initial_fence=initial_fence,
            renew_interval=renew_interval,
        )
