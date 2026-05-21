from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


DEFAULT_ENV_FILE = Path("env/.env")


def _env_file_signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return (str(path), 0, 0)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _load_local_env_file(env_file: str | None = None) -> dict[str, str]:
    path = Path(env_file) if env_file is not None else DEFAULT_ENV_FILE
    return _load_local_env_file_cached(*_env_file_signature(path))


@lru_cache(maxsize=8)
def _load_local_env_file_cached(path_text: str, mtime_ns: int, size: int) -> dict[str, str]:
    path = Path(path_text)
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _get_setting(*keys: str, default: str = "") -> str:
    local_env = _load_local_env_file()
    for key in keys:
        value = os.getenv(key)
        if value not in (None, ""):
            return value
        if key in local_env and local_env[key] != "":
            return local_env[key]
    return default


@dataclass(slots=True)
class Settings:
    app_name: str = "SAP OData Agent"
    sap_base_url: str = field(default_factory=lambda: (_get_setting("SAP_ODATA_BASE_URL", "SAP_BASE_URL")).rstrip("/"))
    sap_username: str = field(default_factory=lambda: _get_setting("SAP_USERNAME"))
    sap_password: str = field(default_factory=lambda: _get_setting("SAP_PASSWORD"))
    sap_client: str = field(default_factory=lambda: _get_setting("SAP_CLIENT"))
    sap_verify_ssl: bool = field(default_factory=lambda: _get_setting("SAP_VERIFY_SSL", default="true").lower() == "true")
    sap_auth_type: str = field(default_factory=lambda: _get_setting("SAP_AUTH_TYPE", default="basic"))
    sap_timeout_ms: int = field(default_factory=lambda: int(_get_setting("SAP_ODATA_TIMEOUT_MS", default="30000")))
    case_store_path: str = field(default_factory=lambda: _get_setting("CASE_STORE_PATH", default="data/cases/cases.jsonl"))
    index_root: str = field(default_factory=lambda: _get_setting("LOCAL_INDEX_ROOT", default="data/index"))
    api_skill_root: str = field(default_factory=lambda: _get_setting("API_SKILL_ROOT", default="data/api_skills"))
    default_index_service: str = field(default_factory=lambda: _get_setting("DEFAULT_INDEX_SERVICE", default="API_BUSINESS_PARTNER"))
    max_attempts: int = field(default_factory=lambda: int(_get_setting("MAX_REPAIR_ATTEMPTS", default="3")))
    llm_planning_max_attempts: int = field(default_factory=lambda: int(_get_setting("LLM_PLANNING_MAX_ATTEMPTS", default="3")))
    retrieval_top_k: int = field(default_factory=lambda: int(_get_setting("RETRIEVAL_TOP_K", default="12")))
    llm_base_url: str = field(default_factory=lambda: _get_setting("MINIMAX_BASE_URL"))
    llm_model: str = field(default_factory=lambda: _get_setting("MINIMAX_MODEL"))
    llm_api_key: str = field(default_factory=lambda: _get_setting("MINIMAX_API_KEY"))
    llm_profiles_path: str = field(default_factory=lambda: _get_setting("LLM_PROFILES_PATH", default="env/llm_profiles.json"))
    llm_verify_ssl: bool = field(default_factory=lambda: _get_setting("LLM_VERIFY_SSL", default="true").lower() == "true")
    llm_timeout_ms: int = field(default_factory=lambda: int(_get_setting("LLM_TIMEOUT_MS", default="45000")))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model and self.llm_api_key)


def get_settings() -> Settings:
    return Settings()
