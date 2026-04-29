from __future__ import annotations

import json
import re
import ssl
import urllib.request
from difflib import SequenceMatcher
from dataclasses import replace
from typing import Any

from sap_odata_agent.application.candidate_ranker import CandidateRanker
from sap_odata_agent.domain.models import (
    AgentRequest,
    CandidatePlan,
    CardinalityPolicy,
    ExecutionStep,
    FilterCondition,
    QueryConstraints,
    QueryShape,
    QueryPlan,
    RetrievedContext,
    RetrievedDocument,
    StepBinding,
)
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader


class AnthropicCompatibleMessagesClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 30,
        verify_ssl: bool = True,
        api_path: str = "/v1/messages",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl
        self.api_path = api_path if api_path.startswith("/") else f"/{api_path}"

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        endpoint = f"{self.base_url}{self.api_path}"
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        handlers: list[urllib.request.BaseHandler] = []
        if endpoint.lower().startswith("https://") and not self.verify_ssl:
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content_items = payload.get("content", [])
        text_parts = [item.get("text", "") for item in content_items if item.get("type") == "text"]
        return "\n".join(part for part in text_parts if part).strip()


class OpenAiCompatibleChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 30,
        verify_ssl: bool = True,
        api_path: str = "/v1/chat/completions",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.verify_ssl = verify_ssl
        self.api_path = api_path if api_path.startswith("/") else f"/{api_path}"

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        endpoint = f"{self.base_url}{self.api_path}"
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
            method="POST",
        )
        handlers: list[urllib.request.BaseHandler] = []
        if endpoint.lower().startswith("https://") and not self.verify_ssl:
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        opener = urllib.request.build_opener(*handlers)
        with opener.open(request, timeout=self.timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        choices = response_payload.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
        return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


class RetrievalAwareIntentPlanner:
    ACTION_HINTS = {
        "POST": {"创建", "新增", "添加", "新建", "create", "add"},
        "PATCH": {"修改", "更新", "变更", "调整", "update", "change", "edit"},
        "DELETE": {"删除", "移除", "作废", "delete", "remove"},
    }
    ENTITY_HINTS = {
        "customer": {"客户", "customer"},
        "supplier": {"供应商", "supplier", "vendor"},
        "business_partner": {"业务伙伴", "business partner", "bp"},
    }
    FIELD_HINTS: dict[str, set[str]] = {}
    BASIC_PROFILE_HINTS = {"基本信息", "概况", "主数据", "详情"}
    MULTI_ROW_HINTS = {"所有", "全部", "分别", "列表", "哪些", "all", "each", "list"}
    CONTEXT_HINTS: dict[str, set[str]] = {}
    FIELD_GROUP_TARGETS: dict[str, tuple[str, ...]] = {}
    ROOT_ENTITIES = {"A_BusinessPartner", "A_Customer", "A_Supplier"}
    ENTITY_HINTS["customer"].add("\u5ba2\u6237")
    ENTITY_HINTS["supplier"].add("\u4f9b\u5e94\u5546")
    ENTITY_HINTS["business_partner"].add("\u4e1a\u52a1\u4f19\u4f34")
    ENTITY_SUFFIX_PENALTIES = {
        "SalesArea": 6.0,
        "Company": 3.0,
        "Tax": 3.0,
        "Dunning": 3.0,
        "WithHoldingTax": 3.0,
        "PurchasingOrg": 3.0,
        "Text": 2.0,
        "AddrDepdnt": 2.5,
    }

    def __init__(self, index_root: str = "data/index", service_name: str = "API_BUSINESS_PARTNER") -> None:
        self.service_name = service_name
        self.loader = LocalIndexLoader(index_root=index_root)
        self.candidate_ranker = CandidateRanker()

    def plan(self, request: AgentRequest, context: RetrievedContext) -> QueryPlan:
        snapshot = self._load_snapshot()
        intent = self._analyze_query(self._get_working_input(request))
        method = intent["method"]
        recall_bundle = self._build_recall_bundle(snapshot, context.documents, intent)
        constraints = request.constraints
        if constraints and constraints.filter_values and not intent.get("identifier_value"):
            intent["identifier_value"] = max(constraints.filter_values, key=len)
        if constraints is None:
            path_plan = self._build_path_plan(snapshot, recall_bundle, intent, self._constraints_from_intent(intent), method)
            if path_plan is not None:
                return path_plan
            entity = recall_bundle["best_entity"]
            if entity is None:
                return QueryPlan(
                    service_name="UNKNOWN_SERVICE",
                    entity_set="UNKNOWN_ENTITY",
                    http_method=method,
                    requires_confirmation=method != "GET",
                    rationale="No suitable entity candidate was found from retrieved local index context.",
                    planner_diagnostics={"recall_strategy": "all_fields_with_fuzzy_matching", "field_candidates": [], "entity_candidates": [], "ranked_candidates": []},
                )
            fields_for_entity = self._get_entity_fields(snapshot, entity["entity_set"])
            filter_field = self._choose_filter_field(entity, fields_for_entity, intent)
            filters = self._build_filters(filter_field, intent, None)
            select_fields = self._choose_select_fields(
                entity,
                fields_for_entity,
                intent,
                filter_field,
                recall_bundle["field_candidates"],
            )
            select_fields = self._apply_constraint_target_fields(select_fields, fields_for_entity, None)
            rationale = [
                f"Selected entity `{entity['entity_set']}` from retrieved local index context.",
                f"Planned method `{method}`.",
            ]
            if filter_field and intent["identifier_value"]:
                rationale.append(f"Matched identifier `{intent['identifier_value']}` to field `{filter_field}`.")
            if select_fields:
                rationale.append(f"Selected fields: {', '.join(select_fields[:6])}.")
            top_fields = [
                f"{item['entity_set']}.{item['field_name']}"
                for item in recall_bundle["field_candidates"][:4]
                if item.get("field_name")
            ]
            if top_fields:
                rationale.append(f"Top recalled fields: {', '.join(top_fields)}.")
            return QueryPlan(
                service_name=entity["service_name"],
                entity_set=entity["entity_set"],
                http_method=method,
                select_fields=select_fields,
                response_summary_fields=select_fields[:4],
                filters=filters,
                top=20 if intent["wants_multiple_rows"] else (1 if filters else 20),
                requires_confirmation=method != "GET",
                response_directive=(
                    "Answer with a list or table covering all matching rows."
                    if intent["wants_multiple_rows"]
                    else "Answer the user directly with the most relevant selected fields."
                ),
                rationale=" ".join(rationale),
                planner_diagnostics=self._build_planner_diagnostics(recall_bundle, "fallback_recall"),
            )

        ranked_candidates = self.candidate_ranker.rank(
            constraints,
            recall_bundle.get("entity_candidates", []),
            recall_bundle.get("path_candidates", []),
        )
        dynamic_paths = [
            *self._synthesize_bridge_paths(snapshot, recall_bundle, constraints),
            *self._synthesize_attribute_filter_paths(snapshot, recall_bundle, constraints),
        ]
        if dynamic_paths:
            recall_bundle["path_candidates"] = [*dynamic_paths, *recall_bundle.get("path_candidates", [])]
            ranked_candidates = self.candidate_ranker.rank(
                constraints,
                recall_bundle.get("entity_candidates", []),
                recall_bundle.get("path_candidates", []),
            )
        recall_bundle["ranked_candidates"] = ranked_candidates
        path_plan = self._build_path_plan(snapshot, recall_bundle, intent, constraints, method)
        if path_plan is not None:
            return path_plan
        entity = self._choose_best_entity_from_ranked_candidates(recall_bundle, ranked_candidates) or recall_bundle["best_entity"]
        if entity is None:
            return QueryPlan(
                service_name="UNKNOWN_SERVICE",
                entity_set="UNKNOWN_ENTITY",
                http_method=method,
                requires_confirmation=method != "GET",
                rationale="No suitable entity candidate was found from retrieved local index context.",
                planner_diagnostics={"recall_strategy": "all_fields_with_fuzzy_matching", "field_candidates": [], "entity_candidates": [], "ranked_candidates": []},
            )
        fields_for_entity = self._get_entity_fields(snapshot, entity["entity_set"])
        filter_field = self._choose_constraint_filter_field(fields_for_entity, constraints)
        if filter_field is None:
            filter_field = self._choose_filter_field(entity, fields_for_entity, intent)
        filters = self._build_filters(filter_field, intent, constraints)
        select_fields = self._choose_select_fields(
            entity,
            fields_for_entity,
            intent,
            filter_field,
            recall_bundle["field_candidates"],
        )
        select_fields = self._apply_constraint_target_fields(select_fields, fields_for_entity, constraints)
        rationale = [
            f"Selected entity `{entity['entity_set']}` from retrieved local index context.",
            f"Planned method `{method}`.",
        ]
        if filter_field and intent["identifier_value"]:
            rationale.append(f"Matched identifier `{intent['identifier_value']}` to field `{filter_field}`.")
        if select_fields:
            rationale.append(f"Selected fields: {', '.join(select_fields[:6])}.")
        top_fields = [
            f"{item['entity_set']}.{item['field_name']}"
            for item in recall_bundle["field_candidates"][:4]
            if item.get("field_name")
        ]
        if top_fields:
            rationale.append(f"Top recalled fields: {', '.join(top_fields)}.")
        return QueryPlan(
            service_name=entity["service_name"],
            entity_set=entity["entity_set"],
            http_method=method,
            select_fields=select_fields,
            response_summary_fields=select_fields[:4],
            filters=filters,
            top=self._resolve_top(constraints, filters),
            requires_confirmation=method != "GET",
            response_directive=(
                "Answer with a list or table covering all matching rows."
                if constraints.cardinality == CardinalityPolicy.MANY or intent["wants_multiple_rows"]
                else "Answer the user directly with the most relevant selected fields."
            ),
            rationale=" ".join(rationale),
            planner_diagnostics=self._build_planner_diagnostics(recall_bundle, "constraint_ranked_recall", constraints, request),
        )

    def _build_path_plan(
        self,
        snapshot,
        recall_bundle: dict[str, Any],
        intent: dict[str, Any],
        constraints: QueryConstraints,
        method: str,
    ) -> QueryPlan | None:
        ranked_path_candidates = [
            candidate
            for candidate in recall_bundle.get("ranked_candidates", [])
            if candidate.candidate_type == "path" and candidate.hard_constraints_passed
        ]
        scored_path_candidates = []
        for candidate in ranked_path_candidates:
            raw = next(
                (item for item in recall_bundle.get("path_candidates", []) if item.get("path_id") == candidate.path_id),
                None,
            )
            if raw is None:
                continue
            scored_path_candidates.append({**raw, "_effective_score": candidate.final_score})
        if (
            not scored_path_candidates
            and "ranked_candidates" in recall_bundle
            and (constraints.target_field_concepts or constraints.filter_concepts)
        ):
            return None
        if not scored_path_candidates:
            scored_path_candidates = sorted(
                [
                    {**item, "_effective_score": self._score_path_candidate(item, intent)}
                    for item in recall_bundle.get("path_candidates", [])
                ],
                key=lambda item: item["_effective_score"],
                reverse=True,
            )
        primary_filter_value = self._resolve_primary_filter_value(intent, constraints)
        if not scored_path_candidates or snapshot is None or not primary_filter_value:
            return None
        top_path = scored_path_candidates[0]
        if not self._should_use_path(top_path, recall_bundle, intent):
            return None

        steps: list[ExecutionStep] = []
        previous_step: ExecutionStep | None = None
        previous_select_fields: list[str] = []
        for index, raw_step in enumerate(top_path.get("steps", []), start=1):
            entity_set = str(raw_step.get("entity_set", ""))
            if not entity_set:
                return None
            filter_field = str(raw_step.get("filter_field", ""))
            select_fields = self._normalize_step_select_fields(raw_step.get("select_fields"))
            if filter_field and filter_field not in select_fields:
                select_fields = [filter_field, *select_fields]
            step_filters: list[FilterCondition] = []
            filter_from_previous: list[StepBinding] = []
            if index == 1:
                if filter_field:
                    step_filters.append(
                        FilterCondition(
                            field=filter_field,
                            operator="contains" if constraints.name_match_mode == "contains" else "eq",
                            value=primary_filter_value,
                        )
                    )
            elif filter_field:
                source_step_id = previous_step.step_id if previous_step is not None else ""
                if filter_field in previous_select_fields and source_step_id:
                    filter_from_previous.append(
                        StepBinding(
                            field=filter_field,
                            source_step_id=source_step_id,
                            source_field=filter_field,
                        )
                    )
                elif previous_select_fields and source_step_id:
                    filter_from_previous.append(
                        StepBinding(
                            field=filter_field,
                            source_step_id=source_step_id,
                            source_field=previous_select_fields[0],
                        )
                    )
                else:
                    step_filters.append(
                        FilterCondition(field=filter_field, operator="eq", value=intent["identifier_value"])
                    )
            step = ExecutionStep(
                step_id=str(raw_step.get("step_id", f"step_{index}")),
                entity_set=entity_set,
                http_method=str(raw_step.get("http_method", method or "GET")),
                select_fields=select_fields,
                response_summary_fields=select_fields[:4],
                filters=step_filters,
                filter_from_previous=filter_from_previous,
                top=int(raw_step.get("top", 1 if index < len(top_path.get("steps", [])) else 20)),
                rationale=str(raw_step.get("rationale", top_path.get("description", ""))),
            )
            steps.append(step)
            previous_step = step
            previous_select_fields = select_fields

        if not steps:
            return None

        final_step = steps[-1]
        target_entity_set = str(top_path.get("target_entity_set", final_step.entity_set))
        target_field = str(top_path.get("target_field", "")) or None
        best_entity = self._lookup_entity(snapshot, target_entity_set) or {"service_name": self.service_name}
        final_summary_fields = self._choose_final_summary_fields(final_step.select_fields, target_field)
        rationale = [
            f"Selected lookup path `{top_path.get('path_id', '')}`.",
            f"Anchor `{top_path.get('anchor_object', '')}` matched filter value `{primary_filter_value}`.",
            f"Final target `{target_entity_set}.{target_field or final_step.select_fields[:1]}`.",
        ]
        return QueryPlan(
            service_name=best_entity.get("service_name", self.service_name),
            entity_set=target_entity_set,
            http_method=method,
            select_fields=final_step.select_fields,
            response_summary_fields=final_summary_fields,
            filters=steps[0].filters,
            top=max(final_step.top or 20, self._resolve_top(constraints, steps[0].filters)),
            requires_confirmation=method != "GET",
            response_directive=(
                "Execute the planned lookup path step by step and answer from the final step results."
            ),
            rationale=" ".join(rationale),
            planner_diagnostics=self._build_planner_diagnostics(recall_bundle, "path_recall", constraints),
            plan_kind="multi_step" if len(steps) > 1 else "lookup",
            anchor_object=str(top_path.get("anchor_object", "")) or None,
            anchor_value=primary_filter_value,
            target_field=target_field,
            target_entity_set=target_entity_set,
            path_id=str(top_path.get("path_id", "")) or None,
            steps=steps,
        )

    @staticmethod
    def _choose_best_entity_from_ranked_candidates(
        recall_bundle: dict[str, Any],
        ranked_candidates: list[CandidatePlan],
    ) -> dict[str, Any] | None:
        ranked_entity = next(
            (candidate for candidate in ranked_candidates if candidate.candidate_type == "entity" and candidate.hard_constraints_passed),
            None,
        )
        if ranked_entity is None:
            return None
        return next(
            (item for item in recall_bundle.get("entity_candidates", []) if item.get("entity_set") == ranked_entity.entity_set),
            None,
        )

    def _synthesize_bridge_paths(
        self,
        snapshot,
        recall_bundle: dict[str, Any],
        constraints: QueryConstraints,
    ) -> list[dict[str, Any]]:
        if snapshot is None or not constraints.target_object or not constraints.target_field_concepts:
            return []
        anchor_field = self._object_field_name(constraints.target_object)
        if not anchor_field or anchor_field == "BusinessPartner":
            bridge_fields = ["Customer", "Supplier"]
        else:
            bridge_fields = ["BusinessPartner"]
        field_candidates = recall_bundle.get("field_candidates", [])
        target_pairs = [
            (candidate.get("entity_set", ""), candidate.get("field_name", ""))
            for candidate in field_candidates
            if candidate.get("field_name") in set(constraints.target_field_concepts)
        ]
        if not target_pairs:
            target_pairs = [
                (field.get("entity_set", ""), field.get("field_name", ""))
                for field in snapshot.fields
                if field.get("field_name") in set(constraints.target_field_concepts)
            ]

        existing_path_ids = {path.get("path_id", "") for path in recall_bundle.get("path_candidates", [])}
        paths: list[dict[str, Any]] = []
        for target_entity_set, target_field in target_pairs:
            if not target_entity_set or not target_field:
                continue
            target_fields = self._get_entity_fields(snapshot, target_entity_set)
            target_field_names = {field.get("field_name", "") for field in target_fields}
            if anchor_field in target_field_names:
                continue
            required_on_target = [
                field_name
                for field_name in constraints.target_field_concepts
                if field_name in target_field_names
            ]
            for bridge_field in bridge_fields:
                if bridge_field not in target_field_names:
                    continue
                resolver = self._find_identity_resolver(snapshot, anchor_field, bridge_field)
                if resolver is None:
                    continue
                resolver_entity_set = resolver["entity_set"]
                path_id = f"{anchor_field.lower()}_to_{target_field.lower()}_via_{bridge_field.lower()}_{target_entity_set.lower()}"
                if path_id in existing_path_ids:
                    continue
                default_fields = self._lookup_entity(snapshot, target_entity_set).get("default_select_fields", []) if self._lookup_entity(snapshot, target_entity_set) else []
                final_select_fields = self._dedupe_fields([bridge_field, *default_fields, *required_on_target, target_field])
                paths.append(
                    {
                        "path_id": path_id,
                        "anchor_object": anchor_field,
                        "target_entity_set": target_entity_set,
                        "target_field": target_field,
                        "path_kind": "dynamic_bridge_lookup",
                        "return_object": anchor_field,
                        "filter_fields": [anchor_field, bridge_field],
                        "result_fields": final_select_fields,
                        "description": (
                            f"Resolve `{anchor_field}` to `{bridge_field}` on `{resolver_entity_set}`, "
                            f"then read `{target_field}` from `{target_entity_set}`."
                        ),
                        "score": 48.0,
                        "confidence": 0.72,
                        "business_aliases": [],
                        "source": "dynamic-bridge",
                        "steps": [
                            {
                                "step_id": "resolve_bridge_object",
                                "entity_set": resolver_entity_set,
                                "filter_field": anchor_field,
                                "select_fields": self._dedupe_fields([anchor_field, bridge_field]),
                                "top": 1,
                            },
                            {
                                "step_id": "fetch_target",
                                "entity_set": target_entity_set,
                                "filter_field": bridge_field,
                                "select_fields": final_select_fields,
                                "top": 20,
                            },
                        ],
                    }
                )
                existing_path_ids.add(path_id)
        return paths

    def _synthesize_attribute_filter_paths(
        self,
        snapshot,
        recall_bundle: dict[str, Any],
        constraints: QueryConstraints,
    ) -> list[dict[str, Any]]:
        if (
            snapshot is None
            or not constraints.target_object
            or not constraints.filter_concepts
            or constraints.query_shape not in {QueryShape.SEARCH_BY_ATTRIBUTE, QueryShape.LIST_QUERY}
        ):
            return []

        anchor_field = self._object_field_name(constraints.target_object)
        if not anchor_field:
            return []
        if (
            constraints.query_shape == QueryShape.LIST_QUERY
            and self._has_direct_attribute_filter_entity(recall_bundle.get("entity_candidates", []), anchor_field, constraints.filter_concepts)
        ):
            return []

        filter_fields = set(constraints.filter_concepts)
        existing_path_ids = {path.get("path_id", "") for path in recall_bundle.get("path_candidates", [])}
        existing_attribute_signatures = self._attribute_filter_path_signatures(
            recall_bundle.get("path_candidates", [])
        )
        filter_pairs: list[tuple[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for candidate in recall_bundle.get("field_candidates", []):
            pair = (str(candidate.get("entity_set", "")), str(candidate.get("field_name", "")))
            if pair[0] and pair[1] in filter_fields and pair not in seen_pairs:
                filter_pairs.append(pair)
                seen_pairs.add(pair)
        for field in snapshot.fields:
            pair = (str(field.get("entity_set", "")), str(field.get("field_name", "")))
            if pair[0] and pair[1] in filter_fields and pair not in seen_pairs:
                filter_pairs.append(pair)
                seen_pairs.add(pair)
        filter_pairs.sort(
            key=lambda pair: (
                -self._attribute_filter_entity_bias(
                    pair[0],
                    {
                        field.get("field_name", "")
                        for field in self._get_entity_fields(snapshot, pair[0])
                    },
                ),
                pair[0],
                pair[1],
            )
        )

        paths: list[dict[str, Any]] = []
        for filter_entity_set, filter_field in filter_pairs:
            filter_entity = self._lookup_entity(snapshot, filter_entity_set)
            filter_entity_fields = self._get_entity_fields(snapshot, filter_entity_set)
            filter_field_meta = next(
                (field for field in filter_entity_fields if field.get("field_name") == filter_field),
                None,
            )
            if filter_field_meta is None or filter_field_meta.get("filterable") is False:
                continue

            filter_field_names = {field.get("field_name", "") for field in filter_entity_fields}
            default_fields = list((filter_entity or {}).get("default_select_fields", []) or [])
            context_fields = self._dedupe_fields(
                [
                    filter_field,
                    *default_fields,
                    *[
                        field_name
                        for field_name in filter_field_names
                        if field_name != filter_field
                    ],
                ]
            )[:8]
            aliases = self._field_aliases(filter_field_meta)

            if anchor_field in filter_field_names:
                select_fields = self._dedupe_fields([anchor_field, *context_fields])[:8]
                path_id = f"{anchor_field.lower()}_list_by_{filter_field.lower()}_on_{filter_entity_set.lower()}_dynamic"
                signature = (anchor_field, filter_field, filter_entity_set)
                if path_id in existing_path_ids or signature in existing_attribute_signatures:
                    continue
                paths.append(
                    {
                        "path_id": path_id,
                        "anchor_object": anchor_field,
                        "target_entity_set": filter_entity_set,
                        "target_field": filter_field,
                        "path_kind": "attribute_filter_list",
                        "return_object": anchor_field,
                        "filter_fields": [filter_field],
                        "result_fields": select_fields,
                        "description": f"Filter `{anchor_field}` records by `{filter_field}` on `{filter_entity_set}`.",
                        "score": 52.0 + self._attribute_filter_entity_bias(filter_entity_set, filter_field_names),
                        "confidence": min(
                            0.95,
                            0.76 + (self._attribute_filter_entity_bias(filter_entity_set, filter_field_names) * 0.01),
                        ),
                        "business_aliases": aliases,
                        "source": "dynamic-attribute-filter",
                        "steps": [
                            {
                                "step_id": "filter_target_object",
                                "entity_set": filter_entity_set,
                                "filter_field": filter_field,
                                "select_fields": select_fields,
                                "top": 50,
                            }
                        ],
                    }
                )
                existing_path_ids.add(path_id)
                continue

            bridge_source_field = next(
                (
                    field_name
                    for field_name in ("BusinessPartner", "BusinessPartnerCompany")
                    if field_name in filter_field_names
                ),
                "",
            )
            if not bridge_source_field:
                continue

            if anchor_field == "BusinessPartner":
                select_fields = self._dedupe_fields([bridge_source_field, *context_fields])[:8]
                path_id = f"businesspartner_list_by_{filter_field.lower()}_via_{filter_entity_set.lower()}_dynamic"
                signature = ("BusinessPartner", filter_field, filter_entity_set)
                if path_id in existing_path_ids or signature in existing_attribute_signatures:
                    continue
                paths.append(
                    {
                        "path_id": path_id,
                        "anchor_object": "BusinessPartner",
                        "target_entity_set": filter_entity_set,
                        "target_field": filter_field,
                        "path_kind": "attribute_filter_list",
                        "return_object": "BusinessPartner",
                        "filter_fields": [filter_field],
                        "result_fields": select_fields,
                        "description": f"Filter business partners by `{filter_field}` on `{filter_entity_set}`.",
                        "score": 50.0 + self._attribute_filter_entity_bias(filter_entity_set, filter_field_names),
                        "confidence": min(
                            0.93,
                            0.72 + (self._attribute_filter_entity_bias(filter_entity_set, filter_field_names) * 0.01),
                        ),
                        "business_aliases": aliases,
                        "source": "dynamic-attribute-filter",
                        "steps": [
                            {
                                "step_id": "filter_attribute",
                                "entity_set": filter_entity_set,
                                "filter_field": filter_field,
                                "select_fields": select_fields,
                                "top": 50,
                            }
                        ],
                    }
                )
                existing_path_ids.add(path_id)
                continue

            resolver = self._find_identity_resolver(snapshot, anchor_field, "BusinessPartner")
            if resolver is None:
                continue
            resolver_fields = {
                field.get("field_name", "")
                for field in self._get_entity_fields(snapshot, resolver.get("entity_set", ""))
            }
            final_select_fields = self._dedupe_fields(
                [
                    "BusinessPartner",
                    anchor_field,
                    *[
                        field_name
                        for field_name in ("BusinessPartnerFullName", "Customer", "Supplier")
                        if field_name in resolver_fields
                    ],
                ]
            )[:8]
            path_id = f"{anchor_field.lower()}_list_by_{filter_field.lower()}_via_{filter_entity_set.lower()}_dynamic"
            signature = (anchor_field, filter_field, filter_entity_set)
            if path_id in existing_path_ids or signature in existing_attribute_signatures:
                continue
            paths.append(
                {
                    "path_id": path_id,
                    "anchor_object": anchor_field,
                    "target_entity_set": resolver.get("entity_set", "A_BusinessPartner"),
                    "target_field": filter_field,
                    "path_kind": "attribute_filter_list",
                    "return_object": anchor_field,
                    "filter_fields": [filter_field],
                    "result_fields": final_select_fields,
                    "description": (
                        f"Filter records by `{filter_field}` on `{filter_entity_set}`, then resolve "
                        f"`BusinessPartner` to `{anchor_field}`."
                    ),
                    "score": 54.0 + self._attribute_filter_entity_bias(filter_entity_set, filter_field_names),
                    "confidence": min(
                        0.96,
                        0.78 + (self._attribute_filter_entity_bias(filter_entity_set, filter_field_names) * 0.01),
                    ),
                    "business_aliases": aliases,
                    "source": "dynamic-attribute-filter",
                    "steps": [
                        {
                            "step_id": "filter_attribute",
                            "entity_set": filter_entity_set,
                            "filter_field": filter_field,
                            "select_fields": self._dedupe_fields([bridge_source_field, *context_fields])[:8],
                            "top": 50,
                        },
                        {
                            "step_id": "resolve_target_object",
                            "entity_set": resolver.get("entity_set", "A_BusinessPartner"),
                            "filter_field": "BusinessPartner",
                            "select_fields": final_select_fields,
                            "top": 50,
                        },
                    ],
                }
            )
            existing_path_ids.add(path_id)
        return paths

    @staticmethod
    def _has_direct_attribute_filter_entity(
        entity_candidates: list[dict[str, Any]],
        anchor_field: str,
        filter_concepts: list[str],
    ) -> bool:
        for entity in entity_candidates:
            available_fields = set(entity.get("available_fields", []) or [])
            if anchor_field in available_fields and any(field in available_fields for field in filter_concepts):
                return True
        return False

    @staticmethod
    def _attribute_filter_entity_bias(entity_set: str, field_names: set[str]) -> float:
        bias = 0.0
        if "BusinessPartner" in field_names:
            bias += 3.0
        elif "BusinessPartnerCompany" in field_names:
            bias -= 1.0
        return bias

    @staticmethod
    def _attribute_filter_path_signatures(path_candidates: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
        signatures: set[tuple[str, str, str]] = set()
        for path in path_candidates:
            if path.get("path_kind") != "attribute_filter_list":
                continue
            return_object = str(path.get("return_object") or path.get("anchor_object") or "")
            steps = path.get("steps", []) or []
            first_entity = str((steps[0] if steps else {}).get("entity_set", ""))
            for filter_field in path.get("filter_fields", []) or []:
                if return_object and filter_field and first_entity:
                    signatures.add((return_object, str(filter_field), first_entity))
        return signatures

    @staticmethod
    def _field_aliases(field: dict[str, Any]) -> list[str]:
        aliases: list[str] = []
        for key in ("label", "description", "field_name"):
            value = str(field.get(key, "") or "").strip()
            if value and value not in aliases:
                aliases.append(value)
        for alias in field.get("business_aliases", []) or []:
            value = str(alias or "").strip()
            if value and value not in aliases:
                aliases.append(value)
        return aliases

    def _find_identity_resolver(self, snapshot, anchor_field: str, bridge_field: str) -> dict[str, Any] | None:
        preferred = "A_BusinessPartner"
        for entity_set in [preferred, *[entity.get("entity_set", "") for entity in snapshot.entities]]:
            entity = self._lookup_entity(snapshot, entity_set)
            if entity is None:
                continue
            field_names = {field.get("field_name", "") for field in self._get_entity_fields(snapshot, entity_set)}
            if anchor_field in field_names and bridge_field in field_names:
                return entity
        return None

    @staticmethod
    def _object_field_name(target_object: str) -> str:
        return {
            "supplier": "Supplier",
            "customer": "Customer",
            "business_partner": "BusinessPartner",
        }.get(target_object, "")

    @staticmethod
    def _dedupe_fields(fields: list[str]) -> list[str]:
        deduped: list[str] = []
        for field in fields:
            if field and field not in deduped:
                deduped.append(field)
        return deduped

    @staticmethod
    def _get_working_input(request: AgentRequest) -> str:
        return request.resolved_user_input or request.user_input

    def _load_snapshot(self):
        try:
            return self.loader.load(self.service_name)
        except FileNotFoundError:
            return None

    def _build_recall_bundle(self, snapshot, documents: list[RetrievedDocument], intent: dict) -> dict[str, Any]:
        field_candidates = self._recall_field_candidates(snapshot, documents, intent)
        path_candidates = self._collect_path_candidates(documents)
        entity_candidates = self._rank_entities_from_candidates(snapshot, documents, intent, field_candidates)
        best_entity = entity_candidates[0] if entity_candidates else self._choose_entity_from_documents(documents, snapshot, intent)
        return {
            "field_candidates": field_candidates,
            "path_candidates": path_candidates,
            "entity_candidates": entity_candidates,
            "best_entity": best_entity,
        }

    @staticmethod
    def _normalize_step_select_fields(raw_value: Any) -> list[str]:
        if isinstance(raw_value, list):
            return [str(item) for item in raw_value if str(item).strip()]
        if isinstance(raw_value, str):
            return [item.strip() for item in raw_value.split(",") if item.strip()]
        return []

    @staticmethod
    def _choose_final_summary_fields(select_fields: list[str], target_field: str | None) -> list[str]:
        summary: list[str] = []
        if target_field and target_field in select_fields:
            summary.append(target_field)
        for field_name in select_fields:
            if field_name not in summary:
                summary.append(field_name)
            if len(summary) >= 4:
                break
        return summary[:4]

    @staticmethod
    def _should_use_path(
        top_path: dict[str, Any],
        recall_bundle: dict[str, Any],
        intent: dict[str, Any],
    ) -> bool:
        steps = top_path.get("steps", []) or []
        path_kind = str(top_path.get("path_kind", "lookup"))
        target_field = str(top_path.get("target_field", ""))
        requested_fields = set(intent.get("requested_exact_fields", []))
        top_path_score = float(top_path.get("_effective_score", top_path.get("score", 0.0)))
        top_field_score = float((recall_bundle.get("field_candidates") or [{}])[0].get("score", 0.0))
        normalized_threshold = 0.35 if top_path_score <= 1.0 else 8.0
        if path_kind == "attribute_filter_list" and len(steps) > 1 and top_path_score >= normalized_threshold:
            return True
        if len(steps) > 1 and top_path_score >= normalized_threshold:
            return True
        comparison_threshold = max(normalized_threshold, (top_field_score - 2.0) if top_path_score > 1.0 else 0.3)
        if target_field and target_field in requested_fields and top_path_score >= comparison_threshold:
            return True
        return False

    @staticmethod
    def _score_path_candidate(path_candidate: dict[str, Any], intent: dict[str, Any]) -> float:
        score = float(path_candidate.get("score", 0.0))
        anchor_object = str(path_candidate.get("anchor_object", ""))
        target_field = str(path_candidate.get("target_field", ""))
        object_type = intent.get("object_type", "")
        requested_fields = set(intent.get("requested_exact_fields", []))
        preferred_anchor = {
            "supplier": "Supplier",
            "customer": "Customer",
            "business_partner": "BusinessPartner",
        }.get(object_type, "")
        if preferred_anchor and anchor_object == preferred_anchor:
            score += 9.0
        elif anchor_object == "BusinessPartner" and preferred_anchor:
            score -= 2.0
        if target_field and target_field in requested_fields:
            score += 6.0
        target_entity_set = str(path_candidate.get("target_entity_set", path_candidate.get("entity_set", "")))
        if len(path_candidate.get("steps", []) or []) > 1:
            score += 2.0
        return score

    def _choose_entity(self, documents: list[RetrievedDocument], snapshot, intent: dict) -> dict | None:
        bundle = self._build_recall_bundle(snapshot, documents, intent)
        if bundle["best_entity"] is not None:
            return bundle["best_entity"]
        return self._choose_entity_from_documents(documents, snapshot, intent)

    def _choose_entity_from_documents(self, documents: list[RetrievedDocument], snapshot, intent: dict) -> dict | None:
        candidate_scores: dict[str, float] = {}
        candidate_meta: dict[str, dict] = {}
        for doc in documents:
            if doc.source not in {
                "entity-hint",
                "entity",
                "business-term",
                "field",
                "field-exact",
                "field-vector",
                "lookup-path",
                "lookup-path-vector",
            }:
                continue
            meta = doc.metadata or {}
            entity_set = meta.get("mapped_entity_set", "") if doc.source == "business-term" else meta.get("entity_set", "")
            entity_set = entity_set or doc.title.split(".", 1)[0]
            if not entity_set:
                continue
            entity_meta = self._lookup_entity(snapshot, entity_set) or {
                "service_name": self.service_name,
                "entity_set": entity_set,
                "key_fields": [],
                "default_select_fields": [],
                "supported_methods": ["GET"],
                "description": "",
            }
            candidate_meta[entity_set] = entity_meta
            candidate_scores[entity_set] = candidate_scores.get(entity_set, 0.0) + doc.score
        if not candidate_scores and snapshot is not None:
            for entity in snapshot.entities:
                candidate_meta[entity["entity_set"]] = entity
                candidate_scores[entity["entity_set"]] = 0.1
        if snapshot is not None:
            seeds = {
                "customer": ["A_Customer", "A_BusinessPartner"],
                "supplier": ["A_Supplier", "A_BusinessPartner"],
                "business_partner": ["A_BusinessPartner"],
            }.get(intent["object_type"], [])
            for entity_set in seeds:
                entity = self._lookup_entity(snapshot, entity_set)
                if entity is not None:
                    candidate_meta[entity_set] = entity
                    candidate_scores[entity_set] = candidate_scores.get(entity_set, 0.0) + 2.5
        best_entity, best_score = None, float("-inf")
        for entity_set, base_score in candidate_scores.items():
            entity = candidate_meta[entity_set]
            fields = self._get_entity_fields(snapshot, entity_set)
            field_names = {field.get("field_name", "") for field in fields}
            score = min(base_score, 15.0)
            if intent["object_type"] == "customer":
                score += (7.0 if "Customer" in field_names else 0.0) + (5.0 if "Customer" in entity_set else 0.0)
            if intent["object_type"] == "supplier":
                score += (7.0 if "Supplier" in field_names else 0.0) + (5.0 if "Supplier" in entity_set else 0.0)
            if intent["object_type"] == "business_partner":
                score += (7.0 if "BusinessPartner" in field_names else 0.0) + (5.0 if "BusinessPartner" in entity_set else 0.0)
            for requested_field in intent["requested_exact_fields"]:
                if requested_field in field_names:
                    score += 6.0
            if intent["context_scope"] == "purchasing_org":
                score += 8.0 if "PurchasingOrganization" in field_names or "PurchasingOrg" in entity_set else -2.0
            if intent["context_scope"] == "company_code":
                score += 8.0 if "CompanyCode" in field_names or "Company" in entity_set else -2.0
            if entity_set in self.ROOT_ENTITIES:
                score += 3.5
            score -= max(0, len(entity.get("key_fields", [])) - 1) * 2.0
            if intent["needs_basic_profile"]:
                score += 6.0 if self._has_name_field(fields) else 0.0
                score += 1.0 if self._has_contact_field(fields) else 0.0
            for suffix, penalty in self.ENTITY_SUFFIX_PENALTIES.items():
                if suffix in entity_set and suffix.lower() not in intent["normalized_query"]:
                    score -= penalty
            if method_not_supported(entity, intent["method"]):
                score -= 6.0
            if score > best_score:
                best_entity, best_score = entity, score
        return best_entity

    @staticmethod
    def _collect_path_candidates(documents: list[RetrievedDocument]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for doc in documents:
            if doc.source not in {"lookup-path", "lookup-path-vector"}:
                continue
            meta = doc.metadata or {}
            path_id = meta.get("path_id", "") or doc.title
            if not path_id or path_id in seen:
                continue
            seen.add(path_id)
            candidates.append(
                {
                    "path_id": path_id,
                    "anchor_object": meta.get("anchor_object", ""),
                    "target_entity_set": meta.get("target_entity_set", meta.get("entity_set", "")),
                    "target_field": meta.get("target_field", meta.get("field_name", "")),
                    "path_kind": meta.get("path_kind", "lookup"),
                    "return_object": meta.get("return_object", ""),
                    "filter_fields": meta.get("filter_fields", []),
                    "result_fields": meta.get("result_fields", []),
                    "description": meta.get("description", ""),
                    "score": round(doc.score, 4),
                    "confidence": float(meta.get("confidence", 0.0)),
                    "steps": meta.get("steps", []),
                    "business_aliases": meta.get("business_aliases", []),
                    "source": doc.source,
                }
            )
        return sorted(candidates, key=lambda item: item.get("score", 0.0), reverse=True)

    def _recall_field_candidates(self, snapshot, documents: list[RetrievedDocument], intent: dict, top_k: int = 24) -> list[dict[str, Any]]:
        if snapshot is None:
            return []
        query = intent["raw_query"]
        query_terms = self._extract_query_terms(query)
        document_bias = self._build_document_bias(documents)
        candidates: list[dict[str, Any]] = []
        for field in snapshot.fields:
            score, reasons = self._score_field_candidate(field, query_terms, intent, document_bias)
            if score <= 0:
                continue
            candidates.append(
                {
                    "entity_set": field.get("entity_set", ""),
                    "field_name": field.get("field_name", ""),
                    "label": field.get("label", ""),
                    "business_aliases": field.get("business_aliases", []),
                    "description": field.get("description", "") or field.get("label", ""),
                    "filterable": field.get("filterable", False),
                    "score": round(score, 3),
                    "reasons": reasons[:4],
                }
            )
        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates[:top_k]

    def _top_answer_field_candidates(
        self,
        field_candidates: list[dict[str, Any]],
        intent: dict,
    ) -> list[dict[str, Any]]:
        filter_fields = set(intent["preferred_filter_fields"])
        requested_fields = set(intent["requested_exact_fields"])
        exact = [candidate for candidate in field_candidates if candidate.get("field_name") in requested_fields]
        if exact:
            return exact + [candidate for candidate in field_candidates if candidate.get("field_name") not in requested_fields]
        preferred = [candidate for candidate in field_candidates if candidate.get("field_name") not in filter_fields]
        return preferred or field_candidates

    def _rank_entities_from_candidates(
        self,
        snapshot,
        documents: list[RetrievedDocument],
        intent: dict,
        field_candidates: list[dict[str, Any]],
        top_k: int = 8,
    ) -> list[dict[str, Any]]:
        if snapshot is None:
            return []
        entity_scores: dict[str, float] = {}
        for candidate in field_candidates:
            entity_set = candidate.get("entity_set", "")
            if not entity_set:
                continue
            entity_scores[entity_set] = entity_scores.get(entity_set, 0.0) + float(candidate.get("score", 0.0))

        for doc in documents:
            meta = doc.metadata or {}
            entity_set = meta.get("mapped_entity_set", "") if doc.source == "business-term" else meta.get("entity_set", "")
            entity_set = entity_set or doc.title.split(".", 1)[0]
            if not entity_set:
                continue
            entity_scores[entity_set] = entity_scores.get(entity_set, 0.0) + min(doc.score, 10.0)

        requested_fields = set(intent["requested_exact_fields"])
        focus_candidates = self._top_answer_field_candidates(field_candidates, intent)[:6]
        for candidate in focus_candidates:
            entity_set = candidate.get("entity_set", "")
            field_name = candidate.get("field_name", "")
            if not entity_set or not field_name:
                continue
            field_score = float(candidate.get("score", 0.0))
            entity_scores[entity_set] = entity_scores.get(entity_set, 0.0) + min(field_score, 24.0) * 0.7
            owner_entities = {
                field.get("entity_set", "")
                for field in snapshot.fields
                if field.get("field_name", "") == field_name
            }
            owner_entities.discard("")
            if field_name in requested_fields and owner_entities:
                rarity_bonus = 0.0
                if len(owner_entities) == 1:
                    rarity_bonus = 12.0
                elif len(owner_entities) == 2:
                    rarity_bonus = 7.0
                elif len(owner_entities) <= 4:
                    rarity_bonus = 3.5
                if rarity_bonus:
                    entity_scores[entity_set] = entity_scores.get(entity_set, 0.0) + rarity_bonus

        ranked: list[tuple[float, dict]] = []
        for entity in snapshot.entities:
            entity_set = entity.get("entity_set", "")
            if not entity_set:
                continue
            score = entity_scores.get(entity_set, 0.0)
            fields = self._get_entity_fields(snapshot, entity_set)
            field_names = {field.get("field_name", "") for field in fields}
            if intent["object_type"] == "supplier":
                score += 8.0 if "Supplier" in field_names else -1.0
                score += 5.0 if "Supplier" in entity_set else 0.0
            if intent["object_type"] == "customer":
                score += 8.0 if "Customer" in field_names else -1.0
                score += 5.0 if "Customer" in entity_set else 0.0
            if intent["object_type"] == "business_partner":
                score += 8.0 if "BusinessPartner" in field_names else -1.0
                score += 5.0 if "BusinessPartner" in entity_set else 0.0
            if intent["context_scope"] == "purchasing_org":
                score += 8.0 if "PurchasingOrganization" in field_names or "PurchasingOrg" in entity_set else -2.0
            if intent["context_scope"] == "company_code":
                score += 8.0 if "CompanyCode" in field_names or "Company" in entity_set else -2.0
            for requested_field in intent["requested_exact_fields"]:
                if requested_field in field_names:
                    score += 8.0
            if any(
                candidate.get("entity_set") == entity_set and candidate.get("field_name") in requested_fields
                for candidate in focus_candidates
            ):
                score += 6.0
            if entity_set in self.ROOT_ENTITIES:
                score += 2.0
                if requested_fields:
                    unmatched_requested = [field_name for field_name in requested_fields if field_name not in field_names]
                    if unmatched_requested:
                        score -= 7.0
            score -= max(0, len(entity.get("key_fields", [])) - 1) * 1.5
            if score > 0:
                ranked.append((score, {**entity, "available_fields": sorted(field_names)}))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [entity for _, entity in ranked[:top_k]]

    def _score_field_candidate(
        self,
        field: dict[str, Any],
        query_terms: dict[str, Any],
        intent: dict,
        document_bias: dict[str, float],
    ) -> tuple[float, list[str]]:
        field_name = field.get("field_name", "")
        entity_set = field.get("entity_set", "")
        aliases = [field_name, self._split_camel_case(field_name), field.get("label", ""), field.get("description", "")]
        aliases.extend(field.get("business_aliases", []))
        aliases.extend([entity_set, self._split_camel_case(entity_set)])
        normalized_aliases = [self._normalize_phrase(alias) for alias in aliases if alias]
        normalized_aliases = [alias for alias in normalized_aliases if alias]
        score = 0.0
        reasons: list[str] = []
        query_text = query_terms["normalized_query"]
        query_compact = query_terms["compact_query"]

        for alias in normalized_aliases:
            if alias and alias in query_text:
                score += 12.0 + min(len(alias) * 0.08, 2.0)
                reasons.append(f"exact:{alias}")
            compact_alias = alias.replace(" ", "")
            if compact_alias and compact_alias in query_compact and len(compact_alias) >= 4:
                score += 9.0
                reasons.append(f"compact:{compact_alias}")

        for query_phrase in query_terms["phrases"]:
            for alias in normalized_aliases:
                ratio = SequenceMatcher(None, query_phrase, alias).ratio()
                if ratio >= 0.88:
                    score += 8.0 * ratio
                    reasons.append(f"phrase:{query_phrase}->{alias}")

        alias_tokens: set[str] = set()
        for alias in normalized_aliases:
            alias_tokens.update(token for token in alias.split() if len(token) >= 2)
        for query_token in query_terms["tokens"]:
            if query_token in alias_tokens:
                score += 4.5
                reasons.append(f"token:{query_token}")
                continue
            best_ratio = max((SequenceMatcher(None, query_token, alias_token).ratio() for alias_token in alias_tokens), default=0.0)
            if best_ratio >= 0.84:
                score += 3.5 * best_ratio
                reasons.append(f"fuzzy:{query_token}")

        entity_bias = document_bias.get(entity_set, 0.0)
        field_bias = document_bias.get(f"{entity_set}.{field_name}", 0.0)
        score += min(entity_bias, 12.0) * 0.08 + min(field_bias, 12.0) * 0.35
        if entity_bias or field_bias:
            reasons.append("retrieval-bias")

        if intent["object_type"] == "supplier":
            if "Supplier" in entity_set or "Supplier" in field_name:
                score += 2.5
            elif "Customer" in entity_set:
                score -= 1.0
        if intent["object_type"] == "customer":
            if "Customer" in entity_set or "Customer" in field_name:
                score += 2.5
            elif "Supplier" in entity_set:
                score -= 1.0
        if intent["context_scope"] == "purchasing_org":
            if entity_set.endswith("PurchasingOrg") or "PurchasingOrganization" in normalized_aliases:
                score += 4.0
            elif "CompanyCode" in field_name:
                score -= 1.0
        if intent["context_scope"] == "company_code":
            if entity_set.endswith("Company") or "CompanyCode" in field_name:
                score += 4.0
            elif "PurchasingOrganization" in field_name:
                score -= 1.0
        if intent["requested_exact_fields"] and field_name in intent["requested_exact_fields"]:
            score += 10.0
            reasons.append("semantic-hint")
        return score, reasons

    @staticmethod
    def _build_document_bias(documents: list[RetrievedDocument]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for doc in documents:
            meta = doc.metadata or {}
            entity_set = meta.get("mapped_entity_set", "") if doc.source == "business-term" else meta.get("entity_set", "")
            entity_set = entity_set or doc.title.split(".", 1)[0]
            mapped_fields = meta.get("mapped_fields") or []
            field_name = mapped_fields[0] if doc.source == "business-term" and mapped_fields else meta.get("field_name", "")
            if entity_set:
                scores[entity_set] = max(scores.get(entity_set, 0.0), doc.score)
            if entity_set and field_name:
                scores[f"{entity_set}.{field_name}"] = max(scores.get(f"{entity_set}.{field_name}", 0.0), doc.score)
        return scores

    @staticmethod
    def _build_planner_diagnostics(
        recall_bundle: dict[str, Any],
        strategy: str,
        constraints: QueryConstraints | None = None,
        request: AgentRequest | None = None,
    ) -> dict[str, Any]:
        return {
            "recall_strategy": strategy,
            "field_candidates": recall_bundle.get("field_candidates", [])[:12],
            "path_candidates": recall_bundle.get("path_candidates", [])[:8],
            "entity_candidates": [
                {
                    "entity_set": entity.get("entity_set", ""),
                    "description": entity.get("description", ""),
                    "key_fields": entity.get("key_fields", []),
                }
                for entity in recall_bundle.get("entity_candidates", [])[:8]
            ],
            "ranked_candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "candidate_type": candidate.candidate_type,
                    "entity_set": candidate.entity_set,
                    "path_id": candidate.path_id,
                    "target_field": candidate.target_field,
                    "target_entity_set": candidate.target_entity_set,
                    "hard_constraints_passed": candidate.hard_constraints_passed,
                    "hard_fail_reasons": candidate.hard_fail_reasons,
                    "scores": candidate.scores,
                    "final_score": candidate.final_score,
                }
                for candidate in recall_bundle.get("ranked_candidates", [])[:8]
            ],
            "query_shape": constraints.query_shape.value if constraints else None,
            "cardinality_policy": constraints.cardinality.value if constraints else None,
            "constraints": {
                "target_object": constraints.target_object,
                "target_field_concepts": constraints.target_field_concepts,
                "filter_concepts": constraints.filter_concepts,
                "filter_values": constraints.filter_values,
                "name_match_mode": constraints.name_match_mode,
                "boolean_intent": constraints.boolean_intent,
            }
            if constraints
            else None,
            "context_carry_decision": (
                {
                    "should_carry": request.context_carry_decision.should_carry,
                    "reason": request.context_carry_decision.reason,
                    "confidence": request.context_carry_decision.confidence,
                }
                if request and request.context_carry_decision
                else None
            ),
        }

    def _extract_query_terms(self, query: str) -> dict[str, Any]:
        normalized_query = self._normalize_phrase(query)
        tokens = [token for token in normalized_query.split() if len(token) >= 2]
        english_chunks = [self._normalize_phrase(chunk) for chunk in re.findall(r"[A-Za-z][A-Za-z0-9 ]+", query)]
        chinese_chunks = [self._normalize_phrase(chunk) for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", query)]
        phrases = [phrase for phrase in [*english_chunks, *chinese_chunks] if phrase]
        return {
            "normalized_query": normalized_query,
            "compact_query": normalized_query.replace(" ", ""),
            "tokens": tokens,
            "phrases": phrases,
        }

    @staticmethod
    def _normalize_phrase(text: str) -> str:
        lowered = RetrievalAwareIntentPlanner._split_camel_case(str(text or "")).lower()
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", lowered).strip()

    @staticmethod
    def _split_camel_case(text: str) -> str:
        value = str(text or "")
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        value = value.replace("_", " ")
        return value

    def _choose_filter_field(self, entity: dict, fields: list[dict], intent: dict) -> str | None:
        if not intent["identifier_value"]:
            return None
        field_names = {field.get("field_name", "") for field in fields}
        for preferred in intent["preferred_filter_fields"]:
            if preferred in field_names:
                return preferred
        if len(entity.get("key_fields", [])) == 1:
            return entity["key_fields"][0]
        for field_name in ("BusinessPartner", "Customer", "Supplier", "SalesOrder"):
            if field_name in field_names:
                return field_name
        return None

    @staticmethod
    def _choose_constraint_filter_field(fields: list[dict], constraints: QueryConstraints) -> str | None:
        if not constraints.filter_concepts:
            return None
        field_names = {field.get("field_name", "") for field in fields}
        for concept in constraints.filter_concepts:
            if concept in field_names:
                return concept
        return None

    def _build_filters(
        self,
        filter_field: str | None,
        intent: dict,
        constraints: QueryConstraints | None = None,
    ) -> list[FilterCondition]:
        active_constraints = constraints or self._constraints_from_intent(intent)
        literal_value = self._resolve_primary_filter_value(intent, active_constraints)
        if active_constraints.name_match_mode == "contains":
            if filter_field and literal_value:
                return [FilterCondition(field=filter_field, operator="contains", value=literal_value)]
        if not filter_field or not literal_value:
            return []
        return [FilterCondition(field=filter_field, operator="eq", value=literal_value)]

    @staticmethod
    def _resolve_primary_filter_value(intent: dict, constraints: QueryConstraints) -> str | None:
        non_numeric = [value for value in constraints.filter_values if not value.isdigit()]
        if constraints.name_match_mode == "contains" and non_numeric:
            return non_numeric[0]
        if intent.get("identifier_value"):
            return intent["identifier_value"]
        if non_numeric:
            return non_numeric[0]
        return next((value for value in constraints.filter_values if value), None)

    @staticmethod
    def _resolve_top(constraints: QueryConstraints, filters: list[FilterCondition]) -> int:
        if constraints.cardinality == CardinalityPolicy.MANY:
            return 50
        return 1 if filters else 20

    @staticmethod
    def _constraints_from_intent(intent: dict) -> QueryConstraints:
        if intent.get("wants_multiple_rows"):
            query_shape = QueryShape.LIST_QUERY
            cardinality = CardinalityPolicy.MANY
        else:
            query_shape = QueryShape.SINGLE_FACT
            cardinality = CardinalityPolicy.ONE
        return QueryConstraints(
            query_shape=query_shape,
            cardinality=cardinality,
            target_object=intent.get("object_type"),
            target_field_concepts=list(intent.get("requested_exact_fields", [])),
            filter_concepts=list(intent.get("preferred_filter_fields", [])),
            filter_values=[intent.get("identifier_value")] if intent.get("identifier_value") else [],
            requested_operation="read" if intent.get("method") == "GET" else "write",
            boolean_intent=False,
        )

    def _choose_select_fields(
        self,
        entity: dict,
        fields: list[dict],
        intent: dict,
        filter_field: str | None,
        field_candidates: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        field_map = {field.get("field_name", ""): field for field in fields}
        selected: list[str] = []

        def add(field_name: str) -> None:
            if field_name and field_name in field_map and field_name not in selected:
                selected.append(field_name)

        for field_name in entity.get("key_fields", []):
            add(field_name)
        add(filter_field or "")
        for field_name in intent["requested_exact_fields"]:
            add(field_name)
        if field_candidates:
            for candidate in field_candidates:
                if candidate.get("entity_set") != entity.get("entity_set"):
                    continue
                add(candidate.get("field_name", ""))
                if len(selected) >= 6:
                    break
        if intent["needs_basic_profile"] or intent["requested_field_groups"]:
            for field_name in self._pick_semantic_fields(field_map, intent):
                add(field_name)
        if not selected:
            for field_name in entity.get("default_select_fields", []):
                add(field_name)
        if not selected:
            for field_name in sorted(field_map.keys()):
                add(field_name)
                if len(selected) >= 5:
                    break
        for field_name in entity.get("default_select_fields", []):
            add(field_name)
            if len(selected) >= 8:
                break
        return selected[:8]

    @staticmethod
    def _apply_constraint_target_fields(
        select_fields: list[str],
        fields: list[dict],
        constraints: QueryConstraints | None,
    ) -> list[str]:
        if constraints is None or not constraints.target_field_concepts:
            return select_fields
        field_names = {field.get("field_name", "") for field in fields}
        merged = list(select_fields)
        required_fields = [
            field_name
            for field_name in constraints.target_field_concepts
            if field_name in field_names
        ]
        for field_name in constraints.target_field_concepts:
            if field_name in field_names and field_name not in merged:
                merged.append(field_name)
        if len(merged) <= 8:
            return merged
        limited = merged[:8]
        for field_name in required_fields:
            if field_name in limited:
                continue
            for index in range(len(limited) - 1, -1, -1):
                if limited[index] not in required_fields:
                    limited.pop(index)
                    break
            limited.append(field_name)
        return limited

    def _pick_semantic_fields(self, field_map: dict[str, dict], intent: dict) -> list[str]:
        results: list[str] = []
        ordered = list(field_map.keys())
        if intent["needs_basic_profile"]:
            for pattern in ("Name", "FullName", "Category", "Grouping", "Customer", "Supplier", "BusinessPartner"):
                for field_name in ordered:
                    if pattern in field_name and field_name not in results:
                        results.append(field_name)
        for group in intent["requested_field_groups"]:
            for preferred_field in self.FIELD_GROUP_TARGETS.get(group, ()):
                if preferred_field in field_map and preferred_field not in results:
                    results.append(preferred_field)
        return results[:6]

    def _analyze_query(self, query: str) -> dict:
        lowered = query.lower()
        numbers = re.findall(r"\d{4,}", query)
        method = "GET"
        for candidate_method, hints in self.ACTION_HINTS.items():
            if any(hint in lowered or hint in query for hint in hints):
                method = candidate_method
                break
        object_type = "generic"
        if any(token in lowered or token in query for token in self.ENTITY_HINTS["customer"]):
            object_type = "customer"
        elif any(token in lowered or token in query for token in self.ENTITY_HINTS["supplier"]):
            object_type = "supplier"
        elif any(token in lowered or token in query for token in self.ENTITY_HINTS["business_partner"]):
            object_type = "business_partner"
        preferred_fields = {
            "customer": ["Customer", "BusinessPartner"],
            "supplier": ["Supplier", "BusinessPartner"],
            "business_partner": ["BusinessPartner", "Customer", "Supplier"],
            "generic": ["BusinessPartner", "Customer", "Supplier"],
        }[object_type]
        requested_groups = {
            group
            for group, hints in self.FIELD_HINTS.items()
            if any(hint in lowered or hint in query for hint in hints)
        }
        requested_exact_fields = [
            field_name
            for group in requested_groups
            for field_name in self.FIELD_GROUP_TARGETS.get(group, ())
        ]
        context_scope = next(
            (
                scope
                for scope, hints in self.CONTEXT_HINTS.items()
                if any(hint in lowered or hint in query for hint in hints)
            ),
            None,
        )
        return {
            "raw_query": query,
            "normalized_query": lowered,
            "identifier_value": max(numbers, key=len) if numbers else None,
            "method": method,
            "object_type": object_type,
            "preferred_filter_fields": preferred_fields,
            "requested_field_groups": requested_groups,
            "requested_exact_fields": requested_exact_fields,
            "context_scope": context_scope,
            "needs_basic_profile": any(term in query for term in self.BASIC_PROFILE_HINTS) or "basic" in lowered,
            "wants_multiple_rows": any(term in lowered or term in query for term in self.MULTI_ROW_HINTS),
            "expects_boolean_answer": any(term in query for term in ("吗", "是否", "是不是", "有无", "对吗")),
        }

    @staticmethod
    def _lookup_entity(snapshot, entity_set: str) -> dict | None:
        if snapshot is None:
            return None
        return next((entity for entity in snapshot.entities if entity.get("entity_set") == entity_set), None)

    @staticmethod
    def _get_entity_fields(snapshot, entity_set: str) -> list[dict]:
        if snapshot is None:
            return []
        return [field for field in snapshot.fields if field.get("entity_set") == entity_set]

    @staticmethod
    def _has_name_field(fields: list[dict]) -> bool:
        return any("Name" in field.get("field_name", "") for field in fields)

    @staticmethod
    def _has_contact_field(fields: list[dict]) -> bool:
        return any(
            token in field.get("field_name", "")
            for field in fields
            for token in ("Phone", "Email", "Address", "Telephone", "Mobile")
        )


class LlmStructuredIntentPlanner(RetrievalAwareIntentPlanner):
    def __init__(
        self,
        index_root: str = "data/index",
        service_name: str = "API_BUSINESS_PARTNER",
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(index_root=index_root, service_name=service_name)
        self.llm_client = llm_client
        self.enabled = enabled

    def plan(self, request: AgentRequest, context: RetrievedContext) -> QueryPlan:
        fallback_plan = super().plan(request, context)
        fallback_snapshot = self._plan_to_dict(fallback_plan)
        snapshot = self._load_snapshot()
        if not self.enabled or self.llm_client is None or snapshot is None:
            return replace(
                fallback_plan,
                planner_diagnostics={
                    **fallback_plan.planner_diagnostics,
                    "fallback_plan_snapshot": fallback_snapshot,
                    "llm_plan_snapshot": None,
                    "planner_winner": "fallback",
                    "llm_adjudication": {"accepted": False, "reasons": ["llm_unavailable"]},
                },
            )
        candidate_payload = self._build_candidate_payload(request, context.documents, snapshot)
        if not candidate_payload["entities"]:
            return replace(
                fallback_plan,
                planner_diagnostics={
                    **fallback_plan.planner_diagnostics,
                    "fallback_plan_snapshot": fallback_snapshot,
                    "llm_plan_snapshot": None,
                    "planner_winner": "fallback",
                    "llm_adjudication": {"accepted": False, "reasons": ["no_entity_candidates"]},
                },
            )
        try:
            parsed = self._request_structured_plan(
                self._get_working_input(request),
                candidate_payload,
                fallback_plan,
                request.feedback_hints,
            )
            materialized = self._materialize_plan(request, parsed, snapshot, fallback_plan)
            llm_snapshot = self._plan_to_dict(materialized) if materialized is not None else None
            accepted, adjudication_reasons = self._accept_llm_plan(request, materialized, fallback_plan, candidate_payload)
            if materialized is not None and accepted:
                return replace(
                    materialized,
                    planner_diagnostics={
                        **materialized.planner_diagnostics,
                        "fallback_plan_snapshot": fallback_snapshot,
                        "llm_plan_snapshot": llm_snapshot,
                        "planner_winner": "llm",
                        "llm_adjudication": {"accepted": True, "reasons": adjudication_reasons},
                    },
                )
            if materialized is not None:
                return replace(
                    fallback_plan,
                    rationale=f"{fallback_plan.rationale} LLM plan was rejected by recall guardrail; fallback recall plan kept.",
                    planner_diagnostics={
                        **fallback_plan.planner_diagnostics,
                        "fallback_plan_snapshot": fallback_snapshot,
                        "llm_plan_snapshot": llm_snapshot,
                        "llm_candidate_payload": candidate_payload,
                        "llm_guardrail": "rejected_llm_plan",
                        "planner_winner": "fallback",
                        "llm_adjudication": {"accepted": False, "reasons": adjudication_reasons},
                    },
                )
        except Exception as exc:
            return replace(
                fallback_plan,
                rationale=f"{fallback_plan.rationale} LLM planner fallback was used after client error: {exc}",
                planner_diagnostics={
                    **fallback_plan.planner_diagnostics,
                    "fallback_plan_snapshot": fallback_snapshot,
                    "llm_plan_snapshot": None,
                    "llm_candidate_payload": candidate_payload,
                    "llm_guardrail": f"client_error:{exc}",
                    "planner_winner": "fallback",
                    "llm_adjudication": {"accepted": False, "reasons": [f"client_error:{exc}"]},
                },
            )
        return replace(
            fallback_plan,
            rationale=f"{fallback_plan.rationale} LLM planner fallback was used because the JSON output was invalid.",
            planner_diagnostics={
                **fallback_plan.planner_diagnostics,
                "fallback_plan_snapshot": fallback_snapshot,
                "llm_plan_snapshot": None,
                "llm_candidate_payload": candidate_payload,
                "llm_guardrail": "invalid_json",
                "planner_winner": "fallback",
                "llm_adjudication": {"accepted": False, "reasons": ["invalid_json"]},
            },
        )

    def _accept_llm_plan(
        self,
        request: AgentRequest,
        materialized: QueryPlan | None,
        fallback_plan: QueryPlan,
        candidate_payload: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        if materialized is None:
            return False, ["materialized_plan_missing"]
        required_fields = set((request.constraints.target_field_concepts if request.constraints else []) or [])
        required_filter_fields = set((request.constraints.filter_concepts if request.constraints else []) or [])
        required_filter_values = set((request.constraints.filter_values if request.constraints else []) or [])
        materialized_selected_fields = self._plan_selected_fields(materialized)
        materialized_filter_fields = self._plan_filter_fields(materialized)
        materialized_filter_values = self._plan_filter_values(materialized)
        if required_fields:
            fallback_has_required = bool(required_fields.intersection(self._plan_selected_fields(fallback_plan)))
            llm_has_required = bool(required_fields.intersection(materialized_selected_fields))
            if fallback_has_required and not llm_has_required:
                return False, ["required_target_field_lost"]
            if not llm_has_required:
                return False, ["required_target_field_missing"]
        if required_filter_fields:
            if not required_filter_fields.intersection(materialized_filter_fields):
                return False, ["required_filter_field_lost"]
        if required_filter_values:
            if not required_filter_values.intersection(materialized_filter_values):
                return False, ["required_filter_value_lost"]
        top_answer_candidates = candidate_payload.get("answer_field_candidates", []) or []
        if not top_answer_candidates:
            return True, ["no_strong_answer_field_candidate"]
        strongest = top_answer_candidates[0]
        strongest_score = float(strongest.get("score", 0.0))
        if strongest_score < 12.0:
            return True, ["top_answer_field_confidence_low"]
        strongest_field = strongest.get("field_name", "")
        strongest_entity = strongest.get("entity_set", "")
        llm_has_field = strongest_field in materialized_selected_fields
        fallback_has_field = strongest_field in self._plan_selected_fields(fallback_plan) and fallback_plan.entity_set == strongest_entity
        if llm_has_field:
            return True, ["llm_preserved_strong_answer_field"]
        if fallback_has_field:
            return False, ["strong_answer_field_ignored_by_llm"]
        return True, ["llm_plan_accepted"]

    @staticmethod
    def _plan_selected_fields(plan: QueryPlan) -> set[str]:
        fields = set(plan.select_fields or [])
        fields.update(plan.response_summary_fields or [])
        for step in plan.steps or []:
            fields.update(step.select_fields or [])
            fields.update(step.response_summary_fields or [])
        return fields

    @staticmethod
    def _plan_filter_fields(plan: QueryPlan) -> set[str]:
        fields = {condition.field for condition in plan.filters or []}
        for step in plan.steps or []:
            fields.update(condition.field for condition in step.filters or [])
            fields.update(binding.field for binding in step.filter_from_previous or [])
        return fields

    @staticmethod
    def _plan_filter_values(plan: QueryPlan) -> set[str]:
        values = {condition.value for condition in plan.filters or []}
        for step in plan.steps or []:
            values.update(condition.value for condition in step.filters or [])
        return values

    def _build_candidate_payload(self, request: AgentRequest, documents: list[RetrievedDocument], snapshot) -> dict[str, Any]:
        intent = self._analyze_query(self._get_working_input(request))
        recall_bundle = self._build_recall_bundle(snapshot, documents, intent)
        constraints = request.constraints or self._constraints_from_intent(intent)
        dynamic_paths = [
            *self._synthesize_bridge_paths(snapshot, recall_bundle, constraints),
            *self._synthesize_attribute_filter_paths(snapshot, recall_bundle, constraints),
        ]
        if dynamic_paths:
            recall_bundle["path_candidates"] = [*dynamic_paths, *recall_bundle.get("path_candidates", [])]
        field_details = {
            (field.get("entity_set", ""), field.get("field_name", "")): field
            for field in snapshot.fields
        }
        entities_payload: list[dict[str, Any]] = []
        for entity in recall_bundle["entity_candidates"][:8]:
            entity_set = entity.get("entity_set", "")
            highlighted = [
                {
                    "field_name": candidate.get("field_name", ""),
                    "description": candidate.get("description", ""),
                    "filterable": candidate.get("filterable", False),
                    "score": candidate.get("score", 0.0),
                    "reasons": candidate.get("reasons", []),
                }
                for candidate in recall_bundle["field_candidates"]
                if candidate.get("entity_set") == entity_set
            ][:8]
            entities_payload.append(
                {
                    "entity_set": entity_set,
                    "description": entity.get("description", ""),
                    "key_fields": entity.get("key_fields", []),
                    "supported_methods": entity.get("supported_methods", []),
                    "default_select_fields": entity.get("default_select_fields", []),
                    "highlighted_fields": highlighted,
                }
            )
        fields_payload = recall_bundle["field_candidates"][:24]
        path_payload = recall_bundle.get("path_candidates", [])[:10]
        answer_field_candidates = self._top_answer_field_candidates(fields_payload, intent)[:12]
        filter_field_candidates = [
            candidate
            for candidate in fields_payload
            if candidate.get("field_name") in set(intent["preferred_filter_fields"])
        ][:6]
        snippets = [
            {"source": doc.source, "title": doc.title, "content": doc.content[:320], "score": round(doc.score, 3)}
            for doc in documents[:8]
        ]
        ambiguity_hints = self._build_ambiguity_hints(fields_payload, field_details)
        payload = {
            "entities": entities_payload,
            "fields": fields_payload,
            "path_candidates": path_payload,
            "answer_field_candidates": answer_field_candidates,
            "filter_field_candidates": filter_field_candidates,
            "ambiguity_hints": ambiguity_hints,
            "snippets": snippets,
            "semantic_frame": request.semantic_frame,
            "schema_rerank": request.schema_rerank,
            "feedback_memories": request.feedback_memories,
            "recall_strategy": "hybrid_keyword_vector_recall",
        }
        if self._is_low_confidence_recall(recall_bundle["field_candidates"], recall_bundle["entity_candidates"]):
            payload["expanded_schema"] = self._build_expanded_schema(snapshot, recall_bundle["entity_candidates"])
        return payload

    def _is_low_confidence_recall(
        self,
        field_candidates: list[dict[str, Any]],
        entity_candidates: list[dict[str, Any]],
    ) -> bool:
        if not field_candidates or not entity_candidates:
            return True
        top_field = float(field_candidates[0].get("score", 0.0))
        second_field = float(field_candidates[1].get("score", 0.0)) if len(field_candidates) > 1 else 0.0
        return top_field < 10.0 or (top_field - second_field) < 1.5

    def _build_expanded_schema(self, snapshot, entity_candidates: list[dict[str, Any]], top_k: int = 10) -> list[dict[str, Any]]:
        entities = entity_candidates[:top_k] if entity_candidates else snapshot.entities[:top_k]
        results: list[dict[str, Any]] = []
        for entity in entities:
            entity_set = entity.get("entity_set", "")
            fields = self._get_entity_fields(snapshot, entity_set)
            results.append(
                {
                    "entity_set": entity_set,
                    "description": entity.get("description", ""),
                    "key_fields": entity.get("key_fields", []),
                    "fields": [
                        {
                            "field_name": field.get("field_name", ""),
                            "label": field.get("label", ""),
                            "description": field.get("description", "") or field.get("label", ""),
                            "business_aliases": field.get("business_aliases", [])[:6],
                        }
                        for field in fields[:24]
                    ],
                }
            )
        return results

    @staticmethod
    def _build_ambiguity_hints(
        fields_payload: list[dict[str, Any]],
        field_details: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        concept_map: dict[str, dict[str, Any]] = {}
        for field in fields_payload:
            entity_set = field.get("entity_set", "")
            field_name = field.get("field_name", "")
            detail = field_details.get((entity_set, field_name), {})
            labels = [
                field.get("label", ""),
                *field.get("business_aliases", []),
                detail.get("label", ""),
                *detail.get("business_aliases", []),
            ]
            for label in labels:
                normalized = str(label).strip()
                if len(normalized) < 2:
                    continue
                bucket = concept_map.setdefault(
                    normalized,
                    {"concept": normalized, "entities": set(), "field_names": set()},
                )
                bucket["entities"].add(entity_set)
                bucket["field_names"].add(field_name)

        results: list[dict[str, Any]] = []
        for concept, payload in concept_map.items():
            entities = sorted(payload["entities"])
            if len(entities) < 2:
                continue
            results.append(
                {
                    "concept": concept,
                    "entities": entities,
                    "field_names": sorted(payload["field_names"]),
                }
            )
        return sorted(results, key=lambda item: (len(item["entities"]) * -1, item["concept"]))[:8]

    @staticmethod
    def _build_system_prompt() -> str:
        return (
            "You are an SAP OData planning assistant. "
            "Choose the best entity and fields from the provided candidates. "
            "Return JSON only and do not invent entities or fields."
        )

    @staticmethod
    def _build_json_repair_system_prompt() -> str:
        return (
            "You repair malformed JSON generated by another model. "
            "Return one valid JSON object only with no markdown fences and no commentary."
        )

    def _build_user_prompt(
        self,
        user_input: str,
        candidate_payload: dict[str, Any],
        fallback_plan: QueryPlan,
        feedback_hints: list[dict[str, str]] | None = None,
    ) -> str:
        example = {
            "plan_kind": "direct",
            "entity_set": "A_RelevantEntity",
            "http_method": "GET",
            "select_fields": ["IdentifierField", "ContextField", "RequestedField"],
            "response_summary_fields": ["ContextField", "RequestedField"],
            "filters": [{"field": "IdentifierField", "operator": "eq", "value": "literal value from the request"}],
            "path_id": "",
            "target_entity_set": "A_RelevantEntity",
            "target_field": "RequestedField",
            "steps": [],
            "requires_confirmation": False,
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "response_directive": "Answer using the requested field and include available context fields.",
            "rationale": "The selected entity contains the requested field and the required filter field.",
        }
        feedback_section = ""
        if feedback_hints:
            feedback_section = (
                "Historical feedback lessons (reference only, do not let them override the current request or candidate recall):\n"
                f"{json.dumps(feedback_hints, ensure_ascii=False, indent=2)}\n\n"
            )
        return (
            f"User request:\n{user_input}\n\n"
            f"{feedback_section}"
            f"Heuristic fallback plan:\n{json.dumps(self._plan_to_dict(fallback_plan), ensure_ascii=False, indent=2)}\n\n"
            f"Candidate schema context:\n{json.dumps(candidate_payload, ensure_ascii=False, indent=2)}\n\n"
            "Choose the best entity and fields. Prefer specific child entities when the requested business concept only exists there. "
            "Use historical feedback only as a cautionary hint; never let an old issue pull you toward unrelated fields or entities. "
            "Treat filter fields such as Supplier, Customer, and BusinessPartner as identifier fields, not as the answer field, unless the user explicitly asks about those identifiers. "
            "Prioritize answer_field_candidates when deciding what field the user actually wants to know. "
            "Use path_candidates as lookup routes when a direct entity cannot answer the request; set plan_kind=multi_step and output steps only from an existing path candidate. "
            "Select only the fields needed to answer the user's question well, plus any key context fields needed to interpret the answer. "
            "If the request is ambiguous because the same concept exists under multiple business contexts, set needs_clarification to true, "
            "ask a short Chinese clarification question, and provide 2-4 concise clarification_options. "
            "Pay special attention to ambiguity_hints: if the requested concept appears in multiple candidate entities and the user did not specify the missing business dimension, prefer clarification over guessing. "
            "If the user explicitly asks for all values, all contexts, or asks for results respectively, do not ask for a single specific code; return all matching rows instead. "
            "Return JSON only with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    def _build_json_repair_prompt(self, raw_response: str) -> str:
        return (
            "Rewrite the following content into a single valid JSON object. "
            "Preserve the intent, entity, fields, and filters when possible.\n\n"
            f"{raw_response}"
        )

    def _request_structured_plan(
        self,
        user_input: str,
        candidate_payload: dict[str, Any],
        fallback_plan: QueryPlan,
        feedback_hints: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        raw = self._complete_nonempty_json_text(
            self._build_system_prompt(),
            self._build_user_prompt(user_input, candidate_payload, fallback_plan, feedback_hints),
        )
        try:
            return self._parse_json_object(raw)
        except json.JSONDecodeError:
            repaired_raw = self._complete_nonempty_json_text(
                self._build_json_repair_system_prompt(),
                self._build_json_repair_prompt(raw),
                max_tokens=500,
            )
            return self._parse_json_object(repaired_raw)

    def _complete_nonempty_json_text(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 900,
        attempts: int = 2,
    ) -> str:
        last_response = ""
        for _ in range(max(1, attempts)):
            response = self.llm_client.complete_json(system_prompt, user_prompt, max_tokens=max_tokens)
            if response and response.strip():
                return response
            last_response = response
        raise ValueError(f"LLM returned empty content after {max(1, attempts)} attempts: {last_response!r}")

    def _materialize_plan(self, request: AgentRequest, parsed: dict[str, Any], snapshot, fallback_plan: QueryPlan) -> QueryPlan | None:
        if str(parsed.get("plan_kind", "")).lower() in {"lookup", "multi_step"} and isinstance(parsed.get("steps"), list):
            materialized_steps = self._materialize_llm_steps(parsed.get("steps", []), snapshot, fallback_plan)
            if materialized_steps:
                final_step = materialized_steps[-1]
                target_entity_set = str(parsed.get("target_entity_set") or final_step.entity_set)
                target_entity = self._lookup_entity(snapshot, target_entity_set)
                if target_entity is not None:
                    target_field = str(parsed.get("target_field", "") or "") or None
                    return QueryPlan(
                        service_name=target_entity.get("service_name", self.service_name),
                        entity_set=target_entity_set,
                        http_method=str(parsed.get("http_method", fallback_plan.http_method)).upper(),
                        select_fields=final_step.select_fields,
                        response_summary_fields=self._choose_final_summary_fields(final_step.select_fields, target_field),
                        filters=materialized_steps[0].filters,
                        top=final_step.top,
                        requires_confirmation=bool(parsed.get("requires_confirmation", False)),
                        needs_clarification=bool(parsed.get("needs_clarification", False)),
                        clarification_question=parsed.get("clarification_question") or None,
                        clarification_options=[
                            option
                            for option in parsed.get("clarification_options", [])
                            if isinstance(option, str) and option.strip()
                        ][:4],
                        response_directive=str(parsed.get("response_directive", fallback_plan.response_directive) or fallback_plan.response_directive),
                        rationale=f"LLM planner selected multi-step plan. {parsed.get('rationale', fallback_plan.rationale)}",
                        planner_diagnostics={
                            **fallback_plan.planner_diagnostics,
                            "llm_candidate_payload": parsed,
                            "llm_selection": "accepted_multistep",
                        },
                        plan_kind="multi_step",
                        anchor_object=parsed.get("anchor_object") or fallback_plan.anchor_object,
                        anchor_value=parsed.get("anchor_value") or fallback_plan.anchor_value,
                        target_field=target_field,
                        target_entity_set=target_entity_set,
                        path_id=parsed.get("path_id") or fallback_plan.path_id,
                        steps=materialized_steps,
                    )

        needs_clarification = bool(parsed.get("needs_clarification", False))
        entity_set = parsed.get("entity_set")
        if not isinstance(entity_set, str) or not entity_set:
            entity_set = fallback_plan.entity_set if needs_clarification else None
        if not isinstance(entity_set, str):
            return None
        entity = self._lookup_entity(snapshot, entity_set)
        if entity is None:
            if not needs_clarification:
                return None
            entity = self._lookup_entity(snapshot, fallback_plan.entity_set)
            if entity is None:
                return None
            entity_set = entity.get("entity_set", fallback_plan.entity_set)
        method = str(parsed.get("http_method", fallback_plan.http_method)).upper()
        intent = self._analyze_query(self._get_working_input(request))
        fields = self._get_entity_fields(snapshot, entity_set)
        field_map = {field.get("field_name", ""): field for field in fields}
        select_fields = [
            field_name
            for field_name in parsed.get("select_fields", [])
            if isinstance(field_name, str) and field_name in field_map
        ]
        filters = []
        for item in parsed.get("filters", []):
            if not isinstance(item, dict):
                continue
            field_name = item.get("field")
            value = item.get("value")
            if isinstance(field_name, str) and field_name in field_map and value not in (None, ""):
                filters.append(
                    FilterCondition(
                        field=field_name,
                        operator=str(item.get("operator", "eq")),
                        value=str(value),
                        value_type=self._filter_value_type(item, field_map[field_name]),
                    )
                )
        if not filters:
            filter_field = self._choose_constraint_filter_field(fields, request.constraints or self._constraints_from_intent(intent))
            if filter_field is None:
                filter_field = self._choose_filter_field(entity, fields, intent)
            filters = self._build_filters(filter_field, intent, request.constraints)
        if not select_fields and not needs_clarification:
            filter_name = filters[0].field if filters else None
            select_fields = self._choose_select_fields(entity, fields, intent, filter_name)
        select_fields = self._apply_constraint_target_fields(select_fields, fields, request.constraints)
        response_summary_fields = [
            field_name
            for field_name in parsed.get("response_summary_fields", [])
            if isinstance(field_name, str) and field_name in field_map
        ]
        if not response_summary_fields:
            response_summary_fields = select_fields[:4]
        response_summary_fields = self._apply_constraint_target_fields(response_summary_fields, fields, request.constraints)
        clarification_question = parsed.get("clarification_question")
        if not isinstance(clarification_question, str) or not clarification_question.strip():
            clarification_question = None
        clarification_options = [
            option
            for option in parsed.get("clarification_options", [])
            if isinstance(option, str) and option.strip()
        ]
        response_directive = parsed.get("response_directive")
        if not isinstance(response_directive, str) or not response_directive.strip():
            response_directive = (
                "Ask the user to clarify the business context before querying SAP."
                if needs_clarification
                else "Answer the user directly with the selected fields."
            )
        rationale = parsed.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            rationale = fallback_plan.rationale
        return QueryPlan(
            service_name=entity.get("service_name", self.service_name),
            entity_set=entity_set,
            http_method=method,
            select_fields=select_fields[:8],
            response_summary_fields=response_summary_fields[:6],
            filters=filters,
            top=self._resolve_top(request.constraints or self._constraints_from_intent(intent), filters),
            requires_confirmation=bool(parsed.get("requires_confirmation", method != "GET")),
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            clarification_options=clarification_options[:4],
            response_directive=response_directive,
            rationale=f"LLM planner selected this plan. {rationale}",
            planner_diagnostics={
                **fallback_plan.planner_diagnostics,
                "llm_candidate_payload": parsed,
                "llm_selection": "accepted",
            },
        )

    def _materialize_llm_steps(self, raw_steps: list[Any], snapshot, fallback_plan: QueryPlan) -> list[ExecutionStep]:
        steps: list[ExecutionStep] = []
        for index, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                continue
            entity_set = str(item.get("entity_set", "") or "")
            entity = self._lookup_entity(snapshot, entity_set)
            if entity is None:
                continue
            field_map = {
                str(field.get("field_name", "")): field
                for field in self._get_entity_fields(snapshot, entity_set)
            }
            select_fields = [
                str(field).strip()
                for field in item.get("select_fields", [])
                if str(field).strip() in field_map
            ]
            if not select_fields:
                select_fields = [
                    str(field).strip()
                    for field in entity.get("default_select_fields", [])
                    if str(field).strip() in field_map
                ][:6]
            filters: list[FilterCondition] = []
            for raw_filter in item.get("filters", []):
                if not isinstance(raw_filter, dict):
                    continue
                field_name = str(raw_filter.get("field", "") or "")
                value = raw_filter.get("value")
                if field_name not in field_map or value in (None, ""):
                    continue
                filters.append(
                    FilterCondition(
                        field=field_name,
                        operator=str(raw_filter.get("operator", "eq") or "eq"),
                        value=str(value),
                        value_type=self._filter_value_type(raw_filter, field_map[field_name]),
                    )
                )
            bindings: list[StepBinding] = []
            for raw_binding in item.get("filter_from_previous", []):
                if not isinstance(raw_binding, dict):
                    continue
                field_name = str(raw_binding.get("field", "") or "")
                if field_name not in field_map:
                    continue
                bindings.append(
                    StepBinding(
                        field=field_name,
                        source_step_id=str(raw_binding.get("source_step_id", "") or ""),
                        source_field=str(raw_binding.get("source_field", "") or ""),
                    )
                )
            if index == 1 and not filters:
                filters = fallback_plan.filters
            steps.append(
                ExecutionStep(
                    step_id=str(item.get("step_id", f"step_{index}") or f"step_{index}"),
                    entity_set=entity_set,
                    http_method=str(item.get("http_method", fallback_plan.http_method) or fallback_plan.http_method).upper(),
                    select_fields=self._dedupe_fields(select_fields),
                    response_summary_fields=self._dedupe_fields(select_fields[:4]),
                    filters=filters,
                    filter_from_previous=bindings,
                    top=int(item.get("top", 1 if index < len(raw_steps) else 20) or 20),
                    rationale=str(item.get("rationale", "") or ""),
                )
            )
        return steps

    @staticmethod
    def _filter_value_type(raw_filter: dict[str, Any], field_metadata: dict[str, Any]) -> str:
        explicit_type = raw_filter.get("value_type")
        if isinstance(explicit_type, str) and explicit_type.strip():
            return explicit_type.strip()
        data_type = field_metadata.get("data_type") or field_metadata.get("type")
        if isinstance(data_type, str) and data_type.strip():
            return data_type.strip()
        return "string"

    @classmethod
    def _parse_json_object(cls, raw_response: str) -> dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            candidate = cls._extract_first_json_object(text)
            if candidate is None:
                raise
            return json.loads(candidate)

    @staticmethod
    def _extract_first_json_object(text: str) -> str | None:
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None

    @staticmethod
    def _plan_to_dict(plan: QueryPlan) -> dict[str, Any]:
        return {
            "service_name": plan.service_name,
            "entity_set": plan.entity_set,
            "http_method": plan.http_method,
            "select_fields": plan.select_fields,
            "response_summary_fields": plan.response_summary_fields,
            "filters": [
                {"field": item.field, "operator": item.operator, "value": item.value, "value_type": item.value_type}
                for item in plan.filters
            ],
            "top": plan.top,
            "requires_confirmation": plan.requires_confirmation,
            "needs_clarification": plan.needs_clarification,
            "clarification_question": plan.clarification_question,
            "clarification_options": plan.clarification_options,
            "response_directive": plan.response_directive,
            "rationale": plan.rationale,
            "plan_kind": plan.plan_kind,
            "path_id": plan.path_id,
            "target_entity_set": plan.target_entity_set,
            "target_field": plan.target_field,
            "steps": [
                {
                    "step_id": step.step_id,
                    "entity_set": step.entity_set,
                    "select_fields": step.select_fields,
                    "filters": [
                        {"field": item.field, "operator": item.operator, "value": item.value, "value_type": item.value_type}
                        for item in step.filters
                    ],
                    "filter_from_previous": [
                        {"field": item.field, "source_step_id": item.source_step_id, "source_field": item.source_field}
                        for item in step.filter_from_previous
                    ],
                    "top": step.top,
                }
                for step in plan.steps
            ],
        }


class IndexAwareRepairEngine(RetrievalAwareIntentPlanner):
    PROPERTY_NOT_FOUND_PATTERNS = [
        re.compile(r"Property\s+(?P<field>[A-Za-z0-9_]+)\s+not found in type\s+(?P<type>[A-Za-z0-9_]+)", re.IGNORECASE),
        re.compile(r"找不到属性\s+'(?P<field>[^']+)'", re.IGNORECASE),
    ]

    def repair(self, request: AgentRequest, context: RetrievedContext, previous_plan: QueryPlan, error_message: str) -> QueryPlan:
        snapshot = self._load_snapshot()
        if snapshot is None:
            return replace(previous_plan, rationale=f"{previous_plan.rationale} Repair skipped because local index was unavailable. SAP error: {error_message}")
        intent = self._analyze_query(self._get_working_input(request))
        schema_repair = self._repair_from_required_schema(snapshot, request, intent, previous_plan, error_message)
        if schema_repair is not None:
            return schema_repair
        missing_field = self._extract_missing_field(error_message)
        if missing_field:
            repaired_plan, repaired = self._repair_missing_property(snapshot, previous_plan, intent, missing_field, error_message)
            if repaired:
                return repaired_plan
        return self._rebuild_from_intent(snapshot, request, context, previous_plan, intent, error_message)

    def _repair_missing_property(self, snapshot, previous_plan: QueryPlan, intent: dict, missing_field: str, error_message: str) -> tuple[QueryPlan, bool]:
        if missing_field in previous_plan.select_fields:
            new_select_fields = [field for field in previous_plan.select_fields if field != missing_field]
            if not new_select_fields:
                entity = self._lookup_entity(snapshot, previous_plan.entity_set) or {"default_select_fields": [], "key_fields": []}
                fields = self._get_entity_fields(snapshot, previous_plan.entity_set)
                filter_name = previous_plan.filters[0].field if previous_plan.filters else None
                new_select_fields = self._choose_select_fields(entity, fields, intent, filter_name)
            return replace(previous_plan, select_fields=new_select_fields, rationale=f"{previous_plan.rationale} Repair removed invalid select field `{missing_field}` after SAP error: {error_message}"), True
        filter_index = next((idx for idx, condition in enumerate(previous_plan.filters) if condition.field == missing_field), None)
        if filter_index is not None:
            replacement_plan = self._repair_filter_field(snapshot, previous_plan, intent, filter_index, error_message)
            if replacement_plan is not None:
                return replacement_plan, True
        return previous_plan, False

    def _repair_filter_field(self, snapshot, previous_plan: QueryPlan, intent: dict, filter_index: int, error_message: str) -> QueryPlan | None:
        current_filter = previous_plan.filters[filter_index]
        current_entity = self._lookup_entity(snapshot, previous_plan.entity_set) or {"entity_set": previous_plan.entity_set, "service_name": previous_plan.service_name, "key_fields": [], "default_select_fields": [], "supported_methods": [previous_plan.http_method]}
        current_fields = self._get_entity_fields(snapshot, previous_plan.entity_set)
        preferred_filter_fields = intent["preferred_filter_fields"]
        if preferred_filter_fields and current_filter.field == preferred_filter_fields[0]:
            switched = self._switch_entity_for_filter(snapshot, previous_plan, intent, current_filter, filter_index, error_message)
            if switched is not None:
                return switched
        replacement_field = self._choose_filter_field(current_entity, current_fields, intent)
        if replacement_field and replacement_field != current_filter.field:
            new_filters = list(previous_plan.filters)
            new_filters[filter_index] = FilterCondition(field=replacement_field, operator=current_filter.operator, value=current_filter.value, value_type=current_filter.value_type)
            new_select_fields = previous_plan.select_fields if replacement_field in previous_plan.select_fields else [replacement_field, *previous_plan.select_fields][:8]
            return replace(previous_plan, filters=new_filters, select_fields=new_select_fields, rationale=f"{previous_plan.rationale} Repair changed filter field from `{current_filter.field}` to `{replacement_field}` after SAP error: {error_message}")
        return self._switch_entity_for_filter(snapshot, previous_plan, intent, current_filter, filter_index, error_message)

    def _switch_entity_for_filter(self, snapshot, previous_plan: QueryPlan, intent: dict, current_filter: FilterCondition, filter_index: int, error_message: str) -> QueryPlan | None:
        for candidate in self._rank_repair_entities(snapshot, intent, current_filter.field, previous_plan.http_method):
            if candidate["entity_set"] == previous_plan.entity_set:
                continue
            candidate_fields = self._get_entity_fields(snapshot, candidate["entity_set"])
            candidate_field_names = {field.get("field_name", "") for field in candidate_fields}
            possible_filter = next((name for name in [current_filter.field, *intent["preferred_filter_fields"]] if name in candidate_field_names), None)
            if possible_filter is None:
                continue
            new_filters = list(previous_plan.filters)
            new_filters[filter_index] = FilterCondition(field=possible_filter, operator=current_filter.operator, value=current_filter.value, value_type=current_filter.value_type)
            new_select_fields = self._choose_select_fields(candidate, candidate_fields, intent, possible_filter)
            return replace(previous_plan, service_name=candidate["service_name"], entity_set=candidate["entity_set"], filters=new_filters, select_fields=new_select_fields, rationale=f"{previous_plan.rationale} Repair switched entity from `{previous_plan.entity_set}` to `{candidate['entity_set']}` after SAP error: {error_message}")
        return None

    def _rank_repair_entities(self, snapshot, intent: dict, preferred_field: str, method: str) -> list[dict]:
        ranked: list[tuple[float, dict]] = []
        for entity in snapshot.entities:
            fields = self._get_entity_fields(snapshot, entity["entity_set"])
            field_names = {field.get("field_name", "") for field in fields}
            score = (8.0 if preferred_field in field_names else 0.0) + (3.0 if entity["entity_set"] in self.ROOT_ENTITIES else 0.0) + (2.0 if not method_not_supported(entity, method) else 0.0)
            if intent["object_type"] == "customer":
                score += (4.0 if "Customer" in field_names else 0.0) + (1.5 if entity["entity_set"] == "A_BusinessPartner" else 0.0)
            if intent["object_type"] == "supplier":
                score += (4.0 if "Supplier" in field_names else 0.0) + (1.5 if entity["entity_set"] == "A_BusinessPartner" else 0.0)
            if intent["object_type"] == "business_partner" and "BusinessPartner" in field_names:
                score += 5.0
            ranked.append((score, entity))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [entity for score, entity in ranked if score > 0]

    def _rebuild_from_intent(self, snapshot, request: AgentRequest, context: RetrievedContext, previous_plan: QueryPlan, intent: dict, error_message: str) -> QueryPlan:
        entity = self._choose_entity(context.documents, snapshot, intent)
        if entity is None:
            return replace(previous_plan, rationale=f"{previous_plan.rationale} Repair rebuild failed. SAP error: {error_message}")
        fields = self._get_entity_fields(snapshot, entity["entity_set"])
        filter_field = self._choose_constraint_filter_field(fields, request.constraints or self._constraints_from_intent(intent))
        if filter_field is None:
            filter_field = self._choose_filter_field(entity, fields, intent)
        filters = self._build_filters(filter_field, intent, request.constraints)
        select_fields = self._choose_select_fields(entity, fields, intent, filter_field)
        top = self._resolve_top(request.constraints or self._constraints_from_intent(intent), filters) if filters else previous_plan.top
        return QueryPlan(service_name=entity["service_name"], entity_set=entity["entity_set"], http_method=intent["method"], select_fields=select_fields, filters=filters, top=top, requires_confirmation=intent["method"] != "GET", rationale=f"{previous_plan.rationale} Repair rebuilt the query plan from retrieved context after SAP error: {error_message}")

    def _extract_missing_field(self, error_message: str) -> str | None:
        for pattern in self.PROPERTY_NOT_FOUND_PATTERNS:
            match = pattern.search(error_message or "")
            if match:
                return match.group("field")
        return None

    def _repair_from_required_schema(
        self,
        snapshot,
        request: AgentRequest,
        intent: dict,
        previous_plan: QueryPlan,
        error_message: str,
    ) -> QueryPlan | None:
        constraints = request.constraints
        if constraints is None:
            return None
        required_targets = [field for field in constraints.target_field_concepts if field]
        required_filters = [field for field in constraints.filter_concepts if field]
        if not required_filters and constraints.filter_values and constraints.target_object:
            anchor_field = {
                "supplier": "Supplier",
                "customer": "Customer",
                "business_partner": "BusinessPartner",
            }.get(constraints.target_object)
            if anchor_field:
                required_filters = [anchor_field]
        if not required_targets or not required_filters:
            return None
        if not any(
            token in (error_message or "")
            for token in (
                "required_target_field_missing",
                "required_filter_field_lost",
                "filter_concept_missing",
                "missing_required_answer_field",
                "missing_required_filter_field",
                "schema_",
                "llm_wrong_entity_selection",
                "llm_wrong_entity_for_target",
            )
        ):
            return None

        primary_filter_value = self._resolve_primary_filter_value(intent, constraints)
        if not primary_filter_value:
            return None

        candidates: list[tuple[float, dict[str, Any], set[str], str]] = []
        for entity in snapshot.entities:
            entity_set = entity.get("entity_set", "")
            fields = self._get_entity_fields(snapshot, entity_set)
            field_names = {field.get("field_name", "") for field in fields}
            target_hits = [field for field in required_targets if field in field_names]
            filter_hits = [field for field in required_filters if field in field_names]
            if not target_hits or not filter_hits:
                continue
            filter_field = self._choose_best_repair_filter_field(fields, filter_hits)
            if filter_field is None:
                continue
            score = 20.0 + (len(target_hits) * 5.0) + (len(filter_hits) * 4.0)
            key_fields = set(entity.get("key_fields", []) or [])
            score += len(key_fields & set(target_hits)) * 3.0
            score += len(key_fields & set(filter_hits)) * 2.0
            score -= max(0, len(entity.get("key_fields", []) or []) - 1) * 0.5
            if entity_set == previous_plan.entity_set:
                score -= 3.0
            candidates.append((score, entity, field_names, filter_field))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, entity, field_names, filter_field = candidates[0]
        entity_set = entity.get("entity_set", previous_plan.entity_set)
        select_fields = self._dedupe_fields(
            [
                *[field for field in required_targets if field in field_names],
                filter_field,
                *[field for field in entity.get("default_select_fields", []) if field in field_names],
            ]
        )[:8]
        filters = [
            FilterCondition(
                field=filter_field,
                operator="contains" if constraints.name_match_mode == "contains" else "eq",
                value=primary_filter_value,
            )
        ]
        return QueryPlan(
            service_name=entity.get("service_name", self.service_name),
            entity_set=entity_set,
            http_method=intent["method"],
            select_fields=select_fields,
            response_summary_fields=self._dedupe_fields([*required_targets, filter_field])[:4],
            filters=filters,
            top=self._resolve_top(constraints, filters),
            requires_confirmation=intent["method"] != "GET",
            response_directive=previous_plan.response_directive,
            rationale=(
                f"{previous_plan.rationale} Repair rebuilt a schema-feasible direct plan on "
                f"`{entity_set}` because the previous plan violated required answer/filter constraints: {error_message}"
            ),
            planner_diagnostics={
                **(previous_plan.planner_diagnostics or {}),
                "schema_repair": {
                    "strategy": "direct_entity_covering_required_answer_and_filter_fields",
                    "entity_set": entity_set,
                    "required_targets": required_targets,
                    "required_filters": required_filters,
                    "filter_field": filter_field,
                },
            },
        )

    @staticmethod
    def _choose_best_repair_filter_field(fields: list[dict[str, Any]], filter_hits: list[str]) -> str | None:
        field_map = {field.get("field_name", ""): field for field in fields}
        filterable = [
            field_name
            for field_name in filter_hits
            if field_map.get(field_name, {}).get("filterable") is not False
        ]
        return (filterable or filter_hits)[0] if filter_hits else None


class LlmRepairEngine(IndexAwareRepairEngine):
    def __init__(
        self,
        index_root: str = "data/index",
        service_name: str = "API_BUSINESS_PARTNER",
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        super().__init__(index_root=index_root, service_name=service_name)
        self.llm_client = llm_client
        self.enabled = enabled

    def repair(self, request: AgentRequest, context: RetrievedContext, previous_plan: QueryPlan, error_message: str) -> QueryPlan:
        deterministic_plan = super().repair(request, context, previous_plan, error_message)
        if not self.enabled or self.llm_client is None:
            return deterministic_plan
        snapshot = self._load_snapshot()
        if snapshot is None:
            return deterministic_plan
        try:
            parsed = self._request_llm_repair(request, context, previous_plan, deterministic_plan, error_message)
            repaired = self._materialize_repair_plan(parsed, snapshot, deterministic_plan)
        except Exception as exc:
            return replace(
                deterministic_plan,
                rationale=f"{deterministic_plan.rationale} LLM repair skipped after client error: {exc}",
                planner_diagnostics={
                    **(deterministic_plan.planner_diagnostics or {}),
                    "llm_repair": {"accepted": False, "reason": f"client_error:{exc}"},
                },
            )
        if repaired is None:
            return deterministic_plan
        return repaired

    def _request_llm_repair(
        self,
        request: AgentRequest,
        context: RetrievedContext,
        previous_plan: QueryPlan,
        deterministic_plan: QueryPlan,
        error_message: str,
    ) -> dict[str, Any]:
        raw = self.llm_client.complete_json(
            self._repair_system_prompt(),
            self._repair_user_prompt(request, context, previous_plan, deterministic_plan, error_message),
            max_tokens=900,
        )
        return LlmStructuredIntentPlanner._parse_json_object(raw)

    @staticmethod
    def _repair_system_prompt() -> str:
        return (
            "You repair SAP OData query plans. "
            "Only use entities and fields shown in candidate_schema. "
            "Return one JSON object only."
        )

    def _repair_user_prompt(
        self,
        request: AgentRequest,
        context: RetrievedContext,
        previous_plan: QueryPlan,
        deterministic_plan: QueryPlan,
        error_message: str,
    ) -> str:
        docs = [
            {
                "source": doc.source,
                "title": doc.title,
                "score": doc.score,
                "metadata": {
                    "entity_set": (doc.metadata or {}).get("entity_set", ""),
                    "field_name": (doc.metadata or {}).get("field_name", ""),
                    "label": (doc.metadata or {}).get("label", ""),
                    "description": (doc.metadata or {}).get("description", ""),
                },
            }
            for doc in context.documents[:16]
        ]
        example = {
            "use_deterministic_plan": False,
            "entity_set": "A_RelevantEntity",
            "http_method": "GET",
            "select_fields": ["IdentifierField", "ContextField", "RequestedField"],
            "response_summary_fields": ["ContextField", "RequestedField"],
            "filters": [{"field": "IdentifierField", "operator": "eq", "value": "literal value from the request"}],
            "top": 20,
            "reason": "The previous plan missed the requested target field.",
        }
        payload = {
            "user_input": request.resolved_user_input or request.user_input,
            "semantic_frame": request.semantic_frame,
            "schema_rerank": request.schema_rerank,
            "feedback_hints": request.feedback_hints,
            "feedback_memories": request.feedback_memories,
            "error_message": error_message,
            "previous_plan": LlmStructuredIntentPlanner._plan_to_dict(previous_plan),
            "deterministic_repair_plan": LlmStructuredIntentPlanner._plan_to_dict(deterministic_plan),
            "candidate_schema": docs,
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "If deterministic_repair_plan is already valid for the user question, set use_deterministic_plan=true. "
            "Otherwise output a repaired direct plan using only candidate_schema fields. "
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    def _materialize_repair_plan(self, parsed: dict[str, Any], snapshot, fallback_plan: QueryPlan) -> QueryPlan | None:
        if bool(parsed.get("use_deterministic_plan", False)):
            return fallback_plan
        entity_set = str(parsed.get("entity_set", "") or "")
        entity = self._lookup_entity(snapshot, entity_set)
        if entity is None:
            return None
        fields = self._get_entity_fields(snapshot, entity_set)
        field_map = {str(field.get("field_name", "")): field for field in fields}
        select_fields = [
            str(field).strip()
            for field in parsed.get("select_fields", [])
            if str(field).strip() in field_map
        ]
        filters: list[FilterCondition] = []
        for item in parsed.get("filters", []):
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("field", "") or "")
            value = item.get("value")
            if field_name not in field_map or value in (None, ""):
                continue
            filters.append(
                FilterCondition(
                    field=field_name,
                    operator=str(item.get("operator", "eq") or "eq"),
                    value=str(value),
                    value_type=LlmStructuredIntentPlanner._filter_value_type(item, field_map[field_name]),
                )
            )
        if not select_fields:
            select_fields = fallback_plan.select_fields
        response_summary_fields = [
            str(field).strip()
            for field in parsed.get("response_summary_fields", [])
            if str(field).strip() in field_map
        ] or select_fields[:4]
        return QueryPlan(
            service_name=entity.get("service_name", fallback_plan.service_name),
            entity_set=entity_set,
            http_method=str(parsed.get("http_method", fallback_plan.http_method) or fallback_plan.http_method).upper(),
            select_fields=select_fields[:8],
            response_summary_fields=response_summary_fields[:6],
            filters=filters or fallback_plan.filters,
            top=int(parsed.get("top", fallback_plan.top or 20) or 20),
            requires_confirmation=bool(parsed.get("requires_confirmation", False)),
            response_directive=fallback_plan.response_directive,
            rationale=f"{fallback_plan.rationale} LLM repair selected a revised plan: {parsed.get('reason', '')}",
            planner_diagnostics={
                **(fallback_plan.planner_diagnostics or {}),
                "llm_repair": {"accepted": True, "raw": parsed},
            },
        )


class KeywordIntentPlanner(RetrievalAwareIntentPlanner):
    pass


class SimpleRepairEngine:
    def repair(self, request: AgentRequest, context: RetrievedContext, previous_plan: QueryPlan, error_message: str) -> QueryPlan:
        return replace(previous_plan, rationale=f"{previous_plan.rationale} Repair placeholder saw error: {error_message}")


def method_not_supported(entity: dict, method: str) -> bool:
    return method not in set(entity.get("supported_methods", ["GET"]))
