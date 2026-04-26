from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from sap_odata_agent.domain.models import (
    AgentRequest,
    ExecutionStep,
    FilterCondition,
    QueryPlan,
    RetrievedContext,
    RetrievedDocument,
    StepBinding,
)
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner


class LlmDynamicPathPlanner:
    """LLM-first planner for entity, field, and multi-hop path selection.

    The program supplies a bounded schema context and validates that the LLM
    only references indexed entities/fields. It does not fall back to the
    deterministic local planner when the LLM is unavailable or returns an
    unusable plan.
    """

    def __init__(
        self,
        index_root: str = "data/index",
        service_name: str = "API_BUSINESS_PARTNER",
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
        max_candidate_fields: int = 180,
        max_candidate_entities: int = 28,
    ) -> None:
        self.loader = LocalIndexLoader(index_root=index_root)
        self.service_name = service_name
        self.llm_client = llm_client
        self.enabled = enabled
        self.max_candidate_fields = max_candidate_fields
        self.max_candidate_entities = max_candidate_entities

    def plan(self, request: AgentRequest, context: RetrievedContext) -> QueryPlan:
        if not self.enabled or self.llm_client is None:
            return self._unavailable_plan("llm_unavailable")
        try:
            snapshot = self.loader.load(self.service_name)
        except FileNotFoundError:
            return self._unavailable_plan("index_unavailable")

        schema_context = self._build_schema_context(request, context, snapshot)
        if not schema_context["entities"] and not schema_context["candidate_fields"]:
            return self._unavailable_plan("schema_context_empty")

        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(request, schema_context),
                max_tokens=2200,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            return self._invalid_plan(f"llm_error:{exc}", schema_context)

        materialized = self._materialize_plan(parsed, snapshot, schema_context)
        if materialized is None:
            return self._invalid_plan("llm_plan_not_materializable", schema_context, parsed)
        return materialized

    def _build_schema_context(self, request: AgentRequest, context: RetrievedContext, snapshot) -> dict[str, Any]:
        query = request.resolved_user_input or request.user_input
        constraints = request.constraints
        schema_rerank = request.schema_rerank or {}
        required_field_names = set()
        if constraints is not None:
            required_field_names.update(constraints.target_field_concepts or [])
            required_field_names.update(constraints.filter_concepts or [])
        required_field_names.update(str(item) for item in schema_rerank.get("answer_fields", []) if str(item).strip())
        required_field_names.update(str(item) for item in schema_rerank.get("filter_fields", []) if str(item).strip())

        doc_entities = self._entity_sets_from_documents(context.documents if context else [])
        doc_fields = self._field_refs_from_documents(context.documents if context else [])
        ranked_fields = [
            item
            for item in schema_rerank.get("ranked_fields", [])
            if isinstance(item, dict) and item.get("entity_set") and item.get("field_name")
        ]

        scored_fields: list[tuple[float, dict[str, Any]]] = []
        for field in snapshot.fields:
            score = self._score_field(query, field, required_field_names)
            key = (str(field.get("entity_set", "")), str(field.get("field_name", "")))
            if key in doc_fields:
                score += min(doc_fields[key], 20.0) * 0.8
            if str(field.get("field_name", "")) in required_field_names:
                score += 30.0
            scored_fields.append((score, field))

        ranked_by_llm_key = {
            (str(item.get("entity_set", "")), str(item.get("field_name", ""))): index
            for index, item in enumerate(ranked_fields)
        }
        boosted: list[tuple[float, dict[str, Any]]] = []
        for score, field in scored_fields:
            key = (str(field.get("entity_set", "")), str(field.get("field_name", "")))
            if key in ranked_by_llm_key:
                score += max(10.0, 40.0 - ranked_by_llm_key[key])
            boosted.append((score, field))
        boosted.sort(key=lambda item: item[0], reverse=True)

        candidate_fields = []
        seen_fields: set[tuple[str, str]] = set()
        for score, field in boosted:
            entity_set = str(field.get("entity_set", ""))
            field_name = str(field.get("field_name", ""))
            if not entity_set or not field_name:
                continue
            if score <= 0 and entity_set not in doc_entities and field_name not in required_field_names:
                continue
            key = (entity_set, field_name)
            if key in seen_fields:
                continue
            seen_fields.add(key)
            candidate_fields.append(self._field_payload(field, score))
            if len(candidate_fields) >= self.max_candidate_fields:
                break

        candidate_entities = self._expand_candidate_entities(snapshot, candidate_fields, doc_entities)
        entities = [
            self._entity_payload(snapshot, entity_set, candidate_fields)
            for entity_set in candidate_entities[: self.max_candidate_entities]
        ]
        entities = [item for item in entities if item]
        entity_set_scope = {item["entity_set"] for item in entities}

        return {
            "service_name": self.service_name,
            "entities": entities,
            "candidate_fields": candidate_fields,
            "join_hints": self._build_join_hints(snapshot, entity_set_scope),
            "relations": self._build_relation_hints(snapshot, entity_set_scope),
            "retrieved_documents": self._document_payload(context.documents if context else []),
        }

    def _expand_candidate_entities(
        self,
        snapshot,
        candidate_fields: list[dict[str, Any]],
        document_entities: set[str],
    ) -> list[str]:
        ordered: list[str] = []

        def add(entity_set: str) -> None:
            if entity_set and entity_set not in ordered:
                ordered.append(entity_set)

        for entity_set in document_entities:
            add(entity_set)
        for field in candidate_fields:
            add(str(field.get("entity_set", "")))

        fields_by_entity: dict[str, set[str]] = {}
        for field in snapshot.fields:
            fields_by_entity.setdefault(str(field.get("entity_set", "")), set()).add(str(field.get("field_name", "")))

        for entity_set in list(ordered):
            entity = self._lookup_entity(snapshot, entity_set)
            if not entity:
                continue
            bridge_fields = set(entity.get("key_fields", []) or [])
            bridge_fields.update(entity.get("default_select_fields", []) or [])
            bridge_fields.update(fields_by_entity.get(entity_set, set()) & {"AddressID", "BusinessPartner"})
            for other_entity, other_fields in fields_by_entity.items():
                if other_entity in ordered:
                    continue
                if bridge_fields & other_fields:
                    add(other_entity)
                if len(ordered) >= self.max_candidate_entities:
                    break
            if len(ordered) >= self.max_candidate_entities:
                break
        return ordered

    def _materialize_plan(
        self,
        parsed: dict[str, Any],
        snapshot,
        schema_context: dict[str, Any],
    ) -> QueryPlan | None:
        plan_kind = str(parsed.get("plan_kind") or "direct").lower()
        if plan_kind in {"clarification", "clarify"} or bool(parsed.get("needs_clarification", False)):
            return QueryPlan(
                service_name=self.service_name,
                entity_set=self._first_entity(schema_context),
                needs_clarification=True,
                clarification_question=str(parsed.get("clarification_question") or "Please clarify the query scope."),
                clarification_options=[
                    str(item)
                    for item in parsed.get("clarification_options", [])
                    if isinstance(item, str) and item.strip()
                ][:4],
                response_directive=str(parsed.get("response_directive") or ""),
                rationale=str(parsed.get("rationale") or "LLM requested clarification."),
                planner_diagnostics={"planner_winner": "llm", "llm_dynamic_path_planner": {"accepted": True, "raw": parsed}},
            )
        if plan_kind in {"no_feasible_plan", "fail", "failure"}:
            return self._invalid_plan(str(parsed.get("failure_reason") or "llm_reported_no_feasible_plan"), schema_context, parsed)

        raw_steps = parsed.get("steps", [])
        has_explicit_steps = isinstance(raw_steps, list) and bool(raw_steps)
        if plan_kind in {"lookup", "multi_step"} or has_explicit_steps:
            steps = self._materialize_steps(raw_steps, snapshot)
            if not steps:
                return None
            final_step = steps[-1]
            target_entity_set = str(parsed.get("target_entity_set") or final_step.entity_set)
            target_entity = self._lookup_entity(snapshot, target_entity_set)
            if target_entity is None:
                target_entity_set = final_step.entity_set
                target_entity = self._lookup_entity(snapshot, target_entity_set)
            if target_entity is None:
                return None
            target_field = str(parsed.get("target_field") or "") or None
            return QueryPlan(
                service_name=str(target_entity.get("service_name") or self.service_name),
                entity_set=target_entity_set,
                http_method=str(parsed.get("http_method") or "GET").upper(),
                select_fields=final_step.select_fields,
                response_summary_fields=self._summary_fields(
                    parsed.get("response_summary_fields"),
                    final_step.select_fields,
                    target_field,
                ),
                filters=steps[0].filters,
                top=final_step.top,
                requires_confirmation=bool(parsed.get("requires_confirmation", False)),
                response_directive=self._response_directive(parsed),
                rationale=str(parsed.get("rationale") or "LLM selected a dynamic multi-step OData path."),
                planner_diagnostics={
                    "planner_winner": "llm",
                    "llm_dynamic_path_planner": {
                        "accepted": True,
                        "raw": parsed,
                        "schema_context": self._compact_schema_context(schema_context),
                    },
                },
                plan_kind="multi_step" if len(steps) > 1 else "lookup",
                anchor_object=str(parsed.get("anchor_object") or "") or None,
                anchor_value=str(parsed.get("anchor_value") or "") or None,
                target_field=target_field,
                target_entity_set=target_entity_set,
                path_id=str(parsed.get("path_id") or "llm_dynamic_path"),
                steps=steps,
            )

        entity_set = str(parsed.get("entity_set") or "")
        entity = self._lookup_entity(snapshot, entity_set)
        if entity is None:
            return None
        field_map = self._field_map(snapshot, entity_set)
        select_fields = self._valid_fields(parsed.get("select_fields", []), field_map)
        if not select_fields:
            select_fields = self._default_fields(entity, field_map)
        filters = self._materialize_filters(parsed.get("filters", []), field_map)
        target_field = str(parsed.get("target_field") or "") or None
        return QueryPlan(
            service_name=str(entity.get("service_name") or self.service_name),
            entity_set=entity_set,
            http_method=str(parsed.get("http_method") or "GET").upper(),
            select_fields=select_fields,
            response_summary_fields=self._summary_fields(parsed.get("response_summary_fields"), select_fields, target_field),
            filters=filters,
            order_by=[str(item) for item in parsed.get("order_by", []) if str(item) in field_map],
            top=self._parse_top(parsed.get("top"), default=50 if self._presentation_kind(parsed) == "table" else 20),
            requires_confirmation=bool(parsed.get("requires_confirmation", False)),
            response_directive=self._response_directive(parsed),
            rationale=str(parsed.get("rationale") or "LLM selected a direct OData plan."),
            planner_diagnostics={
                "planner_winner": "llm",
                "llm_dynamic_path_planner": {
                    "accepted": True,
                    "raw": parsed,
                    "schema_context": self._compact_schema_context(schema_context),
                },
            },
            plan_kind="direct",
            target_field=target_field,
            target_entity_set=entity_set,
        )

    def _materialize_steps(self, raw_steps: Any, snapshot) -> list[ExecutionStep]:
        steps: list[ExecutionStep] = []
        raw_items = raw_steps if isinstance(raw_steps, list) else []
        for index, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                continue
            entity_set = str(item.get("entity_set") or "")
            entity = self._lookup_entity(snapshot, entity_set)
            if entity is None:
                continue
            field_map = self._field_map(snapshot, entity_set)
            filters = self._materialize_filters(item.get("filters", []), field_map)
            bindings = self._materialize_bindings(item, field_map)
            if not bindings and steps:
                shorthand_binding = self._materialize_shorthand_binding(item, field_map, steps[-1])
                if shorthand_binding is not None:
                    bindings.append(shorthand_binding)
            select_fields = self._valid_fields(item.get("select_fields", []), field_map)
            for binding in bindings:
                if binding.source_step_id and binding.source_field:
                    source_step = next((step for step in steps if step.step_id == binding.source_step_id), None)
                    if source_step is not None and binding.source_field not in source_step.select_fields:
                        source_step.select_fields.append(binding.source_field)
                        source_step.response_summary_fields = source_step.response_summary_fields or source_step.select_fields[:4]
                if binding.field in field_map and binding.field not in select_fields:
                    select_fields.append(binding.field)
            for condition in filters:
                if condition.field not in select_fields:
                    select_fields.append(condition.field)
            if not select_fields:
                select_fields = self._default_fields(entity, field_map)
            step_id = str(item.get("step_id") or f"step_{index}")
            steps.append(
                ExecutionStep(
                    step_id=step_id,
                    entity_set=entity_set,
                    http_method=str(item.get("http_method") or "GET").upper(),
                    select_fields=select_fields,
                    response_summary_fields=self._summary_fields(
                        item.get("response_summary_fields"),
                        select_fields,
                        str(item.get("target_field") or "") or None,
                    ),
                    filters=filters,
                    filter_from_previous=bindings,
                    order_by=[str(value) for value in item.get("order_by", []) if str(value) in field_map],
                    top=self._parse_top(item.get("top"), default=50),
                    rationale=str(item.get("rationale") or ""),
                )
            )
        return steps

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are an SAP OData planning engine. Decide the SAP entity set, fields, filters, "
            "multi-hop path, and result presentation shape from the user's question and the provided schema. "
            "Use only schema_context entities, fields, join_hints, and relations. Return one JSON object only."
        )

    @staticmethod
    def _user_prompt(request: AgentRequest, schema_context: dict[str, Any]) -> str:
        example = {
            "plan_kind": "direct | multi_step | clarification | no_feasible_plan",
            "entity_set": "Final entity set for direct plans",
            "http_method": "GET",
            "select_fields": ["Fields to retrieve from the final entity"],
            "response_summary_fields": ["Fields most relevant for answer rendering"],
            "filters": [{"field": "FilterField", "operator": "eq|contains", "value": "literal from user"}],
            "order_by": [],
            "top": 50,
            "target_entity_set": "Final answer entity set",
            "target_field": "Primary answer field if any",
            "anchor_object": "The object being filtered, if any",
            "anchor_value": "The literal identifier or attribute value from the user",
            "steps": [
                {
                    "step_id": "find_source",
                    "entity_set": "SourceEntity",
                    "select_fields": ["JoinField", "FilterField"],
                    "filters": [{"field": "FilterField", "operator": "eq", "value": "literal"}],
                    "top": 50,
                },
                {
                    "step_id": "resolve_target",
                    "entity_set": "TargetEntity",
                    "select_fields": ["JoinField", "AnswerField"],
                    "filter_from_previous": [
                        {"field": "JoinField", "source_step_id": "find_source", "source_field": "JoinField"}
                    ],
                    "top": 50,
                },
            ],
            "presentation": {
                "kind": "text | table",
                "reason": "Use text for a single fact, table for lists/comparisons.",
            },
            "response_directive": "Tell the result presenter how to answer the user.",
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "failure_reason": "",
            "rationale": "Explain the schema evidence and chosen path.",
        }
        payload = {
            "user_input": request.resolved_user_input or request.user_input,
            "query_shape": request.query_shape.value,
            "cardinality_policy": request.cardinality_policy.value,
            "constraints_as_weak_hints": LlmDynamicPathPlanner._constraints_payload(request),
            "semantic_frame_as_weak_hint": request.semantic_frame,
            "schema_rerank_as_weak_hint": request.schema_rerank,
            "feedback_hints": request.feedback_hints,
            "feedback_memories": request.feedback_memories,
            "schema_context": schema_context,
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Planning rules:\n"
            "1. Treat local constraints and schema_rerank as weak hints. The user's wording and schema labels/descriptions win.\n"
            "2. Preserve all literal filter values exactly, including emails, punctuation, spaces, and leading zeros.\n"
            "3. If a requested answer field and filter field are on different entities, build a multi_step plan using join_hints or shared fields.\n"
            "4. Every filter field must be filterable unless no filterable alternative exists in schema_context.\n"
            "5. Select all fields needed for bindings and final answer rendering.\n"
            "6. Choose presentation.kind: text for one factual answer, table for lists or multiple rows.\n"
            "7. Use schema_context.schema_research when present as the primary business-semantic analysis.\n"
            "8. Distinguish requirement/expected flags from completion/open status fields; do not treat similarly named fields as equivalent.\n"
            "9. If the schema context is insufficient, return no_feasible_plan instead of inventing fields.\n\n"
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    def _unavailable_plan(self, reason: str) -> QueryPlan:
        return QueryPlan(
            service_name=self.service_name,
            entity_set="UNKNOWN_ENTITY",
            rationale=f"LLM-first planner could not create a plan: {reason}.",
            planner_diagnostics={
                "planner_winner": "none",
                "llm_dynamic_path_planner": {"accepted": False, "reason": reason},
            },
        )

    @staticmethod
    def _constraints_payload(request: AgentRequest) -> dict[str, Any] | None:
        constraints = request.constraints
        if constraints is None:
            return None
        return {
            "query_shape": constraints.query_shape.value,
            "cardinality": constraints.cardinality.value,
            "target_object": constraints.target_object,
            "target_field_concepts": constraints.target_field_concepts,
            "filter_concepts": constraints.filter_concepts,
            "filter_values": constraints.filter_values,
            "requested_operation": constraints.requested_operation,
            "name_match_mode": constraints.name_match_mode,
            "boolean_intent": constraints.boolean_intent,
        }

    def _invalid_plan(
        self,
        reason: str,
        schema_context: dict[str, Any],
        parsed: dict[str, Any] | None = None,
    ) -> QueryPlan:
        return QueryPlan(
            service_name=self.service_name,
            entity_set="UNKNOWN_ENTITY",
            rationale=f"LLM-first planner returned no executable plan: {reason}.",
            planner_diagnostics={
                "planner_winner": "none",
                "llm_dynamic_path_planner": {
                    "accepted": False,
                    "reason": reason,
                    "raw": parsed or {},
                    "schema_context": self._compact_schema_context(schema_context),
                },
            },
        )

    @staticmethod
    def _score_field(query: str, field: dict[str, Any], required_field_names: set[str]) -> float:
        normalized_query = LlmDynamicPathPlanner._normalize(query)
        query_tokens = set(LlmDynamicPathPlanner._tokens(normalized_query))
        field_name = str(field.get("field_name", "") or "")
        aliases = [
            field_name,
            LlmDynamicPathPlanner._split_camel(field_name),
            str(field.get("entity_set", "") or ""),
            str(field.get("label", "") or ""),
            str(field.get("description", "") or ""),
            *[str(item or "") for item in field.get("business_aliases", []) or []],
        ]
        score = 0.0
        for alias in aliases:
            normalized_alias = LlmDynamicPathPlanner._normalize(alias)
            if not normalized_alias:
                continue
            compact_alias = normalized_alias.replace(" ", "")
            compact_query = normalized_query.replace(" ", "")
            if normalized_alias in normalized_query or compact_alias in compact_query:
                score += 24.0
            alias_tokens = set(LlmDynamicPathPlanner._tokens(normalized_alias))
            score += len(query_tokens & alias_tokens) * 5.0
            for token in query_tokens:
                best = max((SequenceMatcher(None, token, alias_token).ratio() for alias_token in alias_tokens), default=0.0)
                if best >= 0.82:
                    score += best * 3.0
        if field_name in required_field_names:
            score += 20.0
        return score

    @staticmethod
    def _field_payload(field: dict[str, Any], score: float) -> dict[str, Any]:
        return {
            "entity_set": field.get("entity_set", ""),
            "field_name": field.get("field_name", ""),
            "label": field.get("label", ""),
            "description": field.get("description", "") or field.get("quickinfo", ""),
            "business_aliases": field.get("business_aliases", [])[:8],
            "data_type": field.get("data_type", ""),
            "filterable": field.get("filterable", False),
            "score": round(score, 3),
        }

    def _entity_payload(self, snapshot, entity_set: str, candidate_fields: list[dict[str, Any]]) -> dict[str, Any]:
        entity = self._lookup_entity(snapshot, entity_set)
        if not entity:
            return {}
        candidate_field_names = {
            str(field.get("field_name", ""))
            for field in candidate_fields
            if field.get("entity_set") == entity_set
        }
        fields = []
        for field in self._get_entity_fields(snapshot, entity_set):
            field_name = str(field.get("field_name", ""))
            if (
                field_name in candidate_field_names
                or field_name in set(entity.get("key_fields", []) or [])
                or field_name in set(entity.get("default_select_fields", []) or [])
            ):
                fields.append(self._field_payload(field, 0.0))
            if len(fields) >= 64:
                break
        return {
            "entity_set": entity_set,
            "description": entity.get("description", ""),
            "entity_type": entity.get("entity_type", ""),
            "key_fields": entity.get("key_fields", []),
            "default_select_fields": entity.get("default_select_fields", []),
            "supports_filter": entity.get("supports_filter", True),
            "supported_methods": entity.get("supported_methods", ["GET"]),
            "fields": fields,
        }

    @staticmethod
    def _build_join_hints(snapshot, entity_set_scope: set[str]) -> list[dict[str, Any]]:
        by_field: dict[str, list[str]] = {}
        for field in snapshot.fields:
            entity_set = str(field.get("entity_set", ""))
            field_name = str(field.get("field_name", ""))
            if not entity_set or not field_name:
                continue
            if entity_set_scope and entity_set not in entity_set_scope:
                continue
            by_field.setdefault(field_name, []).append(entity_set)
        hints = []
        for field_name, entities in by_field.items():
            unique_entities = list(dict.fromkeys(entities))
            if len(unique_entities) < 2:
                continue
            hints.append({"field_name": field_name, "entity_sets": unique_entities[:12]})
        hints.sort(key=lambda item: (-len(item["entity_sets"]), item["field_name"]))
        return hints[:80]

    @staticmethod
    def _build_relation_hints(snapshot, entity_set_scope: set[str]) -> list[dict[str, Any]]:
        hints = []
        for relation in [*(snapshot.entity_graph or []), *(snapshot.relations or [])]:
            from_entity = str(relation.get("from_entity_set", ""))
            to_entity = str(relation.get("to_entity_set", ""))
            if entity_set_scope and from_entity not in entity_set_scope and to_entity not in entity_set_scope:
                continue
            hints.append(
                {
                    "from_entity_set": from_entity,
                    "to_entity_set": to_entity,
                    "from_field": relation.get("from_field", ""),
                    "to_field": relation.get("to_field", ""),
                    "navigation_name": relation.get("navigation_name", ""),
                    "description": relation.get("description", ""),
                    "confidence": relation.get("confidence", ""),
                }
            )
        return hints[:80]

    @staticmethod
    def _document_payload(documents: list[RetrievedDocument]) -> list[dict[str, Any]]:
        return [
            {
                "source": document.source,
                "title": document.title,
                "score": document.score,
                "metadata": {
                    "entity_set": (document.metadata or {}).get("entity_set", ""),
                    "field_name": (document.metadata or {}).get("field_name", ""),
                    "path_id": (document.metadata or {}).get("path_id", ""),
                },
            }
            for document in documents[:16]
        ]

    @staticmethod
    def _entity_sets_from_documents(documents: list[RetrievedDocument]) -> set[str]:
        results: set[str] = set()
        for document in documents:
            metadata = document.metadata or {}
            entity_set = str(metadata.get("mapped_entity_set") or metadata.get("entity_set") or "")
            if not entity_set and "." in document.title:
                entity_set = document.title.split(".", 1)[0]
            if entity_set:
                results.add(entity_set)
        return results

    @staticmethod
    def _field_refs_from_documents(documents: list[RetrievedDocument]) -> dict[tuple[str, str], float]:
        results: dict[tuple[str, str], float] = {}
        for document in documents:
            metadata = document.metadata or {}
            entity_set = str(metadata.get("entity_set") or "")
            field_name = str(metadata.get("field_name") or "")
            if entity_set and field_name:
                results[(entity_set, field_name)] = max(results.get((entity_set, field_name), 0.0), float(document.score or 0.0))
        return results

    @staticmethod
    def _materialize_filters(raw_filters: Any, field_map: dict[str, dict[str, Any]]) -> list[FilterCondition]:
        filters: list[FilterCondition] = []
        for item in raw_filters if isinstance(raw_filters, list) else []:
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("field") or "")
            value = item.get("value")
            if field_name not in field_map or value in (None, ""):
                continue
            operator = str(item.get("operator") or "eq").lower()
            if operator not in {"eq", "ne", "gt", "ge", "lt", "le", "contains"}:
                operator = "eq"
            filters.append(
                FilterCondition(
                    field=field_name,
                    operator=operator,
                    value=str(value),
                    value_type=LlmDynamicPathPlanner._filter_value_type(item, field_map[field_name]),
                )
            )
        return filters

    def _filter_value_type(raw_filter: dict[str, Any], field_metadata: dict[str, Any]) -> str:
        explicit_type = raw_filter.get("value_type")
        if isinstance(explicit_type, str) and explicit_type.strip():
            return explicit_type.strip()
        data_type = field_metadata.get("data_type") or field_metadata.get("type")
        if isinstance(data_type, str) and data_type.strip():
            return data_type.strip()
        return "string"

    @staticmethod
    def _materialize_bindings(item: dict[str, Any], field_map: dict[str, dict[str, Any]]) -> list[StepBinding]:
        raw_bindings = item.get("filter_from_previous", item.get("filters_from_previous", []))
        bindings: list[StepBinding] = []
        for binding in raw_bindings if isinstance(raw_bindings, list) else []:
            if not isinstance(binding, dict):
                continue
            field_name = LlmDynamicPathPlanner._first_non_empty(
                binding,
                "field",
                "target_field",
                "binding_target_field",
                "to_field",
                "join_target_field",
            )
            source_step_id = LlmDynamicPathPlanner._first_non_empty(
                binding,
                "source_step_id",
                "source_step",
                "step_id",
                "from_step",
                "previous_step_id",
                "previous_step",
            )
            source_field = LlmDynamicPathPlanner._first_non_empty(
                binding,
                "source_field",
                "binding_source_field",
                "from_field",
                "join_source_field",
            )
            if not source_field and field_name:
                source_field = field_name
            if field_name and source_step_id and source_field:
                bindings.append(StepBinding(field=field_name, source_step_id=source_step_id, source_field=source_field))
        return bindings

    @staticmethod
    def _materialize_shorthand_binding(
        item: dict[str, Any],
        field_map: dict[str, dict[str, Any]],
        previous_step: ExecutionStep,
    ) -> StepBinding | None:
        source_field = LlmDynamicPathPlanner._first_non_empty(
            item,
            "binding_source_field",
            "source_field",
            "join_source_field",
            "from_field",
        )
        explicit_target_field = LlmDynamicPathPlanner._first_non_empty(
            item,
            "binding_target_field",
            "join_target_field",
            "to_field",
            "field",
        )
        fallback_target_field = LlmDynamicPathPlanner._first_non_empty(item, "target_field")
        target_field = explicit_target_field
        if source_field and not target_field:
            target_field = fallback_target_field if fallback_target_field in field_map else source_field
        source_step_id = LlmDynamicPathPlanner._first_non_empty(
            item,
            "binding_source_step_id",
            "source_step_id",
            "source_step",
            "from_step",
            "previous_step_id",
            "previous_step",
        ) or previous_step.step_id
        if not source_field and explicit_target_field:
            source_field = target_field
        if not target_field and source_field in field_map:
            target_field = source_field
        if not source_field or not target_field or not source_step_id:
            return None
        return StepBinding(field=target_field, source_step_id=source_step_id, source_field=source_field)

    @staticmethod
    def _first_non_empty(item: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    @staticmethod
    def _summary_fields(raw_summary: Any, select_fields: list[str], target_field: str | None) -> list[str]:
        raw_items = raw_summary if isinstance(raw_summary, list) else []
        summary = [str(item) for item in raw_items if str(item) in select_fields]
        if target_field and target_field in select_fields and target_field not in summary:
            summary.insert(0, target_field)
        for field_name in select_fields:
            if field_name not in summary:
                summary.append(field_name)
            if len(summary) >= 6:
                break
        return summary[:6]

    @staticmethod
    def _response_directive(parsed: dict[str, Any]) -> str:
        directive = str(parsed.get("response_directive") or "").strip()
        presentation = parsed.get("presentation") if isinstance(parsed.get("presentation"), dict) else {}
        kind = str(presentation.get("kind") or "").strip()
        reason = str(presentation.get("reason") or "").strip()
        parts = [directive]
        if kind:
            parts.append(f"Presentation kind selected by LLM: {kind}.")
        if reason:
            parts.append(f"Presentation reason: {reason}.")
        return " ".join(part for part in parts if part)

    @staticmethod
    def _presentation_kind(parsed: dict[str, Any]) -> str:
        presentation = parsed.get("presentation") if isinstance(parsed.get("presentation"), dict) else {}
        return str(presentation.get("kind") or "").lower()

    @staticmethod
    def _valid_fields(raw_fields: Any, field_map: dict[str, dict[str, Any]]) -> list[str]:
        results = []
        for field in raw_fields if isinstance(raw_fields, list) else []:
            field_name = str(field)
            if field_name in field_map and field_name not in results:
                results.append(field_name)
        return results

    @staticmethod
    def _default_fields(entity: dict[str, Any], field_map: dict[str, dict[str, Any]]) -> list[str]:
        fields = [
            str(field)
            for field in [*(entity.get("key_fields", []) or []), *(entity.get("default_select_fields", []) or [])]
            if str(field) in field_map
        ]
        return list(dict.fromkeys(fields))[:8]

    @staticmethod
    def _parse_top(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(1, min(parsed, 500))

    @staticmethod
    def _field_map(snapshot, entity_set: str) -> dict[str, dict[str, Any]]:
        return {
            str(field.get("field_name", "")): field
            for field in snapshot.fields
            if field.get("entity_set") == entity_set and field.get("field_name")
        }

    @staticmethod
    def _lookup_entity(snapshot, entity_set: str) -> dict[str, Any] | None:
        return next((entity for entity in snapshot.entities if entity.get("entity_set") == entity_set), None)

    @staticmethod
    def _get_entity_fields(snapshot, entity_set: str) -> list[dict[str, Any]]:
        return [field for field in snapshot.fields if field.get("entity_set") == entity_set]

    @staticmethod
    def _first_entity(schema_context: dict[str, Any]) -> str:
        entities = schema_context.get("entities", [])
        if entities:
            return str(entities[0].get("entity_set") or "UNKNOWN_ENTITY")
        return "UNKNOWN_ENTITY"

    @staticmethod
    def _compact_schema_context(schema_context: dict[str, Any]) -> dict[str, Any]:
        return {
            "entity_count": len(schema_context.get("entities", [])),
            "candidate_field_count": len(schema_context.get("candidate_fields", [])),
            "join_hint_count": len(schema_context.get("join_hints", [])),
            "top_entities": [item.get("entity_set") for item in schema_context.get("entities", [])[:8]],
            "top_fields": [
                f"{item.get('entity_set')}.{item.get('field_name')}"
                for item in schema_context.get("candidate_fields", [])[:16]
            ],
            "schema_research": schema_context.get("schema_research", {}),
        }

    @staticmethod
    def _split_camel(text: str) -> str:
        return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))

    @staticmethod
    def _normalize(text: str) -> str:
        value = str(text or "").lower()
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        return re.sub(r"[^a-z0-9@\.\-\u4e00-\u9fff]+", " ", value).strip()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9_@.\-]+|[\u4e00-\u9fff]{1,}", text or "")
