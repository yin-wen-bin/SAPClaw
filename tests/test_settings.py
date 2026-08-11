from sap_odata_agent.infrastructure.config import settings as settings_module


def test_settings_reads_env_file_at_instance_time(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SAP_ODATA_BASE_URL=https://sap-old.example\n"
        "SAPCLAW_RUNTIME_PAGE_SIZE=25\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.delenv("SAP_ODATA_BASE_URL", raising=False)
    monkeypatch.delenv("SAPCLAW_RUNTIME_PAGE_SIZE", raising=False)

    first = settings_module.Settings()
    assert first.sap_base_url == "https://sap-old.example"
    assert first.runtime_page_size == 25

    env_file.write_text(
        "SAP_ODATA_BASE_URL=https://sap-new.example\n"
        "SAPCLAW_RUNTIME_PAGE_SIZE=75\n",
        encoding="utf-8",
    )

    second = settings_module.Settings()
    assert second.sap_base_url == "https://sap-new.example"
    assert second.runtime_page_size == 75


def test_settings_merges_local_proxy_bypass_hosts(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NO_PROXY=sap.example.com,localhost\n"
        "no_proxy=127.0.0.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "DEFAULT_ENV_FILE", env_file)
    monkeypatch.setenv("NO_PROXY", "system.example.com")
    monkeypatch.delenv("SAP_ODATA_NO_PROXY", raising=False)

    settings = settings_module.Settings()

    assert settings.sap_proxy_bypass_hosts == "system.example.com,sap.example.com,localhost,127.0.0.1"
