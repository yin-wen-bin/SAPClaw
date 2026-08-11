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


def _merge_csv_values(*values: str | None) -> str:
    merged: list[str] = []
    for value in values:
        for item in str(value or "").split(","):
            normalized = item.strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return ",".join(merged)


def _get_sap_proxy_bypass_hosts() -> str:
    local_env = _load_local_env_file()
    return _merge_csv_values(
        os.getenv("SAP_ODATA_NO_PROXY"),
        local_env.get("SAP_ODATA_NO_PROXY"),
        os.getenv("NO_PROXY"),
        os.getenv("no_proxy"),
        local_env.get("NO_PROXY"),
        local_env.get("no_proxy"),
    )


@dataclass(slots=True)
class Settings:
    app_name: str = "SAPClaw Runtime"
    sap_base_url: str = field(default_factory=lambda: (_get_setting("SAP_ODATA_BASE_URL", "SAP_BASE_URL")).rstrip("/"))
    sap_username: str = field(default_factory=lambda: _get_setting("SAP_USERNAME"))
    sap_password: str = field(default_factory=lambda: _get_setting("SAP_PASSWORD"))
    sap_client: str = field(default_factory=lambda: _get_setting("SAP_CLIENT"))
    sap_verify_ssl: bool = field(default_factory=lambda: _get_setting("SAP_VERIFY_SSL", default="true").lower() == "true")
    sap_auth_type: str = field(default_factory=lambda: _get_setting("SAP_AUTH_TYPE", default="basic"))
    sap_timeout_ms: int = field(default_factory=lambda: int(_get_setting("SAP_ODATA_TIMEOUT_MS", default="30000")))
    sap_proxy_bypass_hosts: str = field(default_factory=_get_sap_proxy_bypass_hosts)
    case_store_path: str = field(default_factory=lambda: _get_setting("CASE_STORE_PATH", default="data/cases/cases.jsonl"))
    index_root: str = field(default_factory=lambda: _get_setting("LOCAL_INDEX_ROOT", default="data/index"))
    api_skill_root: str = field(default_factory=lambda: _get_setting("API_SKILL_ROOT", default="data/api_skills"))
    local_kg_enabled: bool = field(default_factory=lambda: _get_setting("LOCAL_KG_ENABLED", default="true").lower() == "true")
    local_kg_root: str = field(default_factory=lambda: _get_setting("LOCAL_KG_ROOT", default="data/knowledge_graph"))
    local_kg_max_evidence: int = field(default_factory=lambda: int(_get_setting("LOCAL_KG_MAX_EVIDENCE", default="5")))
    default_index_service: str = field(default_factory=lambda: _get_setting("DEFAULT_INDEX_SERVICE", default="API_BUSINESS_PARTNER"))
    internal_api_keys: str = field(default_factory=lambda: _get_setting("SAPCLAW_API_KEYS"))
    runtime_page_size: int = field(default_factory=lambda: int(_get_setting("SAPCLAW_RUNTIME_PAGE_SIZE", default="50")))
    runtime_max_binding_rows: int = field(default_factory=lambda: int(_get_setting("SAPCLAW_RUNTIME_MAX_BINDING_ROWS", default="5000")))
    runtime_live_schema_enabled: bool = field(default_factory=lambda: _get_setting("SAPCLAW_RUNTIME_LIVE_SCHEMA_ENABLED", default="true").lower() == "true")
    runtime_live_schema_ttl_seconds: int = field(default_factory=lambda: int(_get_setting("SAPCLAW_RUNTIME_LIVE_SCHEMA_TTL_SECONDS", default="300")))
    runtime_live_schema_max_stale_seconds: int = field(default_factory=lambda: int(_get_setting("SAPCLAW_RUNTIME_LIVE_SCHEMA_MAX_STALE_SECONDS", default="86400")))
    runtime_viewer_enabled: bool = field(default_factory=lambda: _get_setting("SAPCLAW_RUNTIME_VIEWER_ENABLED", default="true").lower() == "true")
    runtime_viewer_base_url: str = field(default_factory=lambda: _get_setting("SAPCLAW_RUNTIME_VIEWER_BASE_URL", default="http://127.0.0.1:8000").rstrip("/"))

    @property
    def internal_api_key_values(self) -> list[str]:
        return [key.strip() for key in self.internal_api_keys.split(",") if key.strip()]


def get_settings() -> Settings:
    return Settings()
