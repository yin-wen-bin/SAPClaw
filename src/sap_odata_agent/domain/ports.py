from __future__ import annotations

from typing import Any, Protocol

from sap_odata_agent.domain.models import (
    AgentRequest,
    CaseRecord,
    CompiledRequest,
    ExecutionAttempt,
    QueryPlan,
    ResultPresentation,
    RetrievedContext,
    ValidationIssue,
)


class KnowledgeRetriever(Protocol):
    def retrieve(self, query: str, top_k: int = 5) -> RetrievedContext:
        ...


class IntentPlanner(Protocol):
    def plan(self, request: AgentRequest, context: RetrievedContext) -> QueryPlan:
        ...


class PlanValidator(Protocol):
    def validate(self, plan: QueryPlan) -> list[ValidationIssue]:
        ...


class ODataCompiler(Protocol):
    def compile(self, plan: QueryPlan) -> CompiledRequest:
        ...


class SapExecutor(Protocol):
    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        ...


class SelfRepairEngine(Protocol):
    def repair(
        self,
        request: AgentRequest,
        context: RetrievedContext,
        previous_plan: QueryPlan,
        error_message: str,
    ) -> QueryPlan:
        ...


class ResultPresenter(Protocol):
    def present(self, request: AgentRequest, plan: QueryPlan, data: dict[str, object] | None) -> ResultPresentation:
        ...


class CaseRepository(Protocol):
    def save(self, record: CaseRecord) -> None:
        ...

    def list_recent(self, limit: int = 20, conversation_id: str | None = None) -> list[dict[str, Any]]:
        ...

    def get_by_case_id(self, case_id: str) -> dict[str, Any] | None:
        ...

    def update_feedback(
        self,
        case_id: str,
        status: str,
        comment: str = "",
        expected_result: str = "",
    ) -> dict[str, Any] | None:
        ...

    def find_latest_clarification(self, conversation_id: str) -> dict[str, Any] | None:
        ...

    def search_feedback(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        ...

    def save_feedback_memory(self, case_id: str, memory: dict[str, Any]) -> None:
        ...

    def search_feedback_memory(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        ...
