from __future__ import annotations

import re
import time
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from sap_odata_agent.application.diagnostic_critic import DiagnosticCritic
from sap_odata_agent.application.failure_attributor import FailureAttributor
from sap_odata_agent.application.llm_plan_critic import LlmPlanCritic
from sap_odata_agent.application.plan_critic import PlanCritic
from sap_odata_agent.application.planner_guardrail import PlannerGuardrail
from sap_odata_agent.application.presentation_verifier import PresentationVerifier
from sap_odata_agent.application.context_gate import ContextCarryGate
from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.domain.models import (
    AgentRequest,
    AgentResponse,
    ApiRouteDecision,
    CardinalityPolicy,
    CaseRecord,
    CriticFinding,
    ContextCarryDecision,
    FailureAttribution,
    GuardrailDecision,
    PlanningAttemptRecord,
    PresentationVerification,
    QueryConstraints,
    QueryShape,
    QueryPlan,
    RetrievedContext,
    RetrievedDocument,
    ResultPresentation,
    SelectedApi,
    ValidationIssue,
)
from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider
from sap_odata_agent.infrastructure.llm.failure_diagnoser import LlmFailureDiagnoser
from sap_odata_agent.infrastructure.llm.plan_repairer import (
    dataclass_list_to_dicts,
    execution_attempt_to_debug,
)
from sap_odata_agent.infrastructure.llm.result_verifier_agent import LlmResultVerifierAgent
from sap_odata_agent.infrastructure.llm.schema_research_agent import LlmSchemaResearchAgent
from sap_odata_agent.domain.ports import (
    CaseRepository,
    IntentPlanner,
    KnowledgeRetriever,
    ODataCompiler,
    PlanValidator,
    ResultPresenter,
    SapExecutor,
    SelfRepairEngine,
)
from sap_odata_agent.infrastructure.sap.odata_client import MultiStepSapExecutor
from sap_odata_agent.infrastructure.llm.constraint_extractor import QueryConstraintExtractor
from sap_odata_agent.infrastructure.llm.query_classifier import QueryShapeClassifier


