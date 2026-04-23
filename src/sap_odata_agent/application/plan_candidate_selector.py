from __future__ import annotations

from sap_odata_agent.domain.models import PlanCandidate


class PlanCandidateSelector:
    """Choose among LLM/planner candidates using schema feasibility first."""

    def select(self, candidates: list[PlanCandidate]) -> PlanCandidate | None:
        if not candidates:
            return None
        ranked = sorted(candidates, key=self._score, reverse=True)
        return ranked[0]

    @staticmethod
    def _score(candidate: PlanCandidate) -> tuple[float, float, float]:
        feasibility_score = 1.0 if candidate.feasibility is not None and candidate.feasibility.passed else 0.0
        if candidate.feasibility is None:
            feasibility_score = 0.5
        path_score = 1.0
        if candidate.plan.plan_kind in {"lookup", "multi_step"}:
            path_score = max(0.2, 1.0 - (len(candidate.plan.steps or []) * 0.15))
        return (feasibility_score, candidate.llm_confidence, path_score)
