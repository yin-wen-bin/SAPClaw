from pathlib import Path

from sap_odata_agent.application.orchestrator import AgentOrchestrator
from sap_odata_agent.domain.models import (
    AgentRequest,
    ApiRouteDecision,
    CompiledRequest,
    ExecutionAttempt,
    QueryPlan,
    ResultPresentation,
    SelectedApi,
)
from sap_odata_agent.infrastructure.repositories.file_case_repository import JsonlCaseRepository


class StaticCatalogProvider:
    def load(self):
        return [{"service_name": "API_TEST", "business_scope": ["test"], "top_entities": ["A_Bad", "A_Good"]}]


class StaticRouter:
    def route(self, user_input, api_catalog, recent_cases=None, latest_clarification_case=None, feedback_memories=None):
        return ApiRouteDecision(
            resolved_user_input=user_input,
            selected_apis=[SelectedApi(service_name="API_TEST", confidence=0.99, reason="test")],
            intent_summary="test intent",
            raw_response={"selected_apis": [{"service_name": "API_TEST"}]},
        )


class StaticSchemaContextProvider:
    def build(self, service_name, query, route_decision=None, retrieved_documents=None, feedback_memories=None):
        return {"service_name": service_name, "entities": [{"entity_set": "A_Good"}], "candidate_fields": []}

    @staticmethod
    def summarize(schema_context):
        return {"service_name": schema_context["service_name"], "entity_count": 1}


class InitialPlanner:
    def __init__(self):
        self.calls = 0

    def plan_for_api(self, request, route_decision, schema_context):
        self.calls += 1
        return QueryPlan(
            service_name="API_TEST",
            entity_set="A_Bad",
            select_fields=["BadField"],
            rationale="first plan intentionally fails",
        )


class RepairPlanner:
    def __init__(self, always_bad=False):
        self.calls = 0
        self.always_bad = always_bad

    def repair(self, request, route_decision, schema_context, previous_plan, attempt_number, max_attempts, failure_context):
        self.calls += 1
        entity_set = "A_Bad" if self.always_bad else "A_Good"
        return QueryPlan(
            service_name="API_TEST",
            entity_set=entity_set,
            select_fields=["GoodField"],
            rationale=f"repair attempt {attempt_number}",
        )


class PassThroughValidator:
    def validate(self, plan):
        return []


class SimpleCompiler:
    def compile(self, plan):
        return CompiledRequest(method="GET", url=f"https://sap.example.com/{plan.entity_set}")


class FailingThenPassingExecutor:
    def execute(self, compiled_request, attempt_number):
        if "A_Bad" in compiled_request.url:
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=False,
                status_code=400,
                error_message="Property BadField not found in type A_BadType",
            )
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview={"result_count": 1, "results": [{"GoodField": "OK"}]},
        )


class AlwaysFailingExecutor:
    def execute(self, compiled_request, attempt_number):
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=False,
            status_code=400,
            error_message="Still failing",
        )


class AlwaysPassingExecutor:
    def execute(self, compiled_request, attempt_number):
        entity_set = "A_Bad" if "A_Bad" in compiled_request.url else "A_Good"
        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview={"result_count": 1, "results": [{"EntitySet": entity_set}]},
        )


class StaticPresenter:
    def present(self, request, plan, data):
        return ResultPresentation(kind="text", title="查询结果", text="OK")


class StaticFailureDiagnoser:
    def diagnose(self, payload):
        from sap_odata_agent.domain.models import FailureDiagnosis

        return FailureDiagnosis(category="invalid_field", root_cause="failed after retries")


class StaticSchemaResearchAgent:
    def __init__(self):
        self.calls = 0

    def research(self, request, route_decision, schema_context, feedback_memories=None):
        self.calls += 1
        return {
            "available": True,
            "business_intent": "test intent",
            "recommended_filters": [],
            "semantic_risks": [],
            "planner_instructions": "test research",
        }

    @staticmethod
    def summarize(research):
        return {"available": research.get("available", False)}


class SemanticResultVerifier:
    def __init__(self):
        self.calls = 0

    def verify(self, request, plan, data, schema_research=None):
        self.calls += 1
        if plan.entity_set == "A_Bad":
            return {
                "passed": False,
                "issues": [
                    {
                        "code": "wrong_business_semantics",
                        "message": "The result does not prove the requested business condition.",
                        "blocking": True,
                    }
                ],
                "repair_hints": {"preferred_entity_set": "A_Good"},
            }
        return {"passed": True, "issues": [], "repair_hints": {}}


class UnusedOldComponent:
    def classify(self, *args, **kwargs):
        raise AssertionError("old query classifier should not be called")

    def extract(self, *args, **kwargs):
        raise AssertionError("old constraint extractor should not be called")


def _orchestrator(tmp_path: Path, *, repairer=None, executor=None, max_attempts=3, result_verifier=None):
    orch = AgentOrchestrator(
        retriever=None,
        planner=InitialPlanner(),
        validator=PassThroughValidator(),
        compiler=SimpleCompiler(),
        executor=executor or FailingThenPassingExecutor(),
        repair_engine=None,
        result_presenter=StaticPresenter(),
        case_repository=JsonlCaseRepository(str(tmp_path / "cases.jsonl")),
        api_catalog_provider=StaticCatalogProvider(),
        api_router=StaticRouter(),
        schema_context_provider=StaticSchemaContextProvider(),
        api_specific_planner=InitialPlanner(),
        plan_repairer=repairer or RepairPlanner(),
        failure_diagnoser=StaticFailureDiagnoser(),
        schema_research_agent=StaticSchemaResearchAgent(),
        result_verifier_agent=result_verifier,
        llm_planning_max_attempts=max_attempts,
        use_llm_first_pipeline=True,
    )
    orch.query_classifier = UnusedOldComponent()
    orch.constraint_extractor = UnusedOldComponent()
    return orch


def test_llm_first_pipeline_repairs_failed_execution_and_succeeds(tmp_path: Path) -> None:
    repairer = RepairPlanner()
    response = _orchestrator(tmp_path, repairer=repairer).run(AgentRequest(user_input="查询测试对象"))

    assert response.success is True
    assert response.plan.entity_set == "A_Good"
    assert len(response.attempts) == 2
    assert repairer.calls == 1


def test_llm_first_pipeline_limits_planning_attempts_to_three(tmp_path: Path) -> None:
    repairer = RepairPlanner(always_bad=True)
    response = _orchestrator(
        tmp_path,
        repairer=repairer,
        executor=AlwaysFailingExecutor(),
        max_attempts=3,
    ).run(AgentRequest(user_input="查询测试对象"))

    assert response.success is False
    assert len(response.attempts) == 3
    assert repairer.calls == 2
    assert response.final_message == "failed after retries"


def test_llm_first_pipeline_repairs_after_result_verifier_rejects_semantics(tmp_path: Path) -> None:
    repairer = RepairPlanner()
    result_verifier = SemanticResultVerifier()
    response = _orchestrator(
        tmp_path,
        repairer=repairer,
        executor=AlwaysPassingExecutor(),
        result_verifier=result_verifier,
    ).run(AgentRequest(user_input="查询业务语义不可靠的结果"))

    assert response.success is True
    assert response.plan.entity_set == "A_Good"
    assert len(response.attempts) == 2
    assert repairer.calls == 1
    assert result_verifier.calls == 2
