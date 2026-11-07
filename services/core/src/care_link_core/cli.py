"""Explicit loopback developer startup; never starts during import."""

import uvicorn


def main() -> None:
    uvicorn.run("care_link_core.app:create_app", factory=True, host="127.0.0.1", port=8011)
