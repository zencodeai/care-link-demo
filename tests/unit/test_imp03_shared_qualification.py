"""Failure paths must restore reversible faults and never invent fence receipts."""

import json
from pathlib import Path

import pytest

from tools.imp03_shared import qualification


@pytest.mark.parametrize("phase", ["pdp-loss", "fenced"])
def test_lost_fault_reply_is_restored_or_recorded_unknown(tmp_path, monkeypatch, phase):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    monkeypatch.setattr(qualification, "EVIDENCE", evidence)
    monkeypatch.setattr(qualification, "snapshot", lambda: {})
    calls = []

    def fail_reply(actual, *, pause):
        calls.append((actual, pause))
        if pause:
            raise RuntimeError("lost fault reply")

    monkeypatch.setattr(qualification, "fault", fail_reply)

    class Browser:
        def __init__(self, _argv, *, env, **_kwargs):
            output = Path(env["CARE_LINK_IMP03_E2E_OUTPUT"])
            (output / "barrier-ready.json").touch(mode=0o600)

        def poll(self):
            return 0

    monkeypatch.setattr(qualification.subprocess, "Popen", Browser)
    with pytest.raises(RuntimeError, match="lost fault reply"):
        qualification.run(phase, 1, tmp_path)
    result = json.loads((evidence / f"option-b-live-{phase}-001.json").read_text())
    if phase == "fenced":
        assert calls == [(phase, True)]
        assert result["one_way_restriction_retained"] is False
        assert result["restriction_state_unknown"] is True
    else:
        assert calls == [(phase, True), (phase, False)]
        assert result["exact_barrier_restored"] is True
