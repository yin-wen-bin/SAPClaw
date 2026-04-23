from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sap_odata_agent.domain.models import CandidatePlan, CardinalityPolicy, QueryConstraints, QueryShape


class CandidateRanker:
    def rank(
        self,
        constraints: QueryConstraints,
        entity_candidates: list[dict[str, Any]],
        path_candidates: list[dict[str, Any]],
    ) -> list[CandidatePlan]:
        ranked: list[CandidatePlan] = []
        for entity in entity_candidates:
            ranked.append(self._rank_entity_candidate(constraints, entity))
        for path in path_candidates:
            ranked.append(self._rank_path_candidate(constraints, path))
        ranked.sort(key=lambda item: (item.hard_constraints_passed, item.final_score), reverse=True)
        return ranked

    def to_debug_payload(self, candidates: list[CandidatePlan]) -> list[dict[str, Any]]:
        return [asdict(item) for item in candidates[:8]]

    def _rank_entity_candidate(self, constraints: QueryConstraints, entity: dict[str, Any]) -> CandidatePlan:
        entity_set = entity.get("entity_set") or entity.get("title") or ""
        available_fields = set(entity.get("available_fields", []) or [])
        hard_fail_reasons: list[str] = []
        constraint_fit = 0.0

        if constraints.target_object and not self._entity_matches_object(entity, constraints.target_object):
            hard_fail_reasons.append("target_object_mismatch")
        else:
            constraint_fit += 0.25

        if constraints.query_shape == QueryShape.NAME_CONTAINS_SEARCH and not self._has_name_field(available_fields):
            hard_fail_reasons.append("name_contains_requires_name_field")
        elif constraints.query_shape == QueryShape.NAME_CONTAINS_SEARCH:
            constraint_fit += 0.35

        if constraints.filter_concepts and not self._supports_filter_concepts(available_fields, constraints.filter_concepts):
            hard_fail_reasons.append("missing_filter_concept")
        elif constraints.filter_concepts:
            constraint_fit += 0.35

        if constraints.query_shape == QueryShape.SEARCH_BY_ATTRIBUTE and constraints.target_object and constraints.filter_concepts:
            hard_fail_reasons.append("attribute_search_requires_path")

        if constraints.target_field_concepts and self._supports_filter_concepts(available_fields, constraints.target_field_concepts):
            constraint_fit += 0.2

        if constraints.query_shape in {QueryShape.LIST_QUERY, QueryShape.SEARCH_BY_ATTRIBUTE} and constraints.cardinality == CardinalityPolicy.MANY:
            constraint_fit += 0.15

        semantic_match = float(entity.get("score", 0.0)) / 100.0
        path_cost = 1.0
        historical_success = 0.3
        ambiguity_penalty = 0.2 if "Text" in entity_set else 0.0
        final_score = (0.40 * constraint_fit) + (0.25 * semantic_match) + (0.15 * historical_success) + (0.10 * path_cost) - (0.10 * ambiguity_penalty)
        return CandidatePlan(
            candidate_id=entity_set,
            candidate_type="entity",
            entity_set=entity_set,
            target_entity_set=entity_set,
            hard_constraints_passed=not hard_fail_reasons,
            hard_fail_reasons=hard_fail_reasons,
            scores={
                "constraint_fit": round(constraint_fit, 4),
                "semantic_match": round(semantic_match, 4),
                "path_cost": round(path_cost, 4),
                "historical_success": round(historical_success, 4),
                "ambiguity_penalty": round(ambiguity_penalty, 4),
            },
            final_score=round(final_score, 4),
        )

    def _rank_path_candidate(self, constraints: QueryConstraints, path: dict[str, Any]) -> CandidatePlan:
        target_entity = path.get("target_entity_set", "")
        target_field = path.get("target_field", "")
        filter_fields = set(path.get("filter_fields", []) or [])
        result_fields = set(path.get("result_fields", []) or [])
        hard_fail_reasons: list[str] = []
        constraint_fit = 0.0

        if constraints.target_object and not self._path_matches_object(path, constraints.target_object):
            hard_fail_reasons.append("target_object_mismatch")
        else:
            constraint_fit += 0.2

        if constraints.filter_concepts and not any(concept in filter_fields for concept in constraints.filter_concepts):
            hard_fail_reasons.append("missing_filter_concept")
        elif constraints.filter_concepts:
            constraint_fit += 0.35

        if constraints.target_field_concepts:
            if target_field not in constraints.target_field_concepts and not any(
                concept in result_fields for concept in constraints.target_field_concepts
            ):
                hard_fail_reasons.append("target_field_mismatch")
            else:
                constraint_fit += 0.2
        elif constraints.query_shape in {QueryShape.SEARCH_BY_ATTRIBUTE, QueryShape.LIST_QUERY} and constraints.target_object:
            constraint_fit += 0.15

        if constraints.cardinality == CardinalityPolicy.MANY:
            if path.get("path_kind") == "direct_lookup":
                hard_fail_reasons.append("direct_lookup_not_suitable_for_list_query")
            else:
                constraint_fit += 0.15

        semantic_match = min(float(path.get("score", 0.0)) / 80.0, 1.0)
        step_count = len(path.get("steps", []) or [])
        path_cost = 1.0 if step_count <= 1 else max(0.3, 1.0 - ((step_count - 1) * 0.2))
        confidence = float(path.get("confidence", 0.0))
        historical_success = max(0.45, min(0.95, confidence))
        if path.get("path_kind") == "attribute_filter_list":
            historical_success = max(historical_success, 0.6)
        ambiguity_penalty = 0.1 if step_count > 2 else 0.0
        business_context_fit = self._business_context_fit(target_field, target_entity)
        final_score = (
            (0.40 * constraint_fit)
            + (0.25 * semantic_match)
            + (0.15 * historical_success)
            + (0.10 * path_cost)
            + business_context_fit
            - (0.10 * ambiguity_penalty)
        )
        return CandidatePlan(
            candidate_id=path.get("path_id", target_entity),
            candidate_type="path",
            entity_set=target_entity,
            path_id=path.get("path_id"),
            target_field=target_field,
            target_entity_set=target_entity,
            hard_constraints_passed=not hard_fail_reasons,
            hard_fail_reasons=hard_fail_reasons,
            scores={
                "constraint_fit": round(constraint_fit, 4),
                "semantic_match": round(semantic_match, 4),
                "path_cost": round(path_cost, 4),
                "historical_success": round(historical_success, 4),
                "ambiguity_penalty": round(ambiguity_penalty, 4),
                "business_context_fit": round(business_context_fit, 4),
            },
            final_score=round(final_score, 4),
            ambiguity_group=target_field or None,
        )

    @staticmethod
    def _business_context_fit(target_field: str, target_entity: str) -> float:
        return 0.0

    @staticmethod
    def _has_name_field(available_fields: set[str]) -> bool:
        return any("name" in field_name.lower() or "名称" in field_name for field_name in available_fields)

    @staticmethod
    def _supports_filter_concepts(available_fields: set[str], concepts: list[str]) -> bool:
        return any(concept in available_fields for concept in concepts)

    def _entity_matches_object(self, entity: dict[str, Any], target_object: str) -> bool:
        available_fields = set(entity.get("available_fields", []) or [])
        entity_set = entity.get("entity_set", "") or ""
        object_field = self._object_field_name(target_object)
        if self._entity_has_competing_primary_marker(entity_set, target_object):
            return False
        return bool(object_field and (object_field in available_fields or object_field in entity_set))

    def _path_matches_object(self, path: dict[str, Any], target_object: str) -> bool:
        normalized_target = target_object.replace("_", "").lower()
        anchor_object = str(path.get("anchor_object", "")).replace(" ", "").lower()
        return_object = str(path.get("return_object", "")).replace(" ", "").lower()
        object_field = self._object_field_name(target_object).replace(" ", "").lower()
        return anchor_object == object_field or return_object == object_field or anchor_object == normalized_target or return_object == normalized_target

    @staticmethod
    def _object_field_name(target_object: str) -> str:
        return {
            "supplier": "Supplier",
            "customer": "Customer",
            "business_partner": "BusinessPartner",
        }.get(target_object, "")

    @staticmethod
    def _entity_has_competing_primary_marker(entity_set: str, target_object: str) -> bool:
        normalized = (entity_set or "").replace("_", "").lower()
        markers = {
            "supplier": {"target": ("supplier",), "competing": ("customer", "cust")},
            "customer": {"target": ("customer", "cust"), "competing": ("supplier",)},
            "business_partner": {"target": ("businesspartner", "bp"), "competing": ()},
        }.get(target_object)
        if not markers:
            return False
        if any(marker in normalized for marker in markers["target"]):
            return False
        return any(marker in normalized for marker in markers["competing"])
