"""Closed browser routes for training and offline evaluation."""

import asyncio
from collections.abc import Callable
from typing import Protocol

from care_link_domain import Actor, ManualError
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .manual_channels import ManualChannels
from .planning_routes import Authenticate, Record


class TrainingGateway(Protocol):
    def scenario_create(self, actor: Actor, key: str, data: Record) -> Record: ...
    def scenario_read(self, actor: Actor, scenario_id: str) -> Record: ...
    def scenario_stop(self, actor: Actor, key: str, scenario_id: str, data: Record) -> Record: ...


class EvaluationGateway(Protocol):
    def replay_create(self, actor: Actor, key: str, data: Record) -> Record: ...
    def evaluation_read(self, actor: Actor, evaluation_id: str) -> Record: ...


def attach_training_routes(
    app: FastAPI,
    authenticate: Authenticate,
    channels: ManualChannels,
    training: TrainingGateway | None,
    evaluation: EvaluationGateway | None,
) -> None:
    from .manual_app import body, identifier, response

    def attach(
        path: str,
        method: str,
        roles: frozenset[str],
        output: str,
        execute: Callable[..., Record],
        *,
        contract: str | None = None,
        resource: str | None = None,
    ) -> None:
        async def handler(request: Request) -> JSONResponse:
            if request.query_params:
                raise ManualError("manual.invalid_query", 400)
            current = await authenticate(request, mutation=method == "POST")
            if current.role not in roles or not current.mfa:
                raise ManualError("training.actor_denied")
            args: list[object] = [current]
            if contract:
                args.append(identifier(request.headers.get("idempotency-key", "")))
            if resource:
                args.append(identifier(request.path_params[resource]))
            if contract:
                args.append(await body(request, contract))
            if output == "EvaluationView" and not channels.current(
                current.account_id, current.browser_session_digest, current.transport_generation
            ):
                # Replay actors need no access to a participant session stream. Bind the
                # authenticated, CSRF-checked request while Data verifies its current channel.
                with channels.open(current) as connected:

                    async def observe_disconnect() -> None:
                        while (await request.receive())["type"] != "http.disconnect":
                            pass
                        channels.disconnect(connected)

                    observer = asyncio.create_task(observe_disconnect())
                    try:
                        result = await run_in_threadpool(execute, connected, *args[1:])
                    finally:
                        observer.cancel()
                        await asyncio.gather(observer, return_exceptions=True)
            else:
                result = await run_in_threadpool(execute, *args)
            return response(output, result)

        app.add_api_route(path, handler, methods=[method])

    async def identity_link_disabled(_request: Request) -> JSONResponse:
        # LD-13 applies independently of the submitted body, browser or step-up.
        raise ManualError("manual.capability_disabled")

    app.add_api_route("/v1/identity-links", identity_link_disabled, methods=["POST"])
    trainer = frozenset({"trainer"})
    if training is not None:
        attach(
            "/v1/training/scenarios",
            "POST",
            trainer,
            "CommandResult",
            training.scenario_create,
            contract="ScenarioCreate",
        )
        scenario = "/v1/training/scenarios/{scenario_id}"
        attach(
            scenario, "GET", trainer, "ScenarioView", training.scenario_read, resource="scenario_id"
        )
        attach(
            scenario + "/stop",
            "POST",
            trainer,
            "CommandResult",
            training.scenario_stop,
            contract="RevisionCommand",
            resource="scenario_id",
        )
    if evaluation is not None:
        roles = trainer | {"governance"}
        attach(
            "/v1/evaluation/replays",
            "POST",
            roles,
            "EvaluationView",
            evaluation.replay_create,
            contract="ReplayCreate",
        )
        attach(
            "/v1/evaluation/replays/{evaluation_id}",
            "GET",
            roles,
            "EvaluationView",
            evaluation.evaluation_read,
            resource="evaluation_id",
        )
