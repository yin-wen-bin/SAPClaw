from __future__ import annotations

from functools import lru_cache

from sap_odata_agent.application.runtime import SapClawRuntimeService
from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.infrastructure.config.settings import get_settings
from sap_odata_agent.infrastructure.indexing.api_catalog_provider import ApiCatalogProvider
from sap_odata_agent.infrastructure.indexing.api_skill_provider import ApiSkillProvider
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.infrastructure.knowledge_graph import KnowledgeGraphProvider
from sap_odata_agent.infrastructure.repositories.file_case_repository import JsonlCaseRepository
from sap_odata_agent.infrastructure.sap.live_schema import LiveSchemaProvider
from sap_odata_agent.infrastructure.sap.odata_client import (
    BasicODataCompiler,
    BasicPlanValidator,
    SapODataExecutor,
    SapRuntimeConfig,
)


@lru_cache(maxsize=1)
def get_case_repository() -> JsonlCaseRepository:
    settings = get_settings()
    return JsonlCaseRepository(settings.case_store_path)


@lru_cache(maxsize=1)
def get_sap_executor() -> SapODataExecutor:
    settings = get_settings()
    return SapODataExecutor(
        SapRuntimeConfig(
            base_url=settings.sap_base_url,
            username=settings.sap_username,
            password=settings.sap_password,
            client=settings.sap_client,
            verify_ssl=settings.sap_verify_ssl,
            auth_type=settings.sap_auth_type,
            timeout_seconds=max(1, settings.sap_timeout_ms // 1000),
            proxy_bypass_hosts=settings.sap_proxy_bypass_hosts,
        )
    )


@lru_cache(maxsize=1)
def get_knowledge_graph_provider() -> KnowledgeGraphProvider:
    settings = get_settings()
    return KnowledgeGraphProvider(
        kg_root=settings.local_kg_root,
        enabled=settings.local_kg_enabled,
        max_evidence=settings.local_kg_max_evidence,
    )


@lru_cache(maxsize=1)
def get_runtime_service() -> SapClawRuntimeService:
    settings = get_settings()
    sap_executor = get_sap_executor()
    return SapClawRuntimeService(
        settings=settings,
        catalog_provider=ApiCatalogProvider(
            index_root=settings.index_root,
            default_service_name=settings.default_index_service,
        ),
        skill_provider=ApiSkillProvider(
            skill_root=settings.api_skill_root,
            max_summary_chars=4000,
        ),
        knowledge_graph_provider=get_knowledge_graph_provider(),
        schema_context_provider=SchemaContextProvider(index_root=settings.index_root),
        schema_validator=SchemaFeasibilityValidator(
            index_root=settings.index_root,
            service_name=settings.default_index_service,
            enabled=True,
        ),
        plan_validator=BasicPlanValidator(),
        compiler=BasicODataCompiler(
            base_url=settings.sap_base_url,
            index_root=settings.index_root,
        ),
        executor=sap_executor,
        live_schema_provider=LiveSchemaProvider(
            fetch_metadata=sap_executor.fetch_metadata,
            fresh_ttl_seconds=settings.runtime_live_schema_ttl_seconds,
            max_stale_seconds=settings.runtime_live_schema_max_stale_seconds,
        ),
        case_repository=get_case_repository(),
    )
