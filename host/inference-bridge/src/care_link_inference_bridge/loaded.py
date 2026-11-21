"""Bind an existing SDK instance using pinned generated RPC types/vendor keys.

The remote_call method is public; its generated underscore-module types and
vendor configuration keys are a version-pinned integration seam, not a stable
high-level SDK guarantee. Never call get-or-load or .act().
"""

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import lmstudio as lms
from lmstudio._sdk_models import (
    ChatHistoryData,
    KvConfig,
    KvConfigField,
    KvConfigStack,
    KvConfigStackLayer,
    LlmApplyPromptTemplateOpts,
    LlmRpcApplyPromptTemplateParameter,
    ModelSpecifierInstanceReference,
    SystemPrompt,
    TextData,
    UserMessage,
)

from .artifacts import ArtifactPins, canonical, file_digest, pin_artifact
from .bridge import MODEL
from .tokenization import LMStudioTokenCounter, TokenizationDenied, closed_messages

RENDER_MODE = "sdk1.6.0b1-typed-applyPromptTemplate-instance-reference-nonthinking-v1"
THINKING_FIELDS = (
    "llm.prediction.reasoning.enableThinking",
    "ext.virtualModel.customField.qwen.qwen3.827b.enableThinking",
)


def alias_files(index: Path, directory: Path) -> tuple[Path, ...]:
    value = json.loads(index.read_text())
    matches = [item for item in value["models"] if item.get("indexedModelIdentifier") == MODEL]
    if len(matches) != 1 or Path(matches[0]["concreteModelDirAbsolutePath"]).resolve() != directory:
        raise TokenizationDenied("loaded_artifact_mapping_unverified")
    base = Path(matches[0]["containingDirAbsolutePath"]).resolve(strict=True)
    paths = (base / "model.yaml", base / "manifest.json")
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise TokenizationDenied("loaded_alias_definition_unverified")
    return paths


class _ExistingHandle:
    def __init__(self, handle: lms.LLM, client: lms.Client, instance: str) -> None:
        self.handle, self.client, self.instance = handle, client, instance

    def apply_prompt_template(self, chat: object) -> str:
        if not isinstance(chat, dict):
            raise TokenizationDenied("closed SDK history required")
        value = cast(dict[str, object], chat)
        if set(value) != {"messages"}:
            raise TokenizationDenied("closed SDK history required")
        messages = closed_messages(value["messages"])
        history = ChatHistoryData(
            messages=[
                (SystemPrompt if message["role"] == "system" else UserMessage)(
                    content=[TextData(text=message["content"])]
                )
                for message in messages
            ]
        )
        parameters = LlmRpcApplyPromptTemplateParameter(
            specifier=ModelSpecifierInstanceReference(instance_reference=self.instance),
            history=history,
            prediction_config_stack=KvConfigStack(
                layers=[
                    KvConfigStackLayer(
                        layer_name="httpServerRequestOverride",
                        config=KvConfig(
                            fields=[KvConfigField(key=key, value=False) for key in THINKING_FIELDS]
                        ),
                    )
                ]
            ),
            opts=LlmApplyPromptTemplateOpts(),
        )
        # Public remote_call with pinned generated types renders the actual template
        # with the same per-request nonthinking mode as REST reasoning_effort=none.
        # No model/preset/server setting is mutated.
        value = self.client.llm.remote_call("applyPromptTemplate", parameters)
        formatted = value.get("formatted")
        if not isinstance(formatted, str):
            raise TokenizationDenied("invalid_server_template_render")
        return formatted

    def tokenize(self, text: str) -> list[int]:
        tokens = self.handle.tokenize(text)
        if any(type(token) is not int or token < 0 for token in tokens):
            raise TokenizationDenied("invalid_tokenizer_result")
        return list(cast(Sequence[int], tokens))

    def get_context_length(self) -> int:
        return self.handle.get_context_length()


@dataclass(frozen=True)
class LoadedBinding:
    counter: LMStudioTokenCounter
    artifact: ArtifactPins
    model_info: dict[str, object]
    alias_digests: tuple[tuple[str, str], ...]
    client: lms.Client

    def close(self) -> None:
        self.client.close()


def bind_loaded_model(directory: Path, index: Path, *, api_token: str) -> LoadedBinding:
    """Authenticate a fixed loopback SDK connection to an already loaded model."""
    if not api_token or any(not "!" <= char <= "~" for char in api_token):
        raise TokenizationDenied("local_API_credential_required")

    if any(
        os.environ.get(key)
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        )
    ):
        # The SDK owns its HTTP/WebSocket clients and does not expose trust_env.
        # Reject proxy configuration rather than routing template text elsewhere.
        raise TokenizationDenied("SDK proxy environment forbidden")
    artifact = pin_artifact(directory)
    aliases = alias_files(index, artifact.directory)
    alias_digests = tuple((path.name, file_digest(path)) for path in aliases)
    template_digest = hashlib.sha256(
        canonical([artifact.template_digest, alias_digests, RENDER_MODE, THINKING_FIELDS])
    ).hexdigest()
    client = lms.Client("127.0.0.1:1234", api_token=api_token)
    try:
        models = [
            handle for handle in client.list_loaded_models("llm") if handle.identifier == MODEL
        ]
        if len(models) != 1 or not isinstance(models[0], lms.LLM):
            raise TokenizationDenied("exact_loaded_instance_required")
        handle = models[0]
        info = cast(dict[str, object], handle.get_info().to_dict())
        if (
            info.get("identifier") != MODEL
            or info.get("modelKey") != MODEL
            or info.get("path") != MODEL
            or info.get("format") != "safetensors"
            or info.get("contextLength") != 8192
            or not isinstance(info.get("instanceReference"), str)
            or not info["instanceReference"]
        ):
            raise TokenizationDenied("exact_loaded_instance_required")
        load_config = handle.get_load_config().to_dict()

        def current() -> dict[str, object]:
            if (
                not artifact.current()
                or alias_files(index, artifact.directory) != aliases
                or tuple((path.name, file_digest(path)) for path in aliases) != alias_digests
                or handle.get_info().to_dict() != info
                or handle.get_load_config().to_dict() != load_config
            ):
                raise TokenizationDenied("loaded_artifact_or_instance_changed")
            return {
                "model_identifier": MODEL,
                "loaded_model_id": MODEL,
                "artifact_digest": artifact.artifact_digest,
                "tokenizer_digest": artifact.tokenizer_digest,
                "template_digest": template_digest,
                "model_window": 8192,
            }

        counter = LMStudioTokenCounter(
            _ExistingHandle(handle, client, cast(str, info["instanceReference"])),
            lambda history: history,
            artifact_digest=artifact.artifact_digest,
            tokenizer_digest=artifact.tokenizer_digest,
            template_digest=template_digest,
            model_window=8192,
            loaded_current=current,
        )
        current()
        return LoadedBinding(counter, artifact, info, alias_digests, client)
    except BaseException:
        client.close()
        raise
