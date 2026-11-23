"""Closed Data-to-Core request for a fresh proof on an active inference job."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

INFERENCE_ACTOR_PATH = "/internal/v1/broker/inference-authority"
OPERATIONS = frozenset({"context", "current", "reserve", "complete"})
FIELDS = frozenset({"job_id", "task_id", "step_id", "fence", "revision", "operation", "nonce"})


def _uuid(value: object) -> str:
    if not isinstance(value, str) or len(value) != 36 or str(UUID(value)) != value:
        raise ValueError("canonical inference authority identifier required")
    return value


def _counter(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is None
        or int(value) > 9223372036854775807
    ):
        raise ValueError("canonical inference authority counter required")
    return value


@dataclass(frozen=True)
class InferenceActorRequest:
    job_id: str
    task_id: str
    step_id: str
    fence: str
    revision: str
    operation: str
    nonce: str

    @classmethod
    def parse(cls, value: object) -> InferenceActorRequest:
        if not isinstance(value, dict):
            raise ValueError("closed inference authority request required")
        record = cast(dict[str, object], value)
        if frozenset(record) != FIELDS:
            raise ValueError("closed inference authority request required")
        operation = record["operation"]
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise ValueError("fixed inference authority operation required")
        return cls(
            _uuid(record["job_id"]),
            _uuid(record["task_id"]),
            _uuid(record["step_id"]),
            _counter(record["fence"]),
            _counter(record["revision"]),
            operation,
            _uuid(record["nonce"]),
        )

    @classmethod
    def create(
        cls,
        *,
        job_id: object,
        task_id: object,
        step_id: object,
        fence: object,
        revision: object,
        operation: str,
    ) -> InferenceActorRequest:
        return cls.parse(
            {
                "job_id": str(job_id) if isinstance(job_id, UUID) else job_id,
                "task_id": str(task_id) if isinstance(task_id, UUID) else task_id,
                "step_id": str(step_id) if isinstance(step_id, UUID) else step_id,
                "fence": str(fence) if type(fence) is int else fence,
                "revision": str(revision) if type(revision) is int else revision,
                "operation": operation,
                "nonce": str(uuid4()),
            }
        )

    def record(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "fence": self.fence,
            "revision": self.revision,
            "operation": self.operation,
            "nonce": self.nonce,
        }

    @property
    def action(self) -> str:
        return "assistance_inference_" + self.operation

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.record(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("ascii")).hexdigest()
