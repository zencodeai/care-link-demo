from tools.generate_contracts import TARGETS, render


def test_generated_contracts_preserve_reviewed_definitions():
    expected = render()
    for target in TARGETS:
        assert target.read_text() == expected, "Snapshot changed; reconcile source and regenerate"