class AgentOrchestrator:
    def __init__(
        self,
        retriever: KnowledgeRetriever,
        planner: IntentPlanner,
        validator: PlanValidator,
        compiler: ODataCompiler,
        executor: SapExecutor,
        repair_engine: SelfRepairEngine,
        result_presenter: ResultPresenter,
        case_repository: CaseRepository,
        max_attempts: int = 3,
        retrieval_top_k: int = 12,
        semantic_parser=None,
        schema_reranker=None,
        llm_plan_critic: LlmPlanCritic | None = None,
        schema_feasibility_validator: SchemaFeasibilityValidator | None = None,
        enable_query_repair: bool = True,
        api_catalog_provider=None,
        api_router=None,
        schema_context_provider: SchemaContextProvider | None = None,
        api_specific_planner=None,
        plan_repairer=None,
        failure_diagnoser: LlmFailureDiagnoser | None = None,
        schema_research_agent: LlmSchemaResearchAgent | None = None,
        result_verifier_agent: LlmResultVerifierAgent | None = None,
        llm_planning_max_attempts: int = 3,
        use_llm_first_pipeline: bool = False,
    ) -> None:
        self.retriever = retriever
        self.planner = planner
        self.validator = validator
        self.compiler = compiler
        self.executor = executor
        self.repair_engine = repair_engine
        self.result_presenter = result_presenter
        self.case_repository = case_repository
        self.max_attempts = max_attempts
        self.retrieval_top_k = retrieval_top_k
        self.semantic_parser = semantic_parser
        self.schema_reranker = schema_reranker
        self.schema_feasibility_validator = schema_feasibility_validator
        self.enable_query_repair = enable_query_repair
        self.api_catalog_provider = api_catalog_provider
        self.api_router = api_router
        self.schema_context_provider = schema_context_provider
        self.api_specific_planner = api_specific_planner
        self.plan_repairer = plan_repairer
        self.failure_diagnoser = failure_diagnoser or LlmFailureDiagnoser(enabled=False)
        self.schema_research_agent = schema_research_agent or LlmSchemaResearchAgent(enabled=False)
        self.result_verifier_agent = result_verifier_agent or LlmResultVerifierAgent(enabled=False)
        self.llm_planning_max_attempts = max(1, llm_planning_max_attempts)
        self.use_llm_first_pipeline = use_llm_first_pipeline
        self.multi_step_executor = MultiStepSapExecutor(compiler=compiler, executor=executor)
        self.query_classifier = QueryShapeClassifier()
        self.constraint_extractor = QueryConstraintExtractor()
        self.context_gate = ContextCarryGate()
        self.planner_guardrail = PlannerGuardrail()
        self.plan_critic = PlanCritic()
        self.llm_plan_critic = llm_plan_critic or LlmPlanCritic(enabled=False)
        self.diagnostic_critic = DiagnosticCritic()
        self.failure_attributor = FailureAttributor()
        self.presentation_verifier = PresentationVerifier()

    def run(self, request: AgentRequest) -> AgentResponse:
        if self.use_llm_first_pipeline:
            return self._run_llm_first(request)

        timings: list[dict] = []
        run_started_at = time.perf_counter()
        effective_request, seed_context = self._build_effective_request(request, timings)
        retrieval_query = effective_request.user_input
        context = seed_context
        if (
            effective_request.context_carry_decision
            and effective_request.context_carry_decision.should_carry
            and effective_request.resolved_user_input
        ):
            retrieval_query = effective_request.resolved_user_input
            context = self._timed_call(
                timings,
                "retriever.context_carry",
                "上下文继承检索",
                self.retriever.retrieve,
                retrieval_query,
                top_k=self.retrieval_top_k,
            )
        elif context is None:
            context = self._timed_call(
                timings,
                "retriever.retrieve",
                "本地索引检索",
                self.retriever.retrieve,
                retrieval_query,
                top_k=self.retrieval_top_k,
            )
        initial_plan = self._timed_call(
            timings,
            "planner.plan",
            "生成查询计划",
            self.planner.plan,
            effective_request,
            context,
        )
        current_plan = initial_plan
        issues: list[ValidationIssue] = []
        attempts = []
        latest_guardrail_decision: GuardrailDecision | None = None
        latest_critic_findings: list[CriticFinding] = []
        presentation_verification = PresentationVerification(passed=True, issues=[])

        if current_plan.needs_clarification:
            failure_attribution = self.failure_attributor.attribute(
                effective_request,
                current_plan,
                success=False,
                final_message=current_plan.clarification_question or "",
            )
            response = AgentResponse(
                success=False,
                plan=current_plan,
                validation_issues=[],
                attempts=[],
                data=None,
                presentation=ResultPresentation(
                    kind="text",
                    title="查询结果",
                    text=current_plan.clarification_question or "请补充更多信息后再继续查询。",
                ),
                final_message=current_plan.clarification_question or "More detail is needed before querying SAP.",
                needs_clarification=True,
                clarification_question=current_plan.clarification_question,
                clarification_options=current_plan.clarification_options,
                failure_attribution=failure_attribution,
            )
            self._attach_timing(response, timings, run_started_at)
            response.case_id = self._save_case(
                request,
                effective_request,
                context,
                initial_plan,
                current_plan,
                attempts,
                response,
                guardrail_decision=latest_guardrail_decision,
                critic_findings=latest_critic_findings,
                failure_attribution=failure_attribution,
                presentation_verification=presentation_verification,
            )
            return response

        for attempt_number in range(1, self.max_attempts + 1):
            latest_guardrail_decision = self._timed_call(
                timings,
                "guardrail.evaluate",
                "Guardrail 检查",
                self.planner_guardrail.evaluate,
                effective_request,
                current_plan,
            )
            latest_critic_findings = self._timed_call(
                timings,
                "critic.rule_review",
                "规则 Critic 检查",
                self.plan_critic.review,
                effective_request,
                current_plan,
            )
            latest_critic_findings.extend(
                self._timed_call(
                    timings,
                    "critic.diagnostic_review",
                    "诊断 Critic 检查",
                    self.diagnostic_critic.review,
                    effective_request,
                    context,
                    current_plan,
                    guardrail_decision=latest_guardrail_decision,
                    critic_findings=latest_critic_findings,
                )
            )
            latest_critic_findings.extend(
                self._timed_call(
                    timings,
                    "llm.plan_critic",
                    "LLM 计划审查",
                    self.llm_plan_critic.review,
                    effective_request,
                    context,
                    current_plan,
                    existing_findings=latest_critic_findings,
                )
            )
            if self._should_reground_schema(effective_request, latest_critic_findings):
                regrounded = self._reground_and_replan(
                    effective_request,
                    context,
                    timings,
                    feedback_memories=effective_request.feedback_memories,
                )
                if regrounded is not None:
                    effective_request, context, current_plan = regrounded
                    continue
            if self.schema_feasibility_validator is not None:
                feasibility_result = self._timed_call(
                    timings,
                    "schema_feasibility.validate",
                    "Schema 可行性校验",
                    self.schema_feasibility_validator.validate,
                    effective_request,
                    current_plan,
                )
                current_plan = replace(
                    current_plan,
                    planner_diagnostics={
                        **(current_plan.planner_diagnostics or {}),
                        "schema_feasibility": self.schema_feasibility_validator.to_debug_payload(feasibility_result),
                    },
                )
                if not feasibility_result.passed:
                    latest_critic_findings.extend(
                        self.schema_feasibility_validator.to_critic_findings(feasibility_result)
                    )
            if not latest_guardrail_decision.accepted or any(item.blocking for item in latest_critic_findings):
                error_messages = list(latest_guardrail_decision.reasons if latest_guardrail_decision else [])
                error_messages.extend(item.code for item in latest_critic_findings if item.blocking)
                if self.enable_query_repair and attempt_number < self.max_attempts:
                    current_plan = self._timed_call(
                        timings,
                        "repair.plan",
                        "计划修复",
                        self.repair_engine.repair,
                        request=effective_request,
                        context=context,
                        previous_plan=current_plan,
                        error_message="; ".join(error_messages) or "Plan failed guardrail review.",
                    )
                    continue
                issues = [
                    ValidationIssue(
                        severity="error",
                        message=item.message,
                        field=None,
                    )
                    for item in latest_critic_findings
                    if item.blocking
                ]
                break

            issues = self._timed_call(
                timings,
                "validator.basic_validate",
                "基础计划校验",
                self.validator.validate,
                current_plan,
            )
            blocking_issues = [issue for issue in issues if issue.severity == "error"]
            if blocking_issues:
                break

            execution_result = self._execute_query_plan(
                effective_request,
                current_plan,
                start_attempt_number=len(attempts) + 1,
                timings=timings,
            )
            attempts.extend(execution_result["attempts"])
            if execution_result["success"]:
                final_plan = execution_result["plan"]
                final_data = execution_result["data"]

                presentation = self._timed_call(
                    timings,
                    "llm.result_present",
                    "结果呈现生成",
                    self.result_presenter.present,
                    effective_request,
                    final_plan,
                    final_data,
                )
                presentation, presentation_verification = self._timed_call(
                    timings,
                    "presentation.verify",
                    "呈现结果校验",
                    self.presentation_verifier.verify_and_repair,
                    effective_request,
                    final_plan,
                    presentation,
                    final_data,
                )
                failure_attribution = self.failure_attributor.attribute(
                    effective_request,
                    final_plan,
                    success=True,
                    final_message="Query executed successfully.",
                    guardrail_decision=latest_guardrail_decision,
                    critic_findings=latest_critic_findings,
                    presentation_verification=presentation_verification,
                )
                response = AgentResponse(
                    success=True,
                    plan=final_plan,
                    validation_issues=issues,
                    attempts=attempts,
                    data=final_data,
                    presentation=presentation,
                    final_message="Query executed successfully.",
                    needs_clarification=False,
                    clarification_question=None,
                    clarification_options=[],
                    guardrail_decision=latest_guardrail_decision,
                    critic_findings=latest_critic_findings,
                    failure_attribution=failure_attribution,
                    presentation_verification=presentation_verification,
                )
                self._attach_timing(response, timings, run_started_at)
                response.case_id = self._save_case(
                    request,
                    effective_request,
                    context,
                    initial_plan,
                    final_plan,
                    attempts,
                    response,
                    guardrail_decision=latest_guardrail_decision,
                    critic_findings=latest_critic_findings,
                    failure_attribution=failure_attribution,
                    presentation_verification=presentation_verification,
                )
                return response

            execution = attempts[-1] if attempts else None
            if self.enable_query_repair and attempt_number < self.max_attempts:
                current_plan = self._timed_call(
                    timings,
                    "repair.plan",
                    "计划修复",
                    self.repair_engine.repair,
                    request=effective_request,
                    context=context,
                    previous_plan=current_plan,
                    error_message=(execution.error_message if execution else None) or "Unknown SAP execution error.",
                    )
                continue
            break

        failure_attribution = self.failure_attributor.attribute(
            effective_request,
            current_plan,
            success=False,
            final_message="Unable to produce a valid SAP OData request within the configured retry limit.",
            guardrail_decision=latest_guardrail_decision,
            critic_findings=latest_critic_findings,
            presentation_verification=presentation_verification,
        )
        response = AgentResponse(
            success=False,
            plan=current_plan,
            validation_issues=issues,
            attempts=attempts,
            data=None,
            presentation=None,
            final_message="Unable to produce a valid SAP OData request within the configured retry limit.",
            needs_clarification=False,
            clarification_question=None,
            clarification_options=[],
            guardrail_decision=latest_guardrail_decision,
            critic_findings=latest_critic_findings,
            failure_attribution=failure_attribution,
            presentation_verification=presentation_verification,
        )
        self._attach_timing(response, timings, run_started_at)
        response.case_id = self._save_case(
            request,
            effective_request,
            context,
            initial_plan,
            current_plan,
            attempts,
            response,
            guardrail_decision=latest_guardrail_decision,
            critic_findings=latest_critic_findings,
            failure_attribution=failure_attribution,
            presentation_verification=presentation_verification,
        )
        return response

    def _run_llm_first(self, request: AgentRequest) -> AgentResponse:
        timings: list[dict] = []
        run_started_at = time.perf_counter()
        recent_cases = self._timed_call(
            timings,
            "history.list_recent",
            "读取最近查询",
            self.case_repository.list_recent,
            limit=5,
            conversation_id=request.conversation_id,
        )
        clarification_case = None
        if request.conversation_id:
            clarification_case = self._timed_call(
                timings,
                "history.find_latest_clarification",
                "读取上一轮澄清",
                self.case_repository.find_latest_clarification,
                request.conversation_id,
            )
        feedback_memories = self._timed_call(
            timings,
            "history.search_feedback_memory",
            "检索反馈记忆",
            self._search_feedback_memory,
            request.user_input,
            limit=5,
        )
        api_catalog = self._timed_call(
            timings,
            "api_catalog.load",
            "加载 API Catalog",
            self.api_catalog_provider.load,
        )
        route_decision: ApiRouteDecision = self._timed_call(
            timings,
            "llm.api_route",
            "LLM API 路由",
            self.api_router.route,
            request.user_input,
            api_catalog,
            recent_cases=recent_cases,
            latest_clarification_case=clarification_case,
            feedback_memories=feedback_memories,
        )
        selected_service = route_decision.selected_apis[0].service_name if route_decision.selected_apis else ""
        effective_request = replace(
            request,
            resolved_user_input=route_decision.resolved_user_input or request.user_input,
            feedback_memories=feedback_memories,
            semantic_frame={
                "route_decision": route_decision.raw_response,
                "intent_summary": route_decision.intent_summary,
                "business_domain": route_decision.business_domain,
                "business_object": route_decision.business_object,
            },
            constraints=None,
        )
        context = RetrievedContext(documents=[], examples=[])
        placeholder_plan = QueryPlan(
            service_name=selected_service or "UNKNOWN_SERVICE",
            entity_set="UNKNOWN_ENTITY",
            rationale="LLM-first pipeline route placeholder.",
            planner_diagnostics={"route_decision": route_decision.raw_response},
        )

        if not route_decision.selected_apis and not route_decision.needs_clarification:
            latest_critic_findings = [
                CriticFinding(
                    code="api_routing_failed",
                    message="API router did not produce a valid API selection.",
                    severity="error",
                    blocking=True,
                )
            ]
            final_message = "API router did not produce a valid API selection. No SAP request was executed."
            failure_attribution = self.failure_attributor.attribute(
                effective_request,
                placeholder_plan,
                success=False,
                final_message=final_message,
                critic_findings=latest_critic_findings,
            )
            response = AgentResponse(
                success=False,
                plan=placeholder_plan,
                validation_issues=[],
                attempts=[],
                data=None,
                presentation=None,
                final_message=final_message,
                needs_clarification=False,
                clarification_question=None,
                clarification_options=[],
                critic_findings=latest_critic_findings,
                failure_attribution=failure_attribution,
            )
            self._attach_timing(response, timings, run_started_at)
            response.case_id = self._save_case(
                request,
                effective_request,
                context,
                placeholder_plan,
                placeholder_plan,
                [],
                response,
                critic_findings=latest_critic_findings,
                failure_attribution=failure_attribution,
                route_decision=route_decision,
                schema_context_summary={},
            )
            return response

        if route_decision.needs_clarification:
            failure_attribution = self.failure_attributor.attribute(
                effective_request,
                placeholder_plan,
                success=False,
                final_message=route_decision.clarification_question or "",
            )
            response = AgentResponse(
                success=False,
                plan=placeholder_plan,
                validation_issues=[],
                attempts=[],
                data=None,
                presentation=ResultPresentation(
                    kind="text",
                    title="查询结果",
                    text=route_decision.clarification_question or "需要补充更多信息后才能查询。",
                ),
                final_message=route_decision.clarification_question or "More detail is needed before querying SAP.",
                needs_clarification=True,
                clarification_question=route_decision.clarification_question,
                clarification_options=route_decision.clarification_options,
                failure_attribution=failure_attribution,
            )
            self._attach_timing(response, timings, run_started_at)
            response.case_id = self._save_case(
                request,
                effective_request,
                context,
                placeholder_plan,
                placeholder_plan,
                [],
                response,
                failure_attribution=failure_attribution,
                route_decision=route_decision,
            )
            return response

        schema_context = self._timed_call(
            timings,
            "schema_context.build",
            "构建 Schema Context",
            self.schema_context_provider.build,
            selected_service,
            effective_request.resolved_user_input or effective_request.user_input,
            route_decision,
            [],
            feedback_memories,
        )
        schema_research = self._timed_call(
            timings,
            "llm.schema_research",
            "LLM Schema Research",
            self.schema_research_agent.research,
            effective_request,
            route_decision,
            schema_context,
            feedback_memories,
        )
        schema_context = {
            **schema_context,
            "schema_research": schema_research,
        }
        schema_context_summary = self.schema_context_provider.summarize(schema_context)
        schema_context_summary["schema_research"] = self.schema_research_agent.summarize(schema_research)

        attempts = []
        planning_attempts: list[PlanningAttemptRecord] = []
        current_plan = placeholder_plan
        latest_guardrail_decision: GuardrailDecision | None = None
        latest_critic_findings: list[CriticFinding] = []
        latest_issues: list[ValidationIssue] = []
        presentation_verification = PresentationVerification(passed=True, issues=[])
        failure_context: dict = {
            "route_decision": route_decision.raw_response,
            "schema_context_summary": schema_context_summary,
            "previous_failures": [],
        }
        reroute_attempts = 0
        force_initial_plan_after_reroute = False

        for attempt_number in range(1, self.llm_planning_max_attempts + 1):
            if attempt_number == 1 or force_initial_plan_after_reroute:
                current_plan = self._timed_call(
                    timings,
                    "llm.api_specific_plan",
                    "LLM API 内查询规划",
                    self.api_specific_planner.plan_for_api,
                    effective_request,
                    route_decision,
                    schema_context,
                )
                stage = "plan"
                force_initial_plan_after_reroute = False
            else:
                current_plan = self._timed_call(
                    timings,
                    "llm.plan_repair",
                    "LLM 查询修复",
                    self.plan_repairer.repair,
                    effective_request,
                    route_decision,
                    schema_context,
                    current_plan,
                    attempt_number,
                    self.llm_planning_max_attempts,
                    failure_context,
                )
                stage = "repair"

            if self._plan_requests_reroute(current_plan) and reroute_attempts < 1:
                previous_service = selected_service
                rerouted = self._build_reroute_decision(
                    current_plan,
                    route_decision,
                    api_catalog,
                    request.user_input,
                    recent_cases,
                    clarification_case,
                    feedback_memories,
                    timings,
                )
                if rerouted.selected_apis:
                    reroute_attempts += 1
                    route_decision = rerouted
                    selected_service = route_decision.selected_apis[0].service_name
                    effective_request = replace(
                        effective_request,
                        resolved_user_input=route_decision.resolved_user_input
                        or effective_request.resolved_user_input
                        or effective_request.user_input,
                        semantic_frame={
                            **(effective_request.semantic_frame or {}),
                            "route_decision": route_decision.raw_response,
                            "intent_summary": route_decision.intent_summary,
                            "business_domain": route_decision.business_domain,
                            "business_object": route_decision.business_object,
                            "rerouted_from": previous_service,
                        },
                    )
                    placeholder_plan = QueryPlan(
                        service_name=selected_service or "UNKNOWN_SERVICE",
                        entity_set="UNKNOWN_ENTITY",
                        rationale="LLM-first pipeline route placeholder.",
                        planner_diagnostics={"route_decision": route_decision.raw_response},
                    )
                    schema_context, schema_research, schema_context_summary = self._build_llm_schema_context(
                        effective_request,
                        route_decision,
                        selected_service,
                        feedback_memories,
                        timings,
                    )
                    failure_context = {
                        "route_decision": route_decision.raw_response,
                        "schema_context_summary": schema_context_summary,
                        "previous_failures": list(failure_context.get("previous_failures", [])),
                        "rerouted_from": previous_service,
                    }
                    force_initial_plan_after_reroute = True
                    planning_attempts.append(
                        PlanningAttemptRecord(
                            attempt_number=attempt_number,
                            stage=stage,
                            plan=current_plan,
                            success=False,
                            failure_reason="repair_requested_reroute",
                        )
                    )
                    continue

            if current_plan.needs_clarification:
                failure_attribution = self.failure_attributor.attribute(
                    effective_request,
                    current_plan,
                    success=False,
                    final_message=current_plan.clarification_question or "",
                )
                response = AgentResponse(
                    success=False,
                    plan=current_plan,
                    validation_issues=[],
                    attempts=attempts,
                    data=None,
                    presentation=ResultPresentation(
                        kind="text",
                        title="查询结果",
                        text=current_plan.clarification_question or "需要补充更多信息后才能查询。",
                    ),
                    final_message=current_plan.clarification_question or "More detail is needed before querying SAP.",
                    needs_clarification=True,
                    clarification_question=current_plan.clarification_question,
                    clarification_options=current_plan.clarification_options,
                    failure_attribution=failure_attribution,
                )
                self._attach_timing(response, timings, run_started_at)
                response.case_id = self._save_case(
                    request,
                    effective_request,
                    context,
                    placeholder_plan,
                    current_plan,
                    attempts,
                    response,
                    failure_attribution=failure_attribution,
                    presentation_verification=presentation_verification,
                    route_decision=route_decision,
                    planning_attempts=planning_attempts,
                    schema_context_summary=schema_context_summary,
                )
                return response

            latest_guardrail_decision = self._timed_call(
                timings,
                "guardrail.evaluate",
                "Guardrail 检查",
                self.planner_guardrail.evaluate,
                effective_request,
                current_plan,
            )
            latest_critic_findings = self._timed_call(
                timings,
                "critic.rule_review",
                "规则 Critic 检查",
                self.plan_critic.review,
                effective_request,
                current_plan,
            )
            if self.schema_feasibility_validator is not None:
                feasibility_result = self._timed_call(
                    timings,
                    "schema_feasibility.validate",
                    "Schema 可行性校验",
                    self.schema_feasibility_validator.validate,
                    effective_request,
                    current_plan,
                )
                current_plan = replace(
                    current_plan,
                    planner_diagnostics={
                        **(current_plan.planner_diagnostics or {}),
                        "schema_feasibility": self.schema_feasibility_validator.to_debug_payload(feasibility_result),
                    },
                )
                if not feasibility_result.passed:
                    latest_critic_findings.extend(
                        self.schema_feasibility_validator.to_critic_findings(feasibility_result)
                    )

            latest_critic_findings.extend(
                self._timed_call(
                    timings,
                    "llm.plan_critic",
                    "LLM Plan Critic",
                    self.llm_plan_critic.review,
                    effective_request,
                    context,
                    current_plan,
                    existing_findings=latest_critic_findings,
                    schema_research=schema_research,
                )
            )

            blocked = (
                not latest_guardrail_decision.accepted
                or any(item.blocking for item in latest_critic_findings)
            )
            if not blocked:
                latest_issues = self._timed_call(
                    timings,
                    "validator.basic_validate",
                    "基础计划校验",
                    self.validator.validate,
                    current_plan,
                )
                blocked = any(issue.severity == "error" for issue in latest_issues)

            if blocked:
                failure_context = self._build_llm_repair_context(
                    current_plan,
                    latest_guardrail_decision,
                    latest_critic_findings,
                    latest_issues,
                    attempts[-1] if attempts else None,
                    failure_context,
                )
                planning_attempts.append(
                    PlanningAttemptRecord(
                        attempt_number=attempt_number,
                        stage=stage,
                        plan=current_plan,
                        success=False,
                        failure_reason="plan_validation_failed",
                        schema_violations=(
                            ((current_plan.planner_diagnostics or {}).get("schema_feasibility") or {}).get("violations", [])
                        ),
                        guardrail_reasons=list(latest_guardrail_decision.reasons if latest_guardrail_decision else []),
                        critic_findings=dataclass_list_to_dicts(latest_critic_findings),
                    )
                )
                continue

            execution_result = self._execute_query_plan(
                effective_request,
                current_plan,
                start_attempt_number=len(attempts) + 1,
                timings=timings,
            )
            attempts.extend(execution_result["attempts"])
            if execution_result["success"]:
                final_plan = execution_result["plan"]
                final_data = execution_result["data"]
                result_verification = self._timed_call(
                    timings,
                    "llm.result_verify",
                    "LLM Result Verifier",
                    self.result_verifier_agent.verify,
                    effective_request,
                    final_plan,
                    final_data,
                    schema_research,
                )
                final_plan = replace(
                    final_plan,
                    planner_diagnostics={
                        **(final_plan.planner_diagnostics or {}),
                        "schema_research": self.schema_research_agent.summarize(schema_research),
                        "result_verification": result_verification,
                    },
                )
                if not result_verification.get("passed", True):
                    verifier_findings = [
                        CriticFinding(
                            code=f"llm_result_{str(item.get('code', 'verification_failed'))}",
                            message=str(item.get("message", "Result verifier rejected the plan output.")),
                            severity="error" if item.get("blocking", True) else "warning",
                            blocking=bool(item.get("blocking", True)),
                        )
                        for item in result_verification.get("issues", [])
                        if isinstance(item, dict)
                    ]
                    if not verifier_findings:
                        verifier_findings = [
                            CriticFinding(
                                code="llm_result_verification_failed",
                                message="Result verifier rejected the plan output.",
                                severity="error",
                                blocking=True,
                            )
                        ]
                    latest_critic_findings.extend(verifier_findings)
                    failure_context = self._build_llm_repair_context(
                        final_plan,
                        latest_guardrail_decision,
                        latest_critic_findings,
                        latest_issues,
                        attempts[-1] if attempts else None,
                        failure_context,
                    )
                    failure_context["result_verification"] = result_verification
                    planning_attempts.append(
                        PlanningAttemptRecord(
                            attempt_number=attempt_number,
                            stage=stage,
                            plan=final_plan,
                            success=False,
                            failure_reason="result_verification_failed",
                            guardrail_reasons=list(latest_guardrail_decision.reasons if latest_guardrail_decision else []),
                            critic_findings=dataclass_list_to_dicts(latest_critic_findings),
                            sap_error=execution_attempt_to_debug(attempts[-1] if attempts else None),
                        )
                    )
                    continue
                planning_attempts.append(
                    PlanningAttemptRecord(
                        attempt_number=attempt_number,
                        stage=stage,
                        plan=final_plan,
                        success=True,
                    )
                )
                presentation = self._timed_call(
                    timings,
                    "llm.result_present",
                    "结果呈现生成",
                    self.result_presenter.present,
                    effective_request,
                    final_plan,
                    final_data,
                )
                presentation, presentation_verification = self._timed_call(
                    timings,
                    "presentation.verify",
                    "结果呈现校验",
                    self.presentation_verifier.verify_and_repair,
                    effective_request,
                    final_plan,
                    presentation,
                    final_data,
                )
                failure_attribution = self.failure_attributor.attribute(
                    effective_request,
                    final_plan,
                    success=True,
                    final_message="Query executed successfully.",
                    guardrail_decision=latest_guardrail_decision,
                    critic_findings=latest_critic_findings,
                    presentation_verification=presentation_verification,
                )
                response = AgentResponse(
                    success=True,
                    plan=final_plan,
                    validation_issues=latest_issues,
                    attempts=attempts,
                    data=final_data,
                    presentation=presentation,
                    final_message="Query executed successfully.",
                    guardrail_decision=latest_guardrail_decision,
                    critic_findings=latest_critic_findings,
                    failure_attribution=failure_attribution,
                    presentation_verification=presentation_verification,
                )
                self._attach_timing(response, timings, run_started_at)
                response.case_id = self._save_case(
                    request,
                    effective_request,
                    context,
                    placeholder_plan,
                    final_plan,
                    attempts,
                    response,
                    guardrail_decision=latest_guardrail_decision,
                    critic_findings=latest_critic_findings,
                    failure_attribution=failure_attribution,
                    presentation_verification=presentation_verification,
                    route_decision=route_decision,
                    planning_attempts=planning_attempts,
                    schema_context_summary=schema_context_summary,
                )
                return response

            latest_attempt = attempts[-1] if attempts else None
            failure_context = self._build_llm_repair_context(
                current_plan,
                latest_guardrail_decision,
                latest_critic_findings,
                latest_issues,
                latest_attempt,
                failure_context,
            )
            planning_attempts.append(
                PlanningAttemptRecord(
                    attempt_number=attempt_number,
                    stage=stage,
                    plan=current_plan,
                    success=False,
                    failure_reason="sap_execution_failed",
                    guardrail_reasons=list(latest_guardrail_decision.reasons if latest_guardrail_decision else []),
                    critic_findings=dataclass_list_to_dicts(latest_critic_findings),
                    sap_error=execution_attempt_to_debug(latest_attempt),
                )
            )

        diagnosis = self._timed_call(
            timings,
            "llm.failure_diagnose",
            "LLM 失败诊断",
            self.failure_diagnoser.diagnose,
            {
                "original_user_input": request.user_input,
                "resolved_user_input": effective_request.resolved_user_input or effective_request.user_input,
                "route_decision": route_decision.raw_response,
                "schema_context_summary": schema_context_summary,
                "planning_attempts": [
                    {
                        "attempt_number": item.attempt_number,
                        "stage": item.stage,
                        "success": item.success,
                        "failure_reason": item.failure_reason,
                        "guardrail_reasons": item.guardrail_reasons,
                        "sap_error": item.sap_error,
                    }
                    for item in planning_attempts
                ],
                "fallback_category": "unknown",
                "fallback_root_cause": "Unable to produce a valid SAP OData request after LLM planning attempts.",
                "fallback_evidence": [item.failure_reason for item in planning_attempts if item.failure_reason],
            },
        )
        failure_attribution = self.failure_attributor.attribute(
            effective_request,
            current_plan,
            success=False,
            final_message=diagnosis.root_cause or "Unable to produce a valid SAP OData request after LLM planning attempts.",
            guardrail_decision=latest_guardrail_decision,
            critic_findings=latest_critic_findings,
            presentation_verification=presentation_verification,
        )
        response = AgentResponse(
            success=False,
            plan=current_plan,
            validation_issues=latest_issues,
            attempts=attempts,
            data=None,
            presentation=None,
            final_message=(
                diagnosis.root_cause
                or f"Unable to produce a valid SAP OData request after {self.llm_planning_max_attempts} LLM planning attempts."
            ),
            guardrail_decision=latest_guardrail_decision,
            critic_findings=latest_critic_findings,
            failure_attribution=failure_attribution,
            presentation_verification=presentation_verification,
        )
        self._attach_timing(response, timings, run_started_at)
        response.case_id = self._save_case(
            request,
            effective_request,
            context,
            placeholder_plan,
            current_plan,
            attempts,
            response,
            guardrail_decision=latest_guardrail_decision,
            critic_findings=latest_critic_findings,
            failure_attribution=failure_attribution,
            presentation_verification=presentation_verification,
            route_decision=route_decision,
            planning_attempts=planning_attempts,
            schema_context_summary=schema_context_summary,
            final_failure_diagnosis=diagnosis,
        )
        return response

    def _build_llm_schema_context(
        self,
        effective_request: AgentRequest,
        route_decision: ApiRouteDecision,
        selected_service: str,
        feedback_memories: list[dict],
        timings: list[dict],
    ) -> tuple[dict, dict, dict]:
        schema_context = self._timed_call(
            timings,
            "schema_context.build",
            "譫・ｻｺ Schema Context",
            self.schema_context_provider.build,
            selected_service,
            effective_request.resolved_user_input or effective_request.user_input,
            route_decision,
            [],
            feedback_memories,
        )
        schema_research = self._timed_call(
            timings,
            "llm.schema_research",
            "LLM Schema Research",
            self.schema_research_agent.research,
            effective_request,
            route_decision,
            schema_context,
            feedback_memories,
        )
        schema_context = {
            **schema_context,
            "schema_research": schema_research,
        }
        schema_context_summary = self.schema_context_provider.summarize(schema_context)
        schema_context_summary["schema_research"] = self.schema_research_agent.summarize(schema_research)
        return schema_context, schema_research, schema_context_summary

    @staticmethod
    def _plan_requests_reroute(plan: QueryPlan) -> bool:
        diagnostics = plan.planner_diagnostics or {}
        dynamic = diagnostics.get("llm_dynamic_path_planner") or {}
        raw = dynamic.get("raw") if isinstance(dynamic, dict) else {}
        return (
            str(plan.plan_kind or "") == "reroute_required"
            or str(diagnostics.get("plan_kind") or "") == "reroute_required"
            or str(dynamic.get("reason") if isinstance(dynamic, dict) else "") == "repair_requested_reroute"
            or str((raw or {}).get("plan_kind") if isinstance(raw, dict) else "") == "reroute_required"
        )

    def _build_reroute_decision(
        self,
        plan: QueryPlan,
        previous_route: ApiRouteDecision,
        api_catalog: list[dict],
        user_input: str,
        recent_cases: list[dict],
        clarification_case: dict | None,
        feedback_memories: list[dict],
        timings: list[dict],
    ) -> ApiRouteDecision:
        valid_catalog = {
            str(item.get("service_name") or ""): item
            for item in api_catalog
            if str(item.get("service_name") or "")
        }
        previous_service = previous_route.selected_apis[0].service_name if previous_route.selected_apis else ""
        requested_service = self._extract_reroute_service_from_plan(plan)
        if requested_service in valid_catalog and requested_service != previous_service:
            raw_response = {
                "accepted": True,
                "reason": "repair_requested_reroute",
                "selected_apis": [{"service_name": requested_service}],
                "previous_route": previous_route.raw_response,
                "planner_diagnostics": plan.planner_diagnostics or {},
            }
            return ApiRouteDecision(
                resolved_user_input=previous_route.resolved_user_input or user_input,
                selected_apis=[
                    SelectedApi(
                        service_name=requested_service,
                        confidence=0.8,
                        reason="Planner repair requested reroute to this API.",
                    )
                ],
                requires_multi_api=previous_route.requires_multi_api,
                intent_summary=previous_route.intent_summary,
                business_domain=previous_route.business_domain,
                business_object=previous_route.business_object,
                raw_response=raw_response,
            )
        return self._timed_call(
            timings,
            "llm.api_reroute",
            "LLM API Reroute",
            self.api_router.route,
            user_input,
            api_catalog,
            recent_cases=recent_cases,
            latest_clarification_case=clarification_case,
            feedback_memories=feedback_memories,
        )

    @staticmethod
    def _extract_reroute_service_from_plan(plan: QueryPlan) -> str:
        diagnostics = plan.planner_diagnostics or {}
        dynamic = diagnostics.get("llm_dynamic_path_planner") or {}
        raw = dynamic.get("raw") if isinstance(dynamic, dict) else {}
        candidates = [
            raw.get("service_name") if isinstance(raw, dict) else None,
            raw.get("target_service_name") if isinstance(raw, dict) else None,
            raw.get("recommended_service_name") if isinstance(raw, dict) else None,
            dynamic.get("service_name") if isinstance(dynamic, dict) else None,
            diagnostics.get("service_name"),
            plan.service_name,
        ]
        for candidate in candidates:
            service_name = str(candidate or "").strip()
            if service_name:
                return service_name
        return ""

    def _execute_query_plan(
        self,
        request: AgentRequest,
        plan: QueryPlan,
        start_attempt_number: int,
        timings: list[dict] | None = None,
    ) -> dict:
        timings = timings if timings is not None else []
        if plan.plan_kind in {"lookup", "multi_step"} and plan.steps:
            path_attempts, final_data = self._timed_call(
                timings,
                "sap.multi_step_execute",
                "多步 SAP OData 执行",
                self.multi_step_executor.execute_plan,
                plan,
                starting_attempt_number=start_attempt_number,
            )
            return {
                "success": bool(path_attempts and path_attempts[-1].success and final_data is not None),
                "plan": plan,
                "attempts": path_attempts,
                "data": final_data,
            }

        compiled_request = self._timed_call(
            timings,
            "odata.compile",
            "编译 OData 请求",
            self.compiler.compile,
            plan,
        )
        execution = self._timed_call(
            timings,
            "sap.execute",
            "执行 SAP OData 请求",
            self.executor.execute,
            compiled_request,
            start_attempt_number,
        )
        attempts = [execution]
        if not execution.success:
            return {"success": False, "plan": plan, "attempts": attempts, "data": None}

        final_plan = plan
        final_data = execution.response_preview
        return {
            "success": True,
            "plan": final_plan,
            "attempts": attempts,
            "data": final_data,
        }

    def _build_effective_request(self, request: AgentRequest, timings: list[dict] | None = None) -> tuple[AgentRequest, object]:
        timings = timings if timings is not None else []
        recent_cases = self._timed_call(
            timings,
            "history.list_recent",
            "读取最近查询",
            self.case_repository.list_recent,
            limit=5,
            conversation_id=request.conversation_id,
        )
        clarification_case = None
        if request.conversation_id:
            clarification_case = self._timed_call(
                timings,
                "history.find_latest_clarification",
                "读取澄清上下文",
                self.case_repository.find_latest_clarification,
                request.conversation_id,
            )
        query_shape, cardinality_policy, classifier_diagnostics = self._timed_call(
            timings,
            "query.classify",
            "查询形态识别",
            self.query_classifier.classify,
            request.user_input,
            previous_clarification_question=(
                ((clarification_case or {}).get("initial_plan") or {}).get("clarification_question")
                if clarification_case is not None
                else None
            ),
        )
        seed_context = self._timed_call(
            timings,
            "retriever.retrieve",
            "本地索引检索",
            self.retriever.retrieve,
            request.user_input,
            top_k=self.retrieval_top_k,
        )
        candidate_fields = self._extract_candidate_fields(seed_context)
        constraints = self._timed_call(
            timings,
            "constraints.extract",
            "结构化约束抽取",
            self.constraint_extractor.extract,
            request.user_input,
            query_shape,
            cardinality_policy,
            candidate_fields=candidate_fields,
        )
        carry_decision = self._timed_call(
            timings,
            "context_carry.decide",
            "上下文继承判断",
            self.context_gate.decide,
            request.user_input,
            query_shape,
            clarification_case,
        )
        relevant_feedback = self._timed_call(
            timings,
            "history.search_feedback",
            "检索历史反馈",
            self.case_repository.search_feedback,
            request.user_input,
            limit=3,
        )
        feedback_hints = self._build_feedback_hints(relevant_feedback)
        feedback_memories = self._timed_call(
            timings,
            "history.search_feedback_memory",
            "检索反馈记忆",
            self._search_feedback_memory,
            request.user_input,
            limit=5,
        )

        semantic_frame = {}
        if self.semantic_parser is not None:
            constraints, semantic_frame = self._timed_call(
                timings,
                "llm.semantic_parse",
                "LLM 语义解析",
                self.semantic_parser.parse,
                request.user_input,
                constraints,
                candidate_fields=candidate_fields,
                feedback_hints=feedback_hints,
                feedback_memories=feedback_memories,
            )

        schema_rerank = {}
        if self.schema_reranker is not None:
            schema_rerank = self._timed_call(
                timings,
                "llm.schema_rerank",
                "LLM Schema 候选重排",
                self.schema_reranker.rerank,
                request.user_input,
                constraints,
                retrieved_documents=seed_context.documents,
                feedback_memories=feedback_memories,
            )
            constraints = self._apply_schema_rerank_to_constraints(constraints, schema_rerank)
            seed_context = self._augment_context_with_schema_rerank(seed_context, schema_rerank)

        sections: list[str] = []
        if clarification_case is not None and carry_decision.should_carry:
            previous_input = clarification_case.get("effective_user_input") or (
                (clarification_case.get("request") or {}).get("user_input") or ""
            )
            clarification_question = (
                ((clarification_case.get("initial_plan") or {}).get("clarification_question"))
                or "请补充之前问题里缺失的业务维度。"
            )
            sections.extend(
                [
                    "这是同一会话里的澄清追问，请把本轮输入视为对上一轮问题的补充。",
                    f"原始问题: {previous_input}",
                    f"上一轮澄清: {clarification_question}",
                ]
            )

        resolved_user_input = None
        if sections:
            sections.append(f"本轮用户输入: {request.user_input}")
            sections.append("请基于澄清上下文理解当前意图，只输出与本轮问题相关的查询。")
            resolved_user_input = "\n".join(section for section in sections if section.strip())

        if resolved_user_input is None and not feedback_hints:
            return (
                replace(
                    request,
                    query_shape=query_shape,
                    cardinality_policy=cardinality_policy,
                    constraints=constraints,
                    feedback_hints=feedback_hints,
                    feedback_memories=feedback_memories,
                    semantic_frame=semantic_frame,
                    schema_rerank=schema_rerank,
                    context_carry_decision=carry_decision,
                ),
                seed_context,
            )

        return (
            replace(
                request,
                resolved_user_input=resolved_user_input,
                feedback_hints=feedback_hints,
                feedback_memories=feedback_memories,
                semantic_frame=semantic_frame,
                schema_rerank=schema_rerank,
                query_shape=query_shape,
                cardinality_policy=cardinality_policy,
                constraints=constraints,
                context_carry_decision=replace(
                    carry_decision,
                    reason=f"{carry_decision.reason}; classifier={','.join(classifier_diagnostics.get('matched_terms', []))}; recent_cases={len(recent_cases)}",
                ),
            ),
            seed_context,
        )

    def _search_feedback_memory(self, query: str, limit: int = 5) -> list[dict]:
        searcher = getattr(self.case_repository, "search_feedback_memory", None)
        if not callable(searcher):
            return []
        try:
            return searcher(query, limit=limit)
        except Exception:
            return []

    @staticmethod
    def _build_llm_repair_context(
        plan: QueryPlan,
        guardrail_decision: GuardrailDecision | None,
        critic_findings: list[CriticFinding],
        validation_issues: list[ValidationIssue],
        latest_attempt,
        previous_context: dict,
    ) -> dict:
        previous_failures = list((previous_context or {}).get("previous_failures", []))
        failure = {
            "previous_plan": {
                "service_name": plan.service_name,
                "entity_set": plan.entity_set,
                "plan_kind": plan.plan_kind,
                "select_fields": plan.select_fields,
                "filters": [
                    {"field": item.field, "operator": item.operator, "value": item.value}
                    for item in plan.filters
                ],
                "steps": [
                    {
                        "step_id": step.step_id,
                        "entity_set": step.entity_set,
                        "select_fields": step.select_fields,
                        "filters": [
                            {"field": item.field, "operator": item.operator, "value": item.value}
                            for item in step.filters
                        ],
                        "filter_from_previous": [
                            {
                                "field": item.field,
                                "source_step_id": item.source_step_id,
                                "source_field": item.source_field,
                            }
                            for item in step.filter_from_previous
                        ],
                    }
                    for step in plan.steps
                ],
            },
            "guardrail": {
                "accepted": guardrail_decision.accepted if guardrail_decision else None,
                "reasons": guardrail_decision.reasons if guardrail_decision else [],
                "severity": guardrail_decision.severity if guardrail_decision else "",
            },
            "critic_findings": dataclass_list_to_dicts(critic_findings),
            "validation_issues": dataclass_list_to_dicts(validation_issues),
            "schema_feasibility": (plan.planner_diagnostics or {}).get("schema_feasibility", {}),
            "sap_error": execution_attempt_to_debug(latest_attempt),
        }
        previous_failures.append(failure)
        return {
            **(previous_context or {}),
            "latest_failure": failure,
            "previous_failures": previous_failures[-5:],
        }

    def _should_reground_schema(
        self,
        request: AgentRequest,
        findings: list[CriticFinding],
    ) -> bool:
        if self.schema_reranker is None:
            return False
        if (request.schema_rerank or {}).get("grounding_reason") == "critic_requested_broad_schema_grounding":
            return False
        blocking_codes = {finding.code for finding in findings if finding.blocking}
        if not blocking_codes:
            return False
        return bool(
            blocking_codes.intersection(
                {
                    "llm_wrong_entity_for_target",
                    "llm_wrong_entity_selection",
                    "llm_required_target_field_missing",
                    "required_target_field_missing",
                    "schema_missing_required_answer_field",
                    "schema_missing_required_filter_field",
                }
            )
        )

    def _reground_and_replan(
        self,
        request: AgentRequest,
        context: RetrievedContext,
        timings: list[dict],
        *,
        feedback_memories: list[dict],
    ) -> tuple[AgentRequest, RetrievedContext, QueryPlan] | None:
        if self.schema_reranker is None or request.constraints is None:
            return None
        schema_rerank = self._timed_call(
            timings,
            "llm.schema_grounding_fallback",
            "LLM Schema Grounding 兜底",
            self.schema_reranker.rerank,
            request.resolved_user_input or request.user_input,
            request.constraints,
            retrieved_documents=context.documents,
            feedback_memories=feedback_memories,
            top_k=180,
            force_broad_schema=True,
        )
        grounded_constraints = self._apply_schema_rerank_to_constraints(request.constraints, schema_rerank)
        if grounded_constraints == request.constraints:
            return None
        grounded_context = self._augment_context_with_schema_rerank(context, schema_rerank)
        grounded_request = replace(
            request,
            constraints=grounded_constraints,
            schema_rerank={
                **(request.schema_rerank or {}),
                **schema_rerank,
                "regrounded_after_critic": True,
            },
        )
        grounded_plan = self._timed_call(
            timings,
            "planner.replan_after_schema_grounding",
            "Schema Grounding 后重新规划",
            self.planner.plan,
            grounded_request,
            grounded_context,
        )
        return grounded_request, grounded_context, grounded_plan

    def _timed_call(
        self,
        timings: list[dict],
        key: str,
        label: str,
        func,
        *args,
        **kwargs,
    ):
        started_at = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            self._record_timing(
                timings,
                key=key,
                label=label,
                started_at=started_at,
                success=False,
                error_message=str(exc),
            )
            raise
        self._record_timing(timings, key=key, label=label, started_at=started_at, success=True)
        return result

    @staticmethod
    def _record_timing(
        timings: list[dict],
        *,
        key: str,
        label: str,
        started_at: float,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        entry = {
            "key": key,
            "label": label,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "success": success,
        }
        if error_message:
            entry["error_message"] = error_message
        timings.append(entry)

    def _attach_timing(self, response: AgentResponse, timings: list[dict], started_at: float) -> None:
        response.timings = [dict(item) for item in timings]
        response.timing_summary = self._timing_summary(timings)
        response.total_duration_ms = round((time.perf_counter() - started_at) * 1000, 2)

    @staticmethod
    def _timing_summary(timings: list[dict]) -> dict[str, float]:
        summary: dict[str, float] = {}
        for item in timings:
            key = str(item.get("key") or item.get("label") or "unknown")
            summary[key] = round(summary.get(key, 0.0) + float(item.get("duration_ms") or 0.0), 2)
        return summary

    @staticmethod
    def _extract_candidate_fields(context) -> list[dict]:
        candidate_fields: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for document in (context.documents if context else []):
            metadata = document.metadata or {}
            field_name = metadata.get("field_name")
            entity_set = metadata.get("entity_set")
            if not field_name or not entity_set:
                continue
            key = (str(entity_set), str(field_name))
            if key in seen:
                continue
            seen.add(key)
            candidate_fields.append(metadata)
        return candidate_fields

    @staticmethod
    def _apply_schema_rerank_to_constraints(
        constraints: QueryConstraints,
        schema_rerank: dict,
    ) -> QueryConstraints:
        answer_fields = [
            str(field).strip()
            for field in schema_rerank.get("answer_fields", [])
            if str(field).strip()
        ]
        filter_fields = [
            str(field).strip()
            for field in schema_rerank.get("filter_fields", [])
            if str(field).strip()
        ]
        if not answer_fields and not filter_fields:
            return constraints
        return replace(
            constraints,
            target_field_concepts=list(dict.fromkeys([*constraints.target_field_concepts, *answer_fields])),
            filter_concepts=list(dict.fromkeys([*constraints.filter_concepts, *filter_fields])),
        )

    @staticmethod
    def _augment_context_with_schema_rerank(
        context: RetrievedContext,
        schema_rerank: dict,
    ) -> RetrievedContext:
        ranked_fields = schema_rerank.get("ranked_fields", [])
        if not ranked_fields:
            return context
        existing_keys = {
            (document.source, document.title)
            for document in context.documents
        }
        documents: list[RetrievedDocument] = []
        for index, field in enumerate(ranked_fields[:24]):
            entity_set = str(field.get("entity_set", "") or "")
            field_name = str(field.get("field_name", "") or "")
            if not entity_set or not field_name:
                continue
            title = f"{entity_set}.{field_name}"
            key = ("llm-schema-rerank", title)
            if key in existing_keys:
                continue
            documents.append(
                RetrievedDocument(
                    source="llm-schema-rerank",
                    title=title,
                    content=(
                        f"LLM schema rerank candidate `{field_name}` on `{entity_set}`. "
                        f"Label: {field.get('label', '')}. "
                        f"Description: {field.get('description', '')}. "
                        f"Reason: {field.get('llm_reason', '')}."
                    ),
                    score=float(field.get("llm_confidence", 0.0) or 0.0) * 100.0
                    if field.get("llm_confidence") is not None
                    else max(1.0, 100.0 - index),
                    metadata=field,
                )
            )
        if not documents:
            return context
        return replace(context, documents=[*documents, *context.documents])

    @staticmethod
    def _build_feedback_hints(entries: list[dict]) -> list[dict[str, str]]:
        hints: list[dict[str, str]] = []
        for entry in entries:
            feedback = entry.get("feedback") or {}
            original_input = (entry.get("request") or {}).get("user_input") or ""
            comment = feedback.get("comment") or ""
            expected = feedback.get("expected_result") or ""
            hint = {
                "previous_query": original_input,
                "mistake": comment,
                "expected_result": expected,
            }
            if any(value.strip() for value in hint.values()):
                hints.append(hint)
        return hints

    def _save_case(
        self,
        request: AgentRequest,
        effective_request: AgentRequest,
        context,
        initial_plan: QueryPlan,
        final_plan: QueryPlan,
        attempts,
        response: AgentResponse,
        guardrail_decision: GuardrailDecision | None = None,
        critic_findings: list[CriticFinding] | None = None,
        failure_attribution: FailureAttribution | None = None,
        presentation_verification: PresentationVerification | None = None,
        route_decision: ApiRouteDecision | None = None,
        planning_attempts: list[PlanningAttemptRecord] | None = None,
        schema_context_summary: dict | None = None,
        final_failure_diagnosis=None,
    ) -> str:
        latest_attempt = attempts[-1] if attempts else None
        case_id = str(uuid4())
        record = CaseRecord(
            case_id=case_id,
            created_at=datetime.now().astimezone(),
            request=request,
            context=context,
            initial_plan=initial_plan,
            final_plan=final_plan,
            attempts=attempts,
            final_status=(
                "clarification_requested"
                if response.needs_clarification
                else ("success" if response.success else "failed")
            ),
            final_query_url=latest_attempt.request.url if latest_attempt else None,
            response_preview=response.data,
            effective_user_input=effective_request.resolved_user_input,
            presentation=response.presentation,
            guardrail_decision=guardrail_decision,
            critic_findings=critic_findings or [],
            failure_attribution=failure_attribution,
            presentation_verification=presentation_verification,
            timings=response.timings,
            timing_summary=response.timing_summary,
            total_duration_ms=response.total_duration_ms,
            route_decision=route_decision,
            planning_attempts=planning_attempts or [],
            schema_context_summary=schema_context_summary or {},
            final_failure_diagnosis=final_failure_diagnosis,
            feedback=None,
            error_summary=None if response.success else response.final_message,
        )
        self.case_repository.save(record)
        return case_id
