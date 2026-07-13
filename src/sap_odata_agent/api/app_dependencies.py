from __future__ import annotations

from functools import lru_cache

from sap_odata_agent.application.llm_plan_critic import LlmPlanCritic
from sap_odata_agent.application.orchestrator import AgentOrchestrator
from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.application.thin_runtime import ThinRuntimeService
from sap_odata_agent.infrastructure.config.settings import get_settings
from sap_odata_agent.infrastructure.indexing.api_catalog_provider import ApiCatalogProvider
from sap_odata_agent.infrastructure.indexing.api_skill_provider import ApiSkillProvider
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.infrastructure.knowledge_graph import KnowledgeGraphProvider
from sap_odata_agent.infrastructure.llm.api_router import LlmApiRouter
from sap_odata_agent.infrastructure.llm.api_specific_planner import LlmApiSpecificPlanner
from sap_odata_agent.infrastructure.llm.failure_diagnoser import LlmFailureDiagnoser
from sap_odata_agent.infrastructure.llm.plan_repairer import LlmPlanRepairer
from sap_odata_agent.infrastructure.llm.planner import SimpleRepairEngine
from sap_odata_agent.infrastructure.llm.profiles import create_llm_client, get_llm_profile
from sap_odata_agent.infrastructure.llm.feedback_summarizer import LlmFeedbackSummarizer
from sap_odata_agent.infrastructure.llm.result_verifier_agent import LlmResultVerifierAgent
from sap_odata_agent.infrastructure.llm.result_presenter import LlmResultPresenter
from sap_odata_agent.infrastructure.llm.schema_research_agent import LlmSchemaResearchAgent
from sap_odata_agent.infrastructure.repositories.file_case_repository import JsonlCaseRepository
from sap_odata_agent.infrastructure.retrieval.local_doc_retriever import LocalDocRetriever
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


@lru_cache(maxsize=16)
def get_llm_client_for_profile(profile_id: str | None = None):
    profile = get_llm_profile(profile_id)
    return create_llm_client(profile)


def get_llm_client():
    return get_llm_client_for_profile()


@lru_cache(maxsize=1)
def get_feedback_summarizer() -> LlmFeedbackSummarizer:
    llm_client = get_llm_client()
    return LlmFeedbackSummarizer(
        llm_client=llm_client,
        enabled=llm_client is not None,
    )


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
        )
    )


@lru_cache(maxsize=1)
def get_thin_runtime_service() -> ThinRuntimeService:
    settings = get_settings()
    return ThinRuntimeService(
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
        executor=get_sap_executor(),
        case_repository=get_case_repository(),
    )


@lru_cache(maxsize=1)
def get_knowledge_graph_provider() -> KnowledgeGraphProvider:
    settings = get_settings()
    return KnowledgeGraphProvider(
        kg_root=settings.local_kg_root,
        enabled=settings.local_kg_enabled,
        max_evidence=settings.local_kg_max_evidence,
    )


@lru_cache(maxsize=16)
def get_orchestrator_for_profile(profile_id: str | None = None) -> AgentOrchestrator:
    settings = get_settings()
    profile = get_llm_profile(profile_id)
    llm_client = get_llm_client_for_profile(profile.id)
    llm_enabled = llm_client is not None
    return AgentOrchestrator(
        retriever=LocalDocRetriever(
            index_root=settings.index_root,
            service_name=settings.default_index_service,
        ),
        planner=LlmApiSpecificPlanner(
            index_root=settings.index_root,
            llm_client=llm_client,
            enabled=llm_enabled,
        ),
        validator=BasicPlanValidator(),
        compiler=BasicODataCompiler(base_url=settings.sap_base_url, index_root=settings.index_root),
        executor=get_sap_executor(),
        repair_engine=SimpleRepairEngine(),
        result_presenter=LlmResultPresenter(
            llm_client=llm_client,
            enabled=llm_enabled,
        ),
        case_repository=get_case_repository(),
        max_attempts=settings.max_attempts,
        retrieval_top_k=settings.retrieval_top_k,
        semantic_parser=None,
        schema_reranker=None,
        llm_plan_critic=LlmPlanCritic(
            llm_client=llm_client,
            enabled=llm_enabled,
        ),
        schema_feasibility_validator=SchemaFeasibilityValidator(
            index_root=settings.index_root,
            service_name=settings.default_index_service,
            enabled=True,
        ),
        api_skill_provider=ApiSkillProvider(
            skill_root=settings.api_skill_root,
            max_summary_chars=4000,
        ),
        enable_query_repair=False,
        api_catalog_provider=ApiCatalogProvider(
            index_root=settings.index_root,
            default_service_name=settings.default_index_service,
        ),
        api_router=LlmApiRouter(
            llm_client=llm_client,
            enabled=llm_enabled,
            default_service_name=settings.default_index_service,
            allow_default_fallback=False,
        ),
        schema_context_provider=SchemaContextProvider(
            index_root=settings.index_root,
        ),
        api_specific_planner=LlmApiSpecificPlanner(
            index_root=settings.index_root,
            llm_client=llm_client,
            enabled=llm_enabled,
        ),
        plan_repairer=LlmPlanRepairer(
            index_root=settings.index_root,
            llm_client=llm_client,
            enabled=llm_enabled,
        ),
        failure_diagnoser=LlmFailureDiagnoser(
            llm_client=llm_client,
            enabled=llm_enabled,
        ),
        schema_research_agent=LlmSchemaResearchAgent(
            llm_client=llm_client,
            enabled=llm_enabled,
        ),
        result_verifier_agent=LlmResultVerifierAgent(
            llm_client=llm_client,
            enabled=llm_enabled,
        ),
        knowledge_graph_provider=get_knowledge_graph_provider(),
        llm_planning_max_attempts=settings.llm_planning_max_attempts,
        use_llm_first_pipeline=True,
    )


def get_orchestrator() -> AgentOrchestrator:
    return get_orchestrator_for_profile()
