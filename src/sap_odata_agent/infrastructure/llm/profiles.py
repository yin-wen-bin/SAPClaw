from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from sap_odata_agent.infrastructure.config.settings import _get_setting, get_settings
from sap_odata_agent.infrastructure.llm.planner import (
    AnthropicCompatibleMessagesClient,
    OpenAiCompatibleChatClient,
)


SUPPORTED_PROTOCOLS = {"anthropic_messages", "openai_chat"}


@dataclass(frozen=True, slots=True)
class LlmProfile:
    id: str
    label: str
    provider: str
    model: str
    base_url: str
    api_key_env: str
    protocol: str
    api_path: str
    timeout_ms: int
    verify_ssl: bool = True

    @property
    def api_key(self) -> str:
        return _get_setting(self.api_key_env) if self.api_key_env else ""

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def public_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "model": self.model,
            "protocol": self.protocol,
            "enabled": self.enabled,
        }


@dataclass(frozen=True, slots=True)
class LlmProfileRegistry:
    default_profile: str
    profiles: tuple[LlmProfile, ...]

    def get(self, profile_id: str | None = None) -> LlmProfile:
        resolved_id = profile_id or self.default_profile
        for profile in self.profiles:
            if profile.id == resolved_id:
                return profile
        raise ValueError(f"Unknown LLM profile: {resolved_id}")

    def public_payload(self) -> dict[str, Any]:
        return {
            "default_profile": self.default_profile,
            "items": [profile.public_payload() for profile in self.profiles],
        }


