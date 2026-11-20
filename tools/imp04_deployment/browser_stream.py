"""IMP-04-only generated stream routing; shared IMP-03 defaults stay intact."""

from copy import deepcopy
from pathlib import Path
from typing import cast

from .config import Record, record, write


def configure_browser_stream(config: Record) -> None:
    resources = record(config["static_resources"])
    listeners = cast(list[Record], resources["listeners"])
    browser = [item for item in listeners if item.get("name") == "browser_tls"]
    if len(browser) != 1:
        raise ValueError("Exactly one IMP-04 browser listener required")
    chains = cast(list[Record], browser[0]["filter_chains"])
    filters = cast(list[Record], chains[0]["filters"])
    connection = record(filters[0]["typed_config"])
    hosts = cast(list[Record], record(connection["route_config"])["virtual_hosts"])
    if len(hosts) != 1:
        raise ValueError("Exactly one IMP-04 browser virtual host required")
    routes = cast(list[Record], hosts[0]["routes"])
    if len(routes) != 1 or routes[0].get("match") != {"prefix": "/"}:
        raise ValueError("Fresh browser fallback required; stream must not be configured twice")
    fallback = routes[0]
    if record(fallback["route"]) != {"cluster": "application", "timeout": "45s"}:
        raise ValueError("Unchanged bounded application fallback required")
    if not fallback.get("request_headers_to_remove"):
        raise ValueError("Browser protected-header stripping required")
    stream = deepcopy(fallback)
    stream["match"] = {
        "path": "/v1/review/events",
        "headers": [{"name": ":method", "string_match": {"exact": "GET"}}],
    }
    record(stream["route"])["timeout"] = "0s"
    # Copy the complete fallback, including protected-header removal. Authority
    # still revalidates throughout the stream; transport resource bounds remain.
    hosts[0]["routes"] = [stream, fallback]


def configure_rendered_browser_stream(path: Path) -> None:
    import json

    if path.is_symlink() or not path.is_file():
        raise ValueError("Fresh regular generated browser configuration required")
    config = record(json.loads(path.read_text()))
    configure_browser_stream(config)
    replacement = path.with_suffix(".stream.json")
    write(replacement, json.dumps(config, indent=2) + "\n")
    replacement.replace(path)
