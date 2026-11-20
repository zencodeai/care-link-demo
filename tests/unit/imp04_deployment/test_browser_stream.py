"""Fresh IMP-04 rendering retains every browser boundary around the SSE exception."""

from copy import deepcopy
from pathlib import Path

import pytest

from tools.imp03_runtime.mesh import render
from tools.imp04_deployment.browser_stream import (
    configure_browser_stream,
    configure_rendered_browser_stream,
)
from tools.imp04_deployment.prepare import make_binding, provider_state


def test_fresh_render_adds_only_get_stream_with_full_header_stripping(tmp_path: Path) -> None:
    import json

    binding = make_binding(provider_state(), {"identity": "a" * 40, "data": "b" * 40})
    directory = tmp_path / "rendered"
    render(binding, directory)
    path = directory / "core-envoy.json"
    before = json.loads(path.read_text())
    configure_rendered_browser_stream(path)
    after = json.loads(path.read_text())
    browser = next(x for x in after["static_resources"]["listeners"] if x["name"] == "browser_tls")
    connection = browser["filter_chains"][0]["filters"][0]["typed_config"]
    host = connection["route_config"]["virtual_hosts"][0]
    stream, fallback = host["routes"]
    assert stream["match"] == {
        "path": "/v1/review/events",
        "headers": [{"name": ":method", "string_match": {"exact": "GET"}}],
    }
    assert stream["route"] == {"cluster": "application", "timeout": "0s"}
    assert stream["request_headers_to_remove"] == fallback["request_headers_to_remove"]
    assert stream["request_headers_to_remove"]
    assert fallback["route"]["timeout"] == "45s"
    assert connection["request_timeout"] == "45s"
    host["routes"].pop(0)
    assert after == before
    # The shared renderer continues to emit its original, bounded IMP-03 route.
    shared = deepcopy(before)
    configure_browser_stream(shared)
    with pytest.raises(ValueError, match="Fresh browser fallback"):
        configure_browser_stream(shared)


def test_missing_browser_listener_rejected() -> None:
    with pytest.raises(ValueError, match="Exactly one"):
        configure_browser_stream({"static_resources": {"listeners": []}})
