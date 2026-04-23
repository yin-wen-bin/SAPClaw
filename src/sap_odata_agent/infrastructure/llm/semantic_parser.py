from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from sap_odata_agent.domain.models import QueryConstraints, QueryShape
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner


class LlmSemanticParser:
    """Use the LLM to normalize user phrasing into a stable semantic frame."""

    def __init__(
        self,
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.enabled = enabled

    def parse(
        self,
        query: str,
        constraints: QueryConstraints,
        candidate_fields: list[dict[str, Any]],
        feedback_hints: list[dict[str, str]] | None = None,
        feedback_memories: list[dict[str, Any]] | None = None,
    ) -> tuple[QueryConstraints, dict[str, Any]]:
        if not self.enabled or self.llm_client is None:
            return constraints, {"enabled": False, "accepted": False, "reason": "llm_unavailable"}

        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(query, constraints, candidate_fields, feedback_hints, feedback_memories),
                max_tokens=900,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            return constraints, {"enabled": True, "accepted": False, "reason": f"client_error:{exc}"}

        merged = self._merge_constraints(constraints, parsed, candidate_fields)
        parsed["accepted"] = True
        return merged, parsed

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You normalize SAP business user requests into a structured semantic frame. "
            "Do not invent SAP fields. Prefer field names that appear in candidate_fields. "
            "Return one JSON object only."
        )

    @staticmethod
    def _user_prompt(
        query: str,
        constraints: QueryConstraints,
        candidate_fields: list[dict[str, Any]],
        feedback_hints: list[dict[str, str]] | None,
        feedback_memories: list[dict[str, Any]] | None,
    ) -> str:
        example = {
            "intent_type": "attribute_lookup",
            "target_object": "business object named by the user, if any",
            "target_fields": [
                {"field_name": "RequestedField", "user_phrase": "user wording for requested data", "confidence": 0.88}
            ],
            "filters": [
                {"field_name": "IdentifierOrFilterField", "operator": "eq", "value": "literal value from the query", "confidence": 0.95}
            ],
            "cardinality": "one",
            "name_match_mode": None,
            "boolean_intent": False,
            "needs_clarification": False,
            "clarification_question": "",
            "reason": "The request asks for one field constrained by one identifier or attribute value.",
        }
        payload = {
            "query": query,
            "current_constraints": {
                "query_shape": constraints.query_shape.value,
                "cardinality": constraints.cardinality.value,
                "target_object": constraints.target_object,
                "target_field_concepts": constraints.target_field_concepts,
                "filter_concepts": constraints.filter_concepts,
                "filter_values": constraints.filter_values,
                "name_match_mode": constraints.name_match_mode,
                "boolean_intent": constraints.boolean_intent,
            },
            "candidate_fields": [
                {
                    "entity_set": item.get("entity_set", ""),
                    "field_name": item.get("field_name", ""),
                    "label": item.get("label", ""),
                    "description": item.get("description", ""),
                    "business_aliases": item.get("business_aliases", [])[:8],
                }
                for item in candidate_fields[:80]
            ],
            "feedback_hints": feedback_hints or [],
            "feedback_memories": feedback_memories or [],
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Output rules:\n"
            "- Use target_fields for fields the user wants returned.\n"
            "- Use filters for fields that constrain the result.\n"
            "- If a field is likely but not in candidate_fields, include the phrase but leave field_name empty.\n"
            "- Preserve identifiers and literal values exactly.\n"
            "- Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _merge_constraints(
        constraints: QueryConstraints,
        parsed: dict[str, Any],
        candidate_fields: list[dict[str, Any]],
    ) -> QueryConstraints:
        known_fields = {
            str(item.get("field_name", ""))
            for item in candidate_fields
            if str(item.get("field_name", "")).strip()
        }

        target_fields = [
            str(item.get("field_name", "")).strip()
            for item in parsed.get("target_fields", [])
            if isinstance(item, dict)
        ]
        target_fields = [field for field in target_fields if field and (not known_fields or field in known_fields)]

        filter_fields = [
            str(item.get("field_name", "")).strip()
            for item in parsed.get("filters", [])
            if isinstance(item, dict)
        ]
        filter_fields = [field for field in filter_fields if field and (not known_fields or field in known_fields)]

        filter_values = [
            str(item.get("value", "")).strip()
            for item in parsed.get("filters", [])
            if isinstance(item, dict) and str(item.get("value", "")).strip()
        ]

        target_object = str(parsed.get("target_object") or "").strip()
        if not target_object:
            target_object = constraints.target_object

        name_match_mode = parsed.get("name_match_mode")
        if name_match_mode not in {"contains", "eq", None, ""}:
            name_match_mode = constraints.name_match_mode

        return replace(
            constraints,
            target_object=target_object,
            target_field_concepts=target_fields or constraints.target_field_concepts,
            filter_concepts=filter_fields or constraints.filter_concepts,
            filter_values=list(dict.fromkeys([*constraints.filter_values, *filter_values])),
            name_match_mode=(name_match_mode or constraints.name_match_mode),
            boolean_intent=bool(parsed.get("boolean_intent", constraints.boolean_intent)),
            query_shape=QueryShape(parsed.get("intent_type", constraints.query_shape.value))
            if parsed.get("intent_type") in QueryShape._value2member_map_
            else constraints.query_shape,
        )
