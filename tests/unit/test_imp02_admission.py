import json
from copy import deepcopy

import pytest

from tools.check_imp02_admission import CONFIG, validate


@pytest.mark.unit
def test_unverified_flags_cannot_activate_private_admission():
    baseline = json.loads(CONFIG.read_text())
    assert validate(baseline) == []
    for field in ("participant_admission", "police_integration", "autonomous_emergency_contact"):
        candidate = deepcopy(baseline)
        candidate[field] = True
        assert validate(candidate)
    baseline["help"]["fresh_authority_each_operation"] = False
    assert validate(baseline)
