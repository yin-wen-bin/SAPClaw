from sap_odata_agent.infrastructure.config import settings as settings_module
from sap_odata_agent.infrastructure.llm import profiles as profiles_module


def test_settings_reads_env_file_at_instance_time(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MINIMAX_BASE_URL=https://minimax.example\n"
        "MINIMAX_MODEL=old-model\n"
        "MINIMAX_API_KEY=key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.delenv("MINIMAX_MODEL", raising=False)
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    assert settings_module.Settings().llm_model == "old-model"

    env_file.write_text(
        "MINIMAX_BASE_URL=https://minimax.example\n"
        "MINIMAX_MODEL=new-minimax-model\n"
        "MINIMAX_API_KEY=key\n",
        encoding="utf-8",
    )

    assert settings_module.Settings().llm_model == "new-minimax-model"


def test_profile_registry_reloads_after_env_file_changes(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MINIMAX_BASE_URL=https://minimax.example\n"
        "MINIMAX_MODEL=old-model\n"
        "MINIMAX_API_KEY=key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.setattr(profiles_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.delenv("MINIMAX_MODEL", raising=False)
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    profiles_module.get_profile_registry.cache_clear()

    assert profiles_module.get_llm_profile("minimax-default").model == "old-model"

    env_file.write_text(
        "MINIMAX_BASE_URL=https://minimax.example\n"
        "MINIMAX_MODEL=new-minimax-model\n"
        "MINIMAX_API_KEY=key\n",
        encoding="utf-8",
    )

    profile = profiles_module.get_llm_profile("minimax-default")

    assert profile.model == "new-minimax-model"
    assert profile.enabled is True
