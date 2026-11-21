"""Only the bridge process may read the operator's provider credential."""

import pytest
from care_link_inference_bridge.credentials import read_api_token


def test_private_file_is_required_and_symlinks_are_rejected(tmp_path):
    secret = tmp_path / "credential"
    secret.write_text("synthetic-value\n")
    secret.chmod(0o644)
    with pytest.raises(ValueError, match="private host-owned"):
        read_api_token(secret)
    secret.chmod(0o600)
    assert read_api_token(secret) == "synthetic-value"
    pointer = tmp_path / "pointer"
    pointer.symlink_to(secret)
    with pytest.raises(OSError):
        read_api_token(pointer)
