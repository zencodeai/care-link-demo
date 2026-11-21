import json

import pytest
from care_link_inference_bridge.artifacts import pin_artifact


def artifact(tmp_path):
    for name, value in {
        "model.safetensors.index.json": json.dumps({"weight_map": {"tensor": "part.safetensors"}}),
        "part.safetensors": "synthetic weights",
        "tokenizer_config.json": "{}",
        "tokenizer.json": "{}",
        "config.json": "{}",
        "chat_template.jinja": "synthetic template",
    }.items():
        (tmp_path / name).write_text(value)
    return tmp_path


def test_all_weight_and_tokenizer_bytes_bound_and_mutations_revoke(tmp_path):
    directory = artifact(tmp_path)
    pins = pin_artifact(directory)
    assert len(pins.files) == 6 and pins.current()
    (directory / "part.safetensors").write_text("changed weights")
    assert not pins.current()
    assert pin_artifact(directory).artifact_digest != pins.artifact_digest


def test_shard_path_escape_is_rejected(tmp_path):
    directory = artifact(tmp_path)
    (directory / "model.safetensors.index.json").write_text(
        json.dumps({"weight_map": {"tensor": "../outside.safetensors"}})
    )
    with pytest.raises(ValueError, match="closed local"):
        pin_artifact(directory)


def test_symlink_artifacts_rejected(tmp_path):
    directory = artifact(tmp_path)
    (directory / "tokenizer.json").unlink()
    (directory / "tokenizer.json").symlink_to(directory / "config.json")
    with pytest.raises(ValueError, match="ordinary"):
        pin_artifact(directory)


def test_generation_configuration_and_tokenizer_vocabulary_bound(tmp_path):
    directory = artifact(tmp_path)
    original = pin_artifact(directory)
    (directory / "generation_config.json").write_text("{}")
    (directory / "vocab.json").write_text("{}")
    assert not original.current()

    expanded = pin_artifact(directory)
    assert expanded.artifact_digest != original.artifact_digest
    assert expanded.tokenizer_digest != original.tokenizer_digest
    (directory / "generation_config.json").write_text('{"new_value":0}')
    assert not expanded.current()
