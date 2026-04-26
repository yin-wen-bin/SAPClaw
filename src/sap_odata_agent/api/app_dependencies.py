from __future__ import annotations

from functools import lru_cache

from sap_odata_agent.application.llm_plan_critic import LlmPlanCritic
from sap_odata_agent.application.orchestrator import AgentOrchestrator
from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.infrastructure.config.settings import get_settings
from sap_odata_agent.infrastructure.indexing.api_catalog_provider import ApiCatalogProvider
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.infrastructure.llm.api_router import LlmApiRouter
from sap_odata_agent.infrastructure.llm.api_specific_planner import LlmApiSpecificPlanner
from sap_odata_agent.infrastructure.llm.failure_diagnoser import LlmFailureDiagnoser
from sap_odata_agent.infrastructure.llm.plan_repairer import LlmPlanRepairer
from sap_odata_agent.infrastructure.llm.planner import (
    AnthropicCompatibleMessagesClient,
    SimpleRepairEngine,
)
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


@lru_cache(maxsize=1)
def get_llm_client() -> AnthropicCompatibleMessagesClient | None:
    settings = get_settings()
    if settings.llm_enabled:
        return AnthropicCompatibleMessagesClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=max(1, settings.llm_timeout_ms // 1000),
            verify_ssl=settings.llm_verify_ssl,
        )
    return None


@lru_cache(maxsize=1)
def get_feedback_summarizer() -> LlmFeedbackSummarizer:
    settings = get_settings()
    return LlmFeedbackSummarizer(
        llm_client=get_llm_client(),
        enabled=settings.llm_enabled,
    )


@lru_cache(maxsize=1)
def get_orchestrator() -> AgentOrchestrator:
    settings = get_settings()
    llm_client = get_llm_client()
    return AgentOrchestrator(
        retriever=LocalDocRetriever(
            index_root=settings.index_root,
            service_name=settings.default_index_service,
        ),
        planner=LlmApiSpecificPlanner(
            index_root=settings.index_root,
            llm_client=llm_client,
            enabled=settings.llm_enabled,
        ),
        validator=BasicPlanValidator(),
        compiler=BasicODataCompiler(base_url=settings.sap_base_url),
        executor=SapODataExecutor(
            SapRuntimeConfig(
                base_url=settings.sap_base_url,
                username=settings.sap_username,
                password=settings.sap_password,
                client=settings.sap_client,
                verify_ssl=settings.sap_verify_ssl,
                auth_type=settings.sap_auth_type,
                timeout_seconds=max(1, settings.sap_timeout_ms // 1000),
            )
        ),
        repair_engine=SimpleRepairEngine(),
        result_presenter=LlmResultPresenter(
            llm_client=llm_client,
            enabled=settings.llm_enabled,
        ),
        case_repository=get_case_repository(),
        max_attempts=settings.max_attempts,
        retrieval_top_k=settings.retrieval_top_k,
        semantic_parser=None,
        schema_reranker=None,
        llm_plan_critic=LlmPlanCritic(
            llm_client=llm_client,
            enabled=settings.llm_enabled,
        ),
        schema_feasibility_validator=SchemaFeasibilityValidator(
            index_root=settings.index_root,
            service_name=settings.default_index_service,
            enabled=True,
        ),
        enable_query_repair=False,
        api_catalog_provider=ApiCatalogProvider(
            index_root=settings.index_root,
            default_service_name=settings.default_index_service,
        ),
        api_router=LlmApiRouter(
            llm_client=llm_client,
            enabled=settings.llm_enabled,
            default_service_name=settings.default_index_service,
            allow_default_fallback=False,
        ),
        schema_context_provider=SchemaContextProvider(
            index_root=settings.index_root,
        ),
        api_specific_planner=LlmApiSpecificPlanner(
            index_root=settings.index_root,
            llm_client=llm_client,
            enabled=settings.llm_enabled,
        ),
        plan_repairer=LlmPlanRepairer(
            index_root=settings.index_root,
            llm_client=llm_client,
            enabled=settings.llm_enabled,
        ),
        failure_diagnoser=LlmFailureDiagnoser(
            llm_client=llm_client,
            enabled=settings.llm_enabled,
        ),
        schema_research_agent=LlmSchemaResearchAgent(
            llm_client=llm_client,
            enabled=settings.llm_enabled,
        ),
        result_verifier_agent=LlmResultVerifierAgent(
            llm_client=llm_client,
            enabled=settings.llm_enabled,
        ),
        llm_planning_max_attempts=settings.llm_planning_max_attempts,
        use_llm_first_pipeline=True,
    )
