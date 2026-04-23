from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEFAULT_ENV_FILE = Path("env/.env")


@lru_cache(maxsize=1)
def _load_local_env_file(env_file: str = str(DEFAULT_ENV_FILE)) -> dict[str, str]:
    path = Path(env_file)
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
    sap_base_url: str = (_get_setting("SAP_ODATA_BASE_URL", "SAP_BASE_URL")).rstrip("/")
    sap_username: str = _get_setting("SAP_USERNAME")
    sap_password: str = _get_setting("SAP_PASSWORD")
    sap_client: str = _get_setting("SAP_CLIENT")
    sap_verify_ssl: bool = _get_setting("SAP_VERIFY_SSL", default="true").lower() == "true"
    sap_auth_type: str = _get_setting("SAP_AUTH_TYPE", default="basic")
    sap_timeout_ms: int = int(_get_setting("SAP_ODATA_TIMEOUT_MS", default="30000"))
    case_store_path: str = _get_setting("CASE_STORE_PATH", default="data/cases/cases.jsonl")
    index_root: str = _get_setting("LOCAL_INDEX_ROOT", default="data/index")
    default_index_service: str = _get_setting("DEFAULT_INDEX_SERVICE", default="API_BUSINESS_PARTNER")
    max_attempts: int = int(_get_setting("MAX_REPAIR_ATTEMPTS", default="3"))
    llm_planning_max_attempts: int = int(_get_setting("LLM_PLANNING_MAX_ATTEMPTS", default="3"))
    retrieval_top_k: int = int(_get_setting("RETRIEVAL_TOP_K", default="12"))
    llm_base_url: str = _get_setting("MINIMAX_BASE_URL")
    llm_model: str = _get_setting("MINIMAX_MODEL")
    llm_api_key: str = _get_setting("MINIMAX_API_KEY")
    llm_verify_ssl: bool = _get_setting("LLM_VERIFY_SSL", default="true").lower() == "true"
    llm_timeout_ms: int = int(_get_setting("LLM_TIMEOUT_MS", default="45000"))

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model and self.llm_api_key)


def get_settings() -> Settings:
    return Settings()
