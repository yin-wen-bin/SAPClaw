from __future__ import annotations

import re
from collections.abc import Iterable

from sap_odata_agent.domain.models import (
    AgentRequest,
    CriticFinding,
    GuardrailDecision,
    QueryPlan,
    RetrievedContext,
)


class DiagnosticCritic:
    """Cross-check recall, extracted constraints, and the final plan."""

    ANCHORED_IDENTIFIER_PATTERN = r"([A-Za-z0-9][A-Za-z0-9_-]{1,})"
    OBJECT_FIELD_MAP = {
        "supplier": "Supplier",
        "customer": "Customer",
        "business_partner": "BusinessPartner",
    }
    OBJECT_ALIASES = {
        "supplier": {"\u4f9b\u5e94\u5546", "supplier", "vendor"},
        "customer": {"\u5ba2\u6237", "customer"},
        "business_partner": {"\u4e1a\u52a1\u4f19\u4f34", "business partner", "bp"},
    }

    def review(
        self,
        request: AgentRequest,
        context: RetrievedContext | None,
        plan: QueryPlan,
        *,
        guardrail_decision: GuardrailDecision | None = None,
        critic_findings: Iterable[CriticFinding] | None = None,
    ) -> list[CriticFinding]:
        constraints = request.constraints
        if constraints is None:
            return []

        findings: list[CriticFinding] = []
        query = request.resolved_user_input or request.user_input or ""
        lowered = query.lower()
        answer_text = self._answer_text(lowered, query, constraints.target_object)
        target_fields = set(constraints.target_field_concepts or [])
        constraint_filter_fields = set(constraints.filter_concepts or [])
        selected_fields = self._selected_fields(plan)
        blocking_already = bool(
            (guardrail_decision is not None and not guardrail_decision.accepted)
            or any(item.blocking for item in (critic_findings or []))
        )

        anchor_finding = self._review_anchor_field(
            query,
            answer_text,
            constraints.target_object,
            target_fields,
            selected_fields,
            blocking_already,
        )
        if anchor_finding is not None:
            findings.append(anchor_finding)

        recalled_answer_fields = self._recalled_answer_fields(context, answer_text)
        dropped_fields = sorted(
            field_name
            for field_name in recalled_answer_fields
            if field_name not in target_fields
            and field_name not in constraint_filter_fields
            and field_name not in selected_fields
            and not self._is_anchor_identity(field_name, constraints.target_object, query, answer_text)
        )
        if dropped_fields:
            findings.append(
                CriticFinding(
                    code="recalled_answer_field_not_in_constraints",
                    message=(
                        "Metadata recall found likely answer field(s), but constraint extraction did not keep them: "
                        + ", ".join(dropped_fields)
                    ),
                    severity="error" if blocking_already else "warning",
                    blocking=blocking_already,
                )
            )

        missing_required = sorted(target_fields - selected_fields)
        candidate_field_names = self._candidate_field_names(context)
        available_elsewhere = [field_name for field_name in missing_required if field_name in candidate_field_names]
        if available_elsewhere:
            findings.append(
                CriticFinding(
                    code="required_field_available_but_not_selected",
                    message=(
                        "Required target field(s) were recalled from metadata but were not selected by the final plan: "
                        + ", ".join(available_elsewhere)
                    ),
                    severity="warning",
                    blocking=False,
                )
            )

        return findings

    def _review_anchor_field(
        self,
        query: str,
        answer_text: str,
        target_object: str | None,
        target_fields: set[str],
        selected_fields: set[str],
        blocking_already: bool,
    ) -> CriticFinding | None:
        identity_field = self.OBJECT_FIELD_MAP.get(target_object or "")
        if not identity_field or identity_field not in target_fields:
            return None
        if not self._is_anchor_identity(identity_field, target_object, query, answer_text):
            return None
        return CriticFinding(
            code="anchor_field_misclassified_as_target",
            message=(
                f"`{identity_field}` appears to be the identifier anchor in the user question, "
                "not an answer field. Re-check constraint extraction before judging the plan."
            ),
            severity="error" if blocking_already or identity_field not in selected_fields else "warning",
            blocking=blocking_already or identity_field not in selected_fields,
        )

    def _is_anchor_identity(
        self,
        field_name: str,
        target_object: str | None,
        query: str,
        answer_text: str,
    ) -> bool:
        identity_field = self.OBJECT_FIELD_MAP.get(target_object or "")
        if field_name != identity_field:
            return False
        object_aliases = self.OBJECT_ALIASES.get(target_object or "", set())
        for alias in object_aliases:
            lowered_alias = alias.lower()
            if lowered_alias in answer_text:
                return False
            if re.search(rf"{re.escape(alias)}\s*{self.ANCHORED_IDENTIFIER_PATTERN}", query or "", flags=re.IGNORECASE):
                return True
        return False

    @staticmethod
    def _selected_fields(plan: QueryPlan) -> set[str]:
        fields = set(plan.select_fields or [])
        fields.update(plan.response_summary_fields or [])
        for step in plan.steps or []:
            fields.update(step.select_fields or [])
            fields.update(step.response_summary_fields or [])
        return fields

    @staticmethod
    def _recalled_answer_fields(context: RetrievedContext | None, answer_text: str) -> set[str]:
        matches: list[tuple[str, str]] = []
        if context is None:
            return set()
        for document in context.documents or []:
            metadata = document.metadata or {}
            field_name = str(metadata.get("field_name", "") or "")
            if not field_name:
                continue
            if DiagnosticCritic._field_conflicts_with_answer_object(field_name, answer_text):
                continue
            matched_alias = str(metadata.get("matched_alias", "") or "")
            aliases = [
                matched_alias,
                str(metadata.get("label", "") or ""),
                str(metadata.get("description", "") or ""),
                *[str(alias or "") for alias in metadata.get("business_aliases", []) or []],
            ]
            if document.source != "field-exact":
                continue
            for alias in aliases:
                normalized_alias = DiagnosticCritic._normalize(alias)
                if normalized_alias and normalized_alias in answer_text:
                    matches.append((field_name, normalized_alias))
                    break
        return {
            field_name
            for field_name, alias in matches
            if not DiagnosticCritic._is_shadowed_answer_alias(field_name, alias, matches)
        }

    @staticmethod
    def _is_shadowed_answer_alias(field_name: str, alias: str, matches: list[tuple[str, str]]) -> bool:
        return any(
            other_field != field_name
            and alias != other_alias
            and alias in other_alias
            for other_field, other_alias in matches
        )

    @staticmethod
    def _field_conflicts_with_answer_object(field_name: str, answer_text: str) -> bool:
        answer_objects = {
            object_name
            for object_name, aliases in DiagnosticCritic.OBJECT_ALIASES.items()
            if any(alias.lower() in answer_text for alias in aliases)
        }
        if not answer_objects:
            return False
        for object_name, identity_field in DiagnosticCritic.OBJECT_FIELD_MAP.items():
            if field_name.startswith(identity_field) and object_name not in answer_objects:
                return True
        return False

    @staticmethod
    def _candidate_field_names(context: RetrievedContext | None) -> set[str]:
        if context is None:
            return set()
        return {
            str((document.metadata or {}).get("field_name", "") or "")
            for document in context.documents or []
            if (document.metadata or {}).get("field_name")
        }

    @staticmethod
    def _answer_text(lowered: str, query: str, target_object: str | None) -> str:
        marker = "\u7684"
        if marker in lowered:
            return lowered.split(marker, 1)[1]
        for alias in sorted(DiagnosticCritic.OBJECT_ALIASES.get(target_object or "", set()), key=len, reverse=True):
            match = re.search(
                rf"{re.escape(alias)}\s*{DiagnosticCritic.ANCHORED_IDENTIFIER_PATTERN}",
                query or "",
                flags=re.IGNORECASE,
            )
            if match:
                return (query or "")[match.end() :].lower()
        return lowered

    @staticmethod
    def _normalize(text: str) -> str:
        return str(text or "").strip().lower()
