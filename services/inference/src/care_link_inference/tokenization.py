"""Inference reaches tokenizer custody only through the authenticated host bridge."""

import json
import ssl
from collections.abc import Mapping, Sequence
from typing import cast

import httpx

from .admission import MODEL, InferenceDenied, ModelManifest
from .context import TokenProof, content_digest

BRIDGE_COUNT_ENDPOINT = "https://host-inference-bridge:8443/internal/v1/inference/tokenize"


class HttpTokenCounter:
    def __init__(
        self,
        tls: ssl.SSLContext,
        manifest: ModelManifest,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if tls.verify_mode != ssl.CERT_REQUIRED or not tls.check_hostname:
            raise ValueError("authenticated tokenizer bridge TLS required")
        self.manifest = manifest
        self.client = httpx.Client(
            verify=tls, transport=transport, trust_env=False, follow_redirects=False
        )

    def count(self, messages: Sequence[Mapping[str, str]]) -> TokenProof:
        digest = content_digest(messages)
        try:
            with self.client.stream(
                "POST",
                BRIDGE_COUNT_ENDPOINT,
                json={
                    "messages": [dict(message) for message in messages],
                    "content_digest": digest,
                },
                timeout=10,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_bytes():
                    if len(raw) + len(chunk) > 4096:
                        raise ValueError("bounded tokenizer receipt required")
                    raw.extend(chunk)

            def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
                value: dict[str, object] = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError("duplicate tokenizer receipt key")
                    value[key] = item
                return value

            value = cast(dict[str, object], json.loads(raw, object_pairs_hook=unique))
            if (
                set(value)
                != {
                    "model_identifier",
                    "loaded_model_id",
                    "artifact_digest",
                    "tokenizer_digest",
                    "template_digest",
                    "model_window",
                    "input_tokens",
                    "template_overhead",
                    "content_digest",
                }
                or value["model_identifier"] != MODEL
                or value["loaded_model_id"] != self.manifest.loaded_model_id
                or value["artifact_digest"] != self.manifest.artifact_digest
                or value["tokenizer_digest"] != self.manifest.tokenizer_digest
                or value["template_digest"] != self.manifest.template_digest
                or value["model_window"] != self.manifest.model_window
                or value["content_digest"] != digest
                or type(value["input_tokens"]) is not int
                or not 0 <= value["input_tokens"] <= 1000000
                or type(value["template_overhead"]) is not int
                or not 0 <= value["template_overhead"] <= 1000000
            ):
                raise ValueError("tokenizer bridge identity/binding mismatch")
            return TokenProof(
                value["input_tokens"],
                value["template_overhead"],
                self.manifest.tokenizer_digest,
                self.manifest.template_digest,
                digest,
            )
        except (httpx.HTTPError, ValueError, TypeError, KeyError, RecursionError) as error:
            raise InferenceDenied("tokenizer_bridge_unavailable_or_unverified") from error

    def close(self) -> None:
        self.client.close()
