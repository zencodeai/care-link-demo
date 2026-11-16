"""Stable redacted failures for the local demo operator interface."""


class DemoError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
