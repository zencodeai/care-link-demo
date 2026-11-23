"""Data-only, job-bound minting for the broker's live inference calls."""

import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import cast

from care_link_contracts import ContractError, validate_contract
from care_link_domain import (
    INFERENCE_ACTOR_PATH,
    Actor,
    ChannelPort,
    InferenceActorRequest,
    ManualError,
)
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from ..manual_envelopes import IdentityEvidencePort
from .actors import ActorTasks, TaskActorBinding
from .ports import Record


@dataclass(frozen=True)
class _ActiveJob:
    scope: tuple[str, str, str, str]
    binding: TaskActorBinding
    deadline: datetime


class InferenceActorAuthority:
    def __init__(
        self,
        actors: ActorTasks,
        identity: IdentityEvidencePort,
        channels: ChannelPort,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.actors, self.identity, self.channels, self.clock = actors, identity, channels, clock
        self._jobs: dict[str, _ActiveJob] = {}
        self._lock = threading.Lock()

    @contextmanager
    def track(self, request: Record, revision: str, actor: Actor) -> Iterator[None]:
        """Pin the admitted actor and exact job for the lifetime of the upstream call."""
        job_id = cast(str, request["job_id"])
        task_id = cast(str, request["task_id"])
        deadline = datetime.fromisoformat(cast(str, request["deadline"]))
        binding = self.actors.binding(task_id)
        if (
            binding is None
            or binding.revision != revision
            or binding.actor != replace(actor, request_deadline=None)
        ):
            raise ManualError("assistance.actor_resumption_required", 409)
        job = _ActiveJob(
            (task_id, cast(str, request["step_id"]), cast(str, request["fence"]), revision),
            binding,
            min(deadline, binding.expires_at, actor.auth_time + timedelta(minutes=5)),
        )
        with self._lock:
            if job_id in self._jobs:
                raise ManualError("assistance.inference_binding", 409)
            self._jobs[job_id] = job
        try:
            self._current(job_id, job)
            yield
        finally:
            with self._lock:
                self._jobs.pop(job_id)

    def _current(self, job_id: str, job: _ActiveJob) -> None:
        with self._lock:
            if self._jobs.get(job_id) is not job:
                raise ManualError("assistance.inference_binding", 403)
        binding = job.binding
        if self.actors.binding(job.scope[0]) is not binding or self.clock() >= job.deadline:
            raise ManualError("assistance.actor_resumption_required", 409)
        actor = binding.actor
        if actor.role != "worker" or not actor.mfa:
            raise ManualError("assistance.inference_binding", 403)
        if not self.channels.current(
            actor.account_id, actor.browser_session_digest, actor.transport_generation
        ):
            raise ManualError("assistance.channel_changed", 409)

    def mint(self, command: InferenceActorRequest) -> Record:
        with self._lock:
            job = self._jobs.get(command.job_id)
        if job is None or job.scope != (
            command.task_id,
            command.step_id,
            command.fence,
            command.revision,
        ):
            raise ManualError("assistance.inference_binding", 403)
        self._current(command.job_id, job)
        mint_deadline = min(job.deadline, self.clock() + timedelta(seconds=1))
        actor = replace(job.binding.actor, request_deadline=mint_deadline)
        evidence = self.identity.evidence(
            actor, command.action, command.digest, command.nonce, command.task_id
        )
        try:
            validate_contract("IdentityEvidence", evidence)
        except ContractError as error:
            raise ManualError("assistance.identity_unavailable", 503) from error
        issued = datetime.fromisoformat(cast(str, evidence["verified_at"]))
        expiry = datetime.fromisoformat(cast(str, evidence["expires_at"]))
        self._current(command.job_id, job)
        now = self.clock()
        if (
            evidence["principal_id"] != actor.account_id
            or evidence["role"] != actor.role
            or evidence["identity_revision"] != str(actor.identity_revision)
            or evidence["role_revision"] != str(actor.role_revision)
            or evidence["action"] != command.action
            or evidence["request_digest"] != command.digest
            or evidence["nonce"] != command.nonce
            or evidence["resource_id"] != command.task_id
            or any(
                evidence.get(name) != getattr(actor, name)
                for name in ("review_run_id", "review_slot_id", "review_origin")
            )
            or issued > now
            or expiry <= now
            or expiry > job.deadline
            or expiry - issued > timedelta(seconds=1)
            or now >= mint_deadline
        ):
            raise ManualError("assistance.inference_binding", 403)
        return evidence


def _unique(pairs: list[tuple[str, object]]) -> Record:
    result: Record = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate inference authority field")
        result[name] = value
    return result


def attach_inference_authority(
    app: FastAPI, authority: InferenceActorAuthority, verify: Callable[[Request], bool]
) -> None:
    async def handle(request: Request) -> JSONResponse:
        if not await run_in_threadpool(verify, request):
            raise ManualError("assistance.data_required", 403)
        if request.query_params:
            raise ManualError("manual.invalid_query", 400)
        if request.headers.get("content-encoding") is not None or request.headers.get(
            "content-type", ""
        ).lower().replace(" ", "") not in {"application/json", "application/json;charset=utf-8"}:
            raise ManualError("manual.json_required", 415)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 2048:
                raise ManualError("manual.body_too_large", 413)
            raw.extend(chunk)
        try:
            command = InferenceActorRequest.parse(
                json.loads(raw.decode(), object_pairs_hook=_unique)
            )
        except ValueError as error:
            raise ManualError("manual.invalid_request", 400) from error
        evidence = await run_in_threadpool(authority.mint, command)
        if not await run_in_threadpool(verify, request):
            raise ManualError("assistance.data_required", 403)
        return JSONResponse(evidence, headers={"Cache-Control": "no-store"})

    app.add_api_route(INFERENCE_ACTOR_PATH, handle, methods=["POST"])
