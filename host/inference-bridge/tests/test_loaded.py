"""SDK boundary doubles: binding never loads an absent or substituted model."""

import json

import pytest
from care_link_inference_bridge import MODEL, TokenizationDenied
from care_link_inference_bridge.loaded import bind_loaded_model

TEST_CREDENTIAL = "test-credential"  # noqa: S105 - mock client only


def setup(tmp_path, monkeypatch, *, loaded=True):
    from care_link_inference_bridge import loaded as module

    artifact = tmp_path / "artifact"
    artifact.mkdir()
    for name, text in {
        "part.safetensors": "synthetic weights",
        "model.safetensors.index.json": json.dumps({"weight_map": {"tensor": "part.safetensors"}}),
        "config.json": "{}",
        "tokenizer.json": "{}",
        "tokenizer_config.json": "{}",
        "chat_template.jinja": "synthetic template",
    }.items():
        (artifact / name).write_text(text)
    alias = tmp_path / "alias"
    alias.mkdir()
    (alias / "model.yaml").write_text("synthetic alias definition")
    (alias / "manifest.json").write_text("{}")
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "indexedModelIdentifier": MODEL,
                        "concreteModelDirAbsolutePath": str(artifact),
                        "containingDirAbsolutePath": str(alias),
                    }
                ]
            }
        )
    )
    info = {
        "identifier": MODEL,
        "modelKey": MODEL,
        "path": MODEL,
        "format": "safetensors",
        "contextLength": 8192,
        "instanceReference": "instance-1",
    }

    class Info:
        def __init__(self, value):
            self.value = value

        def to_dict(self):
            return dict(self.value)

    class Handle:
        identifier = MODEL

        def get_info(self):
            return Info(info)

        def get_load_config(self):
            return Info({"contextLength": 8192})

        def get_context_length(self):
            return 8192

        def apply_prompt_template(self, chat):
            return "synthetic rendered template"

        def tokenize(self, text):
            return [1, 2, 3]

    class Client:
        closed = False

        def __init__(self, host, *, api_token):
            assert (host, api_token) == ("127.0.0.1:1234", TEST_CREDENTIAL)

        def list_loaded_models(self, namespace):
            assert namespace == "llm"
            return [Handle()] if loaded else []

        @property
        def llm(self):
            return self

        def remote_call(self, endpoint, params):
            assert endpoint == "applyPromptTemplate"
            assert params.specifier.instance_reference == "instance-1"
            fields = params.prediction_config_stack.layers[0].config.fields
            assert len(fields) == 2 and all(field.value is False for field in fields)
            return {"formatted": "synthetic rendered template"}

        def close(self):
            self.closed = True

    monkeypatch.setattr(module.lms, "LLM", Handle)
    monkeypatch.setattr(module.lms, "Client", Client)
    return artifact, index, alias, info


def test_already_loaded_handle_matches_artifacts_and_rejects_instance_replacement(
    tmp_path, monkeypatch
):
    directory, index, _, info = setup(tmp_path, monkeypatch)
    binding = bind_loaded_model(directory, index, api_token=TEST_CREDENTIAL)
    proof = binding.counter.count([{"role": "user", "content": "Fictional source"}])
    assert proof.input_tokens == 3 and proof.model_identifier == MODEL
    info["instanceReference"] = "replacement"
    with pytest.raises(TokenizationDenied, match="instance_changed"):
        binding.counter.count([{"role": "user", "content": "Fictional source"}])
    binding.close()


def test_absent_model_denied_without_get_or_load(tmp_path, monkeypatch):
    directory, index, _, _ = setup(tmp_path, monkeypatch, loaded=False)
    with pytest.raises(TokenizationDenied, match="exact_loaded_instance"):
        bind_loaded_model(directory, index, api_token=TEST_CREDENTIAL)


def test_virtual_template_change_invalidates_counter(tmp_path, monkeypatch):
    directory, index, alias, _ = setup(tmp_path, monkeypatch)
    binding = bind_loaded_model(directory, index, api_token=TEST_CREDENTIAL)
    (alias / "model.yaml").write_text("changed thinking controls")
    with pytest.raises(TokenizationDenied, match="instance_changed"):
        binding.counter.count([{"role": "user", "content": "Fictional source"}])
    binding.close()


def test_sdk_proxy_environment_denied_before_any_client_or_artifact_access(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "https://proxy.invalid")
    with pytest.raises(TokenizationDenied, match="proxy"):
        bind_loaded_model(tmp_path / "absent", tmp_path / "absent-index", api_token=TEST_CREDENTIAL)


@pytest.mark.parametrize("token", ["", "has space", "newline\nvalue"])
def test_missing_or_invalid_credentials_fail_before_model_access(tmp_path, token):
    with pytest.raises(TokenizationDenied, match="credential_required"):
        bind_loaded_model(tmp_path / "absent", tmp_path / "absent-index", api_token=token)
