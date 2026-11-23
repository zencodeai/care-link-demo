"""Fail closed under LD-13 without consuming a step-up or writing a link."""

from care_link_domain import ManualError
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse


def attach_disabled_identity_link(app: FastAPI) -> None:
    async def deny(_request: Request) -> JSONResponse:
        raise ManualError("manual.capability_disabled")

    app.add_api_route("/internal/v1/data/identity_link_request", deny, methods=["POST"])
