"""Tests for LLM config loading, provider resolution, fallback, and env overrides."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from src.llm_config import (
    LLMConfig, ProviderConfig, RoleConfig, LLMClient,
    _load_from_yaml, _load_from_env, _apply_env_overrides,
    load_config, get_client, _config,
)
import src.llm_config as llm_config_module


@pytest.fixture(autouse=True)
def reset_config():
    """Reset cached config between tests."""
    llm_config_module._config = None
    yield
    llm_config_module._config = None


@pytest.fixture
def sample_yaml(tmp_path):
    config = {
        "default_provider": "anthropic",
        "default_model": "claude-sonnet-4-20250514",
        "providers": {
            "anthropic": {
                "type": "anthropic",
                "api_key": "sk-test-key",
                "default_model": "claude-sonnet-4-20250514",
            },
            "local": {
                "type": "openai_compatible",
                "api_key": "",
                "base_url": "http://localhost:11434/v1",
                "default_model": "llama3:8b",
            },
        },
        "roles": {
            "skill_extraction": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "fallback": ["local"],
            },
            "workspace_chat": {
                "provider": "anthropic",
            },
        },
    }
    path = tmp_path / "llm.yaml"
    path.write_text(yaml.dump(config))
    return path


def test_load_from_yaml(sample_yaml):
    config = _load_from_yaml(sample_yaml)
    assert "anthropic" in config.providers
    assert "local" in config.providers
    assert config.providers["anthropic"].type == "anthropic"
    assert config.providers["anthropic"].api_key == "sk-test-key"
    assert config.default_provider == "anthropic"


def test_load_from_yaml_env_var_ref(tmp_path):
    config_data = {
        "default_provider": "anthropic",
        "providers": {
            "anthropic": {
                "type": "anthropic",
                "api_key": "${TEST_LLM_KEY}",
                "default_model": "claude-sonnet-4-20250514",
            },
        },
        "roles": {},
    }
    path = tmp_path / "llm.yaml"
    path.write_text(yaml.dump(config_data))

    with patch.dict(os.environ, {"TEST_LLM_KEY": "resolved-key"}):
        config = _load_from_yaml(path)
    assert config.providers["anthropic"].api_key == "resolved-key"


def test_load_from_env():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key", "ANTHROPIC_MODEL": "claude-haiku"}):
        config = _load_from_env()
    assert config.providers["anthropic"].api_key == "env-key"
    assert config.default_model == "claude-haiku"


def test_load_from_env_no_key():
    with patch.dict(os.environ, {}, clear=True):
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            config = _load_from_env()
    assert len(config.providers) == 0


def test_env_overrides():
    config = LLMConfig(
        default_provider="anthropic",
        default_model="old-model",
        providers={"anthropic": ProviderConfig(name="anthropic", type="anthropic", api_key="k")},
        roles={},
    )
    with patch.dict(os.environ, {
        "SR_LLM_DEFAULT_MODEL": "new-model",
        "SR_LLM_SKILL_EXTRACTION_MODEL": "special-model",
    }):
        _apply_env_overrides(config)
    assert config.default_model == "new-model"
    assert config.roles["skill_extraction"].model == "special-model"


def test_role_mapping(sample_yaml):
    config = _load_from_yaml(sample_yaml)
    assert config.roles["skill_extraction"].provider == "anthropic"
    assert config.roles["skill_extraction"].fallback == ["local"]


def test_get_client_with_config(sample_yaml):
    with patch.object(llm_config_module, "_find_config_path", return_value=sample_yaml):
        client = get_client("skill_extraction")
    assert client.provider.name == "anthropic"
    assert client.model == "claude-sonnet-4-20250514"


def test_get_client_backward_compat():
    """With no yaml, env vars should work."""
    with patch.object(llm_config_module, "_find_config_path", return_value=None):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "bc-key", "ANTHROPIC_MODEL": "claude-haiku"}):
            client = get_client("skill_extraction")
    assert client.provider.name == "anthropic"
    assert client.model == "claude-haiku"


def test_get_client_no_config_raises():
    with patch.object(llm_config_module, "_find_config_path", return_value=None):
        with patch.dict(os.environ, {}, clear=True):
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("ANTHROPIC_MODEL", None)
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(ValueError, match="No LLM provider configured"):
                    get_client("skill_extraction")


def test_fallback_chain(sample_yaml):
    """If primary fails, fallback should be tried."""
    with patch.object(llm_config_module, "_find_config_path", return_value=sample_yaml):
        client = get_client("skill_extraction")

    # Mock the underlying complete to fail for anthropic, succeed for local
    call_count = {"n": 0}
    original_complete = LLMClient.complete

    def mock_complete(self, messages, max_tokens=4096, system=None):
        call_count["n"] += 1
        if self.provider.name == "anthropic":
            raise ConnectionError("API down")
        return "fallback result"

    with patch.object(LLMClient, "complete", mock_complete):
        result = client.complete(messages=[{"role": "user", "content": "test"}])
    assert result == "fallback result"
    assert call_count["n"] == 2


def test_anthropic_client_complete():
    """Test Anthropic backend calls the library correctly."""
    provider = ProviderConfig(name="anthropic", type="anthropic", api_key="test-key")
    client = LLMClient(provider=provider, model="claude-test")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="hello world")]

    with patch("anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_response
        result = client.complete(
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=100,
            system="be helpful",
        )
    assert result == "hello world"
    MockAnthropic.assert_called_once_with(api_key="test-key")


def test_openai_client_complete():
    """Test OpenAI-compatible backend calls httpx correctly."""
    provider = ProviderConfig(
        name="local", type="openai_compatible",
        api_key="", base_url="http://localhost:11434/v1",
    )
    client = LLMClient(provider=provider, model="llama3:8b")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "ollama response"}}]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        result = client.complete(
            messages=[{"role": "user", "content": "hi"}],
            system="be helpful",
        )
    assert result == "ollama response"
    # Should call /v1/chat/completions (not /v1/v1/...)
    call_url = mock_post.call_args[0][0]
    assert call_url == "http://localhost:11434/v1/chat/completions"
