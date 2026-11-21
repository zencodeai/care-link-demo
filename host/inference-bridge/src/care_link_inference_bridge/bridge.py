"""Fixed loopback-only LM Studio adapter. No caller URLs, headers or tools."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast

import httpx

MODEL = "qwen/qwen3.8-27b"
ORIGIN = "http://127.0.0.1:1234"
ENDPOINT = ORIGIN + "/v1/chat/completions"
MAX_RESPONSE_BYTES = 65536


class LocalModelBridge:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        api_token: str | None = None,
    ) -> None:
        # trust_env=False prevents proxy environment variables from routing local
        # model traffic elsewhere; redirects are never followed.
        self.client = httpx.Client(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
        )
        self.clock = clock
        if api_token is not None and (not api_token or "\n" in api_token or "\r" in api_token):
            raise ValueError("invalid local API credential")
        self._headers = {"Content-Type": "application/json"}
        if api_token is not None:
            self._headers["Authorization"] = "Bearer " + api_token

    def require_authentication(self) -> None:
        """Probe discovery without sending context or relying on client headers."""
        if "Authorization" not in self._headers:
            raise OSError("local provider credential missing")
        try:
            public = self.client.get(
                ORIGIN + "/api/v1/models", headers={"Connection": "close"}, timeout=2
            )
            if public.status_code not in (401, 403):
                raise OSError("local provider authentication not enforced")
            authorized = self.client.get(
                ORIGIN + "/api/v1/models", headers=self._headers, timeout=2
            )
            if authorized.status_code != 200:
                raise OSError("local provider credential not accepted")
        except httpx.HTTPError as error:
            raise OSError("local provider authentication unavailable") from error

    def close(self) -> None:
        self.client.close()

    def complete(self, payload: dict[str, object], deadline: datetime) -> bytes:
        if (
            set(payload)
            != {
                "model",
                "messages",
                "temperature",
                "stream",
                "max_tokens",
                "response_format",
                "reasoning_effort",
            }
            or payload["model"] != MODEL
            or payload["temperature"] != 0
            or payload["stream"] is not False
            or payload["reasoning_effort"] != "none"
            or type(payload["max_tokens"]) is not int
            or not 1 <= payload["max_tokens"] <= 1024
        ):
            raise ValueError("fixed local inference payload required")
        messages = payload["messages"]
        if not isinstance(messages, list) or not 1 <= len(cast(list[object], messages)) <= 64:
            raise ValueError("bounded text messages required")
        for value in cast(list[object], messages):
            if not isinstance(value, dict):
                raise ValueError("closed text message required")
            message = cast(dict[str, object], value)
            if (
                set(message) != {"role", "content"}
                or message["role"] not in {"system", "user"}
                or not isinstance(message["content"], str)
                or len(message["content"]) > 24576
            ):
                raise ValueError("closed attributed text message required")
        remaining = (deadline - self.clock()).total_seconds()
        if not 0 < remaining <= 30:
            raise TimeoutError("absolute inference deadline expired")
        chunks: list[bytes] = []
        size = 0
        try:
            with self.client.stream(
                "POST",
                ENDPOINT,
                json=payload,
                headers=self._headers,
                timeout=remaining,
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    if self.clock() >= deadline:
                        raise TimeoutError("absolute inference deadline expired")
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        # Transport was interrupted, so compute completion is
                        # unverified; gateway keeps its slot occupied.
                        raise OSError("provider response limit exceeded")
                    chunks.append(chunk)
        except httpx.HTTPError as error:
            raise OSError("local provider did not establish completion") from error
        return b"".join(chunks)
