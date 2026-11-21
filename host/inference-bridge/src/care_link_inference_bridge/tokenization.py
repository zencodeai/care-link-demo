"""Host-only tokenizer custody. No SDK client creation or model load lookup."""

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from .bridge import MODEL

DIGEST = re.compile(r"^[0-9a-f]{64}$")


class TokenizationDenied(ValueError):
    """Safe failure code with no prompt content."""


@dataclass(frozen=True)
class TokenReceipt:
    model_identifier: str
    loaded_model_id: str
    artifact_digest: str
    tokenizer_digest: str
    template_digest: str
    model_window: int
    input_tokens: int
    template_overhead: int
    content_digest: str


class TokenizerPort(Protocol):
    def count(self, messages: Sequence[Mapping[str, str]]) -> TokenReceipt: ...


def content_digest(messages: Sequence[Mapping[str, str]]) -> str:
    return hashlib.sha256(
        json.dumps(messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def closed_messages(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(cast(list[object], value)) <= 64:
        raise ValueError("bounded message list required")
    result: list[dict[str, str]] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            raise ValueError("closed text message required")
        message = cast(dict[str, object], item)
        if (
            set(message) != {"role", "content"}
            or message["role"] not in {"system", "user"}
            or not isinstance(message["content"], str)
            or len(message["content"]) > 24576
        ):
            raise ValueError("closed bounded text message required")
        result.append({"role": str(message["role"]), "content": message["content"]})
    return result


class LoadedLMStudioHandle(Protocol):
    def apply_prompt_template(self, chat: object) -> str: ...
    def tokenize(self, text: str) -> list[int]: ...
    def get_context_length(self) -> int: ...


class LMStudioTokenCounter:
    """Use an already externally verified SDK handle only in this host process."""

    def __init__(
        self,
        handle: LoadedLMStudioHandle,
        chat_from_history: Callable[[dict[str, object]], object],
        *,
        artifact_digest: str,
        tokenizer_digest: str,
        template_digest: str,
        model_window: int,
        loaded_current: Callable[[], dict[str, object]],
    ) -> None:
        self.handle, self.chat_from_history = handle, chat_from_history
        self.artifact_digest = artifact_digest
        self.tokenizer_digest, self.template_digest = tokenizer_digest, template_digest
        self.model_window, self.loaded_current = model_window, loaded_current

    def count(self, messages: Sequence[Mapping[str, str]]) -> TokenReceipt:
        pins = self.loaded_current()
        if (
            pins
            != {
                "model_identifier": MODEL,
                "loaded_model_id": MODEL,
                "artifact_digest": self.artifact_digest,
                "tokenizer_digest": self.tokenizer_digest,
                "template_digest": self.template_digest,
                "model_window": self.model_window,
            }
            or not DIGEST.fullmatch(self.artifact_digest)
            or not DIGEST.fullmatch(self.tokenizer_digest)
            or not DIGEST.fullmatch(self.template_digest)
            or type(self.model_window) is not int
            or self.model_window < 1
            or self.handle.get_context_length() != self.model_window
        ):
            raise TokenizationDenied("loaded_tokenizer_identity_changed")
        chat = self.chat_from_history({"messages": [dict(message) for message in messages]})
        rendered = self.handle.apply_prompt_template(chat)
        if len(rendered.encode()) > 1048576:
            raise TokenizationDenied("rendered_template_limit")
        tokens = self.handle.tokenize(rendered)
        if len(tokens) > 1000000 or any(type(token) is not int or token < 0 for token in tokens):
            raise TokenizationDenied("invalid_tokenizer_result")
        if self.loaded_current() != pins or self.handle.get_context_length() != self.model_window:
            raise TokenizationDenied("loaded_tokenizer_identity_changed")
        return TokenReceipt(
            MODEL,
            MODEL,
            self.artifact_digest,
            self.tokenizer_digest,
            self.template_digest,
            self.model_window,
            len(tokens),
            0,
            content_digest(messages),
        )
