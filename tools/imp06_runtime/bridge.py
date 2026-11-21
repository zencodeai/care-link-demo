"""Host-only fixed loopback bridge; release changes stop optional generation."""

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import lmstudio as lms
from care_link_domain import ManualError
from care_link_inference_bridge import (
    LocalModelBridge,
    TokenizationDenied,
    TokenReceipt,
    create_app,
)
from care_link_inference_bridge.credentials import read_api_token
from care_link_inference_bridge.loaded import bind_loaded_model
from fastapi import FastAPI, Request

from .releases import Record, ReleaseBindings


def bridge_application(
    releases: ReleaseBindings,
    verify: Callable[[Request, str], bool],
    *,
    artifact_directory: Path,
    model_index: Path,
    lmstudio_token_file: Path,
) -> FastAPI:
    releases.release("worker_summary")
    manifest = releases.manifest
    if manifest is None:
        raise ValueError("verified release required")
    lmstudio_api_token = read_api_token(lmstudio_token_file)
    local = LocalModelBridge(api_token=lmstudio_api_token)
    try:
        local.require_authentication()
        binding = bind_loaded_model(artifact_directory, model_index, api_token=lmstudio_api_token)
    except BaseException:
        local.close()
        raise

    counter = binding.counter
    if (
        counter.artifact_digest != manifest.artifact_digest
        or counter.tokenizer_digest != manifest.tokenizer_digest
        or counter.template_digest != manifest.template_digest
        or counter.model_window != manifest.model_window
    ):
        binding.close()
        local.close()
        raise ValueError("loaded model does not match verified release")

    class GuardedModel:
        def complete(self, payload: Record, deadline: datetime) -> bytes:
            try:
                releases.release("worker_summary")
            except ManualError as error:
                raise OSError("current model release unavailable") from error
            try:
                local.require_authentication()
                pins = counter.loaded_current()
                result = local.complete(payload, deadline)
                if pins != counter.loaded_current():
                    raise OSError("model identity changed during generation")
                return result
            except (TokenizationDenied, lms.LMStudioError) as error:
                raise OSError("model identity unavailable") from error

    class GuardedCounter:
        def count(self, messages: Sequence[Mapping[str, str]]) -> TokenReceipt:
            try:
                releases.release("worker_summary")
            except ManualError as error:
                raise TokenizationDenied("current tokenizer release unavailable") from error
            try:
                local.require_authentication()
                return counter.count(messages)
            except lms.LMStudioError as error:
                raise TokenizationDenied("authenticated model session unavailable") from error

    app = create_app(GuardedModel(), verify, counter=GuardedCounter())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            try:
                binding.close()
            finally:
                local.close()

    app.router.lifespan_context = lifespan
    return app
