"""Named signed requests for the Data-owned quality ledger."""

from typing import cast

from care_link_contracts import validate_contract
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from .evaluation import Evaluation
from .governance_app import Envelope


def attach_evaluation_gateway(app: FastAPI, evaluation: Evaluation, envelope: Envelope) -> None:
    async def create(request: Request) -> JSONResponse:
        actor, key, arguments, _paths = await envelope(request, "replay_create")
        result = await run_in_threadpool(evaluation.replay_create, actor, key, arguments)
        validate_contract("EvaluationView", result)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    async def read(request: Request) -> JSONResponse:
        actor, _key, _arguments, paths = await envelope(request, "evaluation_read")
        result = await run_in_threadpool(
            evaluation.evaluation_read, actor, cast(str, paths["evaluation_id"])
        )
        validate_contract("EvaluationView", result)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    app.add_api_route("/internal/v1/data/replay_create", create, methods=["POST"])
    app.add_api_route("/internal/v1/data/evaluation_read", read, methods=["POST"])
