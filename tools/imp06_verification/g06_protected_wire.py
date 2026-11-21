"""Closed, synthetic-only frames for the private G-06 provider qualification relay."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import IO, cast

from care_link_inference_bridge.bridge import MODEL
from care_link_inference_bridge.tokenization import content_digest

TOKENIZE_PATH = "/internal/v1/inference/tokenize"
EXECUTE = "/internal/v1/inference/execute"
FRAME_LIMIT = 262144
MESSAGES = [
    {
        "role": "user",
        "content": 'Synthetic qualification. Return only the JSON object {"status":"READY"}.',
    }
]
PAYLOAD: dict[str, object] = {
    "model": MODEL,
    "messages": MESSAGES,
    "max_tokens": 32,
    "temperature": 0,
    "stream": False,
    "reasoning_effort": "none",
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "synthetic_mesh_qualification",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"status": {"type": "string", "enum": ["READY"]}},
                "required": ["status"],
                "additionalProperties": False,
            },
        },
    },
}

Record = dict[str, object]


def object_record(value: object) -> Record:
    if not isinstance(value, dict):
        raise ValueError("synthetic relay object required")
    return cast(Record, value)


def unique(pairs: list[tuple[str, object]]) -> Record:
    result: Record = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate relay field")
        result[key] = value
    return result


def read_frame(stream: IO[bytes]) -> Record:
    raw = stream.readline(FRAME_LIMIT + 1)
    if len(raw) > FRAME_LIMIT or not raw.endswith(b"\n"):
        raise ValueError("bounded complete relay frame required")
    return object_record(json.loads(raw, object_pairs_hook=unique))


def write_frame(stream: IO[bytes], frame: Record) -> None:
    raw = json.dumps(frame, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    if len(raw) > FRAME_LIMIT:
        raise ValueError("relay frame limit exceeded")
    stream.write(raw)
    stream.flush()


def tokenize_body(messages: Sequence[Mapping[str, str]]) -> Record:
    return {
        "messages": [dict(message) for message in messages],
        "content_digest": content_digest(messages),
    }


def checked_request(frame: Record, operation: str) -> Record:
    if set(frame) != {"operation", "body"} or frame["operation"] != operation:
        raise ValueError("exact synthetic relay route required")
    body = object_record(frame["body"])
    if operation == TOKENIZE_PATH:
        if body != tokenize_body(MESSAGES):
            raise ValueError("fixed synthetic tokenizer request required")
    elif operation == EXECUTE:
        deadline = body.get("deadline")
        if (
            set(body) != {"payload", "deadline"}
            or body["payload"] != PAYLOAD
            or not isinstance(deadline, str)
            or not deadline.endswith("Z")
            or not 0 < (datetime.fromisoformat(deadline) - datetime.now(UTC)).total_seconds() <= 30
        ):
            raise ValueError("fixed bounded synthetic generation required")
    else:
        raise ValueError("unknown relay route")
    return body
