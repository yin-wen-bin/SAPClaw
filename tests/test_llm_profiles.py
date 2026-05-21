import json
from types import SimpleNamespace

import pytest

from sap_odata_agent.infrastructure.llm import profiles as profiles_module
from sap_odata_agent.infrastructure.llm.planner import (
    AnthropicCompatibleMessagesClient,
    OpenAiCompatibleChatClient,
)


def _clear_profile_caches():
    profiles_module.get_profile_registry.cache_clear()


def _profile_settings(path, **overrides):
    defaults = {
        "llm_profiles_path": str(path),
        "llm_model": "",
        "llm_base_url": "",
        "llm_timeout_ms": 45000,
        "llm_verify_ssl": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_default_profiles_include_supported_providers(monkeypatch, tmp_path):
    monkeypatch.setattr(
        profiles_module,
        "get_settings",
        lambda: _profile_settings(
            tmp_path / "missing.json",
            llm_base_url="https://minimax.example",
            llm_model="minimax-model",
        ),
    )
    monkeypatch.setattr(
        profiles_module,
        "_get_setting",
        lambda *keys, default="": {"MINIMAX_API_KEY": "minimax-key"}.get(keys[0], default),
    )
    _clear_profile_caches()

    payload = profiles_module.get_llm_profiles_payload()

    assert payload["default_profile"] == "minimax-default"
    assert [item["provider"] for item in payload["items"]] == [
        "minimax",
        "deepseek",
        "glm",
        "kimi",
        "openai",
        "anthropic",
    ]
    assert payload["items"][0]["enabled"] is True
    assert "api_key" not in payload["items"][0]


def test_profile_config_creates_openai_compatible_client(monkeypatch, tmp_path):
    config_path = tmp_path / "llm_profiles.json"
    config_path.write_text(
        json.dumps(
            {
                "default_profile": "deepseek-default",
                "profiles": [
                    {
                        "id": "deepseek-default",
                        "label": "DeepSeek",
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "base_url": "https://deepseek.example",
                        "api_key_env": "DEEPSEEK_API_KEY",
                        "protocol": "openai_chat",
                        "api_path": "/chat/completions",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(profiles_module, "get_settings", lambda: _profile_settings(config_path))
    monkeypatch.setattr(
        profiles_module,
        "_get_setting",
        lambda *keys, default="": {"DEEPSEEK_API_KEY": "deepseek-key"}.get(keys[0], default),
    )
    _clear_profile_caches()

    profile = profiles_module.get_llm_profile("deepseek-default")
    client = profiles_module.create_llm_client(profile)

    assert profile.enabled is True
    assert isinstance(client, OpenAiCompatibleChatClient)
    assert client.model == "deepseek-chat"
    assert client.api_path == "/chat/completions"


def test_profile_config_creates_anthropic_compatible_client(monkeypatch, tmp_path):
    config_path = tmp_path / "llm_profiles.json"
    config_path.write_text(
        json.dumps(
            {
                "default_profile": "anthropic-default",
                "profiles": [
                    {
                        "id": "anthropic-default",
                        "label": "Anthropic",
                        "provider": "anthropic",
                        "model": "claude-test",
                        "base_url": "https://anthropic.example",
                        "api_key_env": "ANTHROPIC_API_KEY",
                        "protocol": "anthropic_messages",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(profiles_module, "get_settings", lambda: _profile_settings(config_path))
    monkeypatch.setattr(
        profiles_module,
        "_get_setting",
        lambda *keys, default="": {"ANTHROPIC_API_KEY": "anthropic-key"}.get(keys[0], default),
    )
    _clear_profile_caches()

    profile = profiles_module.get_llm_profile("anthropic-default")
    client = profiles_module.create_llm_client(profile)

    assert profile.enabled is True
    assert isinstance(client, AnthropicCompatibleMessagesClient)
    assert client.model == "claude-test"
    assert client.api_path == "/v1/messages"


def test_default_kimi_profile_can_use_anthropic_messages(monkeypatch, tmp_path):
    monkeypatch.setattr(profiles_module, "get_settings", lambda: _profile_settings(tmp_path / "missing.json"))
    monkeypatch.setattr(
        profiles_module,
        "_get_setting",
        lambda *keys, default="": {
            "KIMI_API_KEY": "kimi-key",
            "KIMI_MODEL": "kimi-for-coding",
            "KIMI_BASE_URL": "https://api.kimi.com/coding/v1",
            "KIMI_PROTOCOL": "anthropic_messages",
            "KIMI_API_PATH": "/messages",
        }.get(keys[0], default),
    )
    _clear_profile_caches()

    profile = profiles_module.get_llm_profile("kimi-default")
    client = profiles_module.create_llm_client(profile)

    assert profile.enabled is True
    assert profile.protocol == "anthropic_messages"
    assert isinstance(client, AnthropicCompatibleMessagesClient)
    assert client.model == "kimi-for-coding"
    assert client.api_path == "/messages"


def test_unknown_profile_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(profiles_module, "get_settings", lambda: _profile_settings(tmp_path / "missing.json"))
    _clear_profile_caches()

    with pytest.raises(ValueError, match="Unknown LLM profile"):
        profiles_module.get_llm_profile("missing-profile")