def create_llm_client(profile: LlmProfile):
    if not profile.enabled:
        return None
    if profile.protocol == "anthropic_messages":
        return AnthropicCompatibleMessagesClient(
            base_url=profile.base_url,
            api_key=profile.api_key,
            model=profile.model,
            timeout_seconds=max(1, profile.timeout_ms // 1000),
            verify_ssl=profile.verify_ssl,
            api_path=profile.api_path,
        )
    if profile.protocol == "openai_chat":
        return OpenAiCompatibleChatClient(
            base_url=profile.base_url,
            api_key=profile.api_key,
            model=profile.model,
            timeout_seconds=max(1, profile.timeout_ms // 1000),
            verify_ssl=profile.verify_ssl,
            api_path=profile.api_path,
        )
    raise ValueError(f"Unsupported LLM profile protocol: {profile.protocol}")


@lru_cache(maxsize=1)
def get_profile_registry() -> LlmProfileRegistry:
    settings = get_settings()
    config_path = Path(settings.llm_profiles_path)
    if config_path.exists():
        return _registry_from_file(config_path)
    return _default_registry(settings)


def get_llm_profile(profile_id: str | None = None) -> LlmProfile:
    return get_profile_registry().get(profile_id)


def get_llm_profiles_payload() -> dict[str, Any]:
    return get_profile_registry().public_payload()


def describe_llm_profile(profile_id: str | None) -> dict[str, Any] | None:
    if not profile_id:
        return None
    try:
        return get_llm_profile(profile_id).public_payload()
    except ValueError:
        return {
            "id": profile_id,
            "label": profile_id,
            "provider": "unknown",
            "model": "",
            "protocol": "",
            "enabled": False,
        }


def _registry_from_file(path: Path) -> LlmProfileRegistry:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw_profiles = raw.get("profiles", [])
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError(f"LLM profile config contains no profiles: {path}")

    settings = get_settings()
    profiles = tuple(_profile_from_config(item, settings) for item in raw_profiles)
    _validate_profiles(profiles)
    default_profile = str(raw.get("default_profile") or profiles[0].id)
    if default_profile not in {profile.id for profile in profiles}:
        raise ValueError(f"Default LLM profile is not defined: {default_profile}")
    return LlmProfileRegistry(default_profile=default_profile, profiles=profiles)


def _default_registry(settings) -> LlmProfileRegistry:
    profiles = (
        LlmProfile(
            id="minimax-default",
            label="MiniMax",
            provider="minimax",
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            api_key_env="MINIMAX_API_KEY",
            protocol="anthropic_messages",
            api_path="/v1/messages",
            timeout_ms=settings.llm_timeout_ms,
            verify_ssl=settings.llm_verify_ssl,
        ),
        LlmProfile(
            id="deepseek-default",
            label="DeepSeek",
            provider="deepseek",
            model=_get_setting("DEEPSEEK_MODEL"),
            base_url=_get_setting("DEEPSEEK_BASE_URL", default="https://api.deepseek.com"),
            api_key_env="DEEPSEEK_API_KEY",
            protocol="openai_chat",
            api_path=_get_setting("DEEPSEEK_API_PATH", default="/chat/completions"),
            timeout_ms=settings.llm_timeout_ms,
            verify_ssl=settings.llm_verify_ssl,
        ),
        LlmProfile(
            id="glm-default",
            label="GLM",
            provider="glm",
            model=_get_setting("GLM_MODEL"),
            base_url=_get_setting("GLM_BASE_URL", default="https://open.bigmodel.cn/api/paas/v4"),
            api_key_env="GLM_API_KEY",
            protocol="openai_chat",
            api_path=_get_setting("GLM_API_PATH", default="/chat/completions"),
            timeout_ms=settings.llm_timeout_ms,
            verify_ssl=settings.llm_verify_ssl,
        ),
        LlmProfile(
            id="kimi-default",
            label="KIMI",
            provider="kimi",
            model=_get_setting("KIMI_MODEL"),
            base_url=_get_setting("KIMI_BASE_URL", default="https://api.moonshot.cn/v1"),
            api_key_env="KIMI_API_KEY",
            protocol="openai_chat",
            api_path=_get_setting("KIMI_API_PATH", default="/chat/completions"),
            timeout_ms=settings.llm_timeout_ms,
            verify_ssl=settings.llm_verify_ssl,
        ),
        LlmProfile(
            id="openai-default",
            label="OpenAI",
            provider="openai",
            model=_get_setting("OPENAI_MODEL"),
            base_url=_get_setting("OPENAI_BASE_URL", default="https://api.openai.com"),
            api_key_env="OPENAI_API_KEY",
            protocol="openai_chat",
            api_path=_get_setting("OPENAI_API_PATH", default="/v1/chat/completions"),
            timeout_ms=settings.llm_timeout_ms,
            verify_ssl=settings.llm_verify_ssl,
        ),
        LlmProfile(
            id="anthropic-default",
            label="Anthropic",
            provider="anthropic",
            model=_get_setting("ANTHROPIC_MODEL"),
            base_url=_get_setting("ANTHROPIC_BASE_URL", default="https://api.anthropic.com"),
            api_key_env="ANTHROPIC_API_KEY",
            protocol="anthropic_messages",
            api_path=_get_setting("ANTHROPIC_API_PATH", default="/v1/messages"),
            timeout_ms=settings.llm_timeout_ms,
            verify_ssl=settings.llm_verify_ssl,
        ),
    )
    return LlmProfileRegistry(default_profile=profiles[0].id, profiles=profiles)


def _profile_from_config(raw: dict[str, Any], settings) -> LlmProfile:
    profile_id = str(raw.get("id") or "").strip()
    if not profile_id:
        raise ValueError("LLM profile id is required.")
    protocol = str(raw.get("protocol") or "openai_chat").strip()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"Unsupported LLM profile protocol: {protocol}")
    return LlmProfile(
        id=profile_id,
        label=str(raw.get("label") or profile_id).strip(),
        provider=str(raw.get("provider") or profile_id).strip(),
        model=_resolve_config_value(raw, "model"),
        base_url=_resolve_config_value(raw, "base_url").rstrip("/"),
        api_key_env=str(raw.get("api_key_env") or "").strip(),
        protocol=protocol,
        api_path=str(raw.get("api_path") or _default_api_path(protocol)).strip(),
        timeout_ms=int(raw.get("timeout_ms") or settings.llm_timeout_ms),
        verify_ssl=bool(raw.get("verify_ssl", settings.llm_verify_ssl)),
    )


def _resolve_config_value(raw: dict[str, Any], key: str) -> str:
    env_key = str(raw.get(f"{key}_env") or "").strip()
    if env_key:
        return _get_setting(env_key)
    return str(raw.get(key) or "").strip()


def _default_api_path(protocol: str) -> str:
    return "/v1/messages" if protocol == "anthropic_messages" else "/v1/chat/completions"


def _validate_profiles(profiles: tuple[LlmProfile, ...]) -> None:
    seen: set[str] = set()
    for profile in profiles:
        if profile.id in seen:
            raise ValueError(f"Duplicate LLM profile id: {profile.id}")
        seen.add(profile.id)
