from __future__ import annotations

import json
import re
import time
from typing import Any

from sap_odata_agent.domain.models import ApiRouteDecision, SelectedApi
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner
from sap_odata_agent.infrastructure.llm.prompts import API_ROUTER_TASK_PROMPT, GLOBAL_SAP_ODATA_PROMPT


class LlmApiRouter:
    def __init__(
        self,
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
        default_service_name: str = "API_BUSINESS_PARTNER",
        allow_default_fallback: bool = False,
    ) -> None:
        self.llm_client = llm_client
        self.enabled = enabled
        self.default_service_name = default_service_name
        self.allow_default_fallback = allow_default_fallback

    def route(
        self,
        user_input: str,
        api_catalog: list[dict[str, Any]],
        recent_cases: list[dict[str, Any]] | None = None,
        latest_clarification_case: dict[str, Any] | None = None,
        feedback_memories: list[dict[str, Any]] | None = None,
    ) -> ApiRouteDecision:
        routable_catalog = self._routable_api_catalog(api_catalog)
        if not self.enabled or self.llm_client is None:
            fallback = self._skill_catalog_fallback_route(
                user_input,
                routable_catalog,
                reason="api_router_unavailable",
                feedback_memories=feedback_memories or [],
            )
            return fallback if fallback.selected_apis else self._unavailable_route(routable_catalog or api_catalog)
        payload = {
            "user_input": user_input,
            "api_catalog": self._compact_catalog_for_prompt(routable_catalog, user_input=user_input),
            "recent_cases": self._compact_recent_cases_for_prompt(recent_cases or []),
            "latest_clarification_case": self._compact_case_for_prompt(latest_clarification_case or {}),
            "feedback_memories": self._compact_feedback_memories_for_prompt(feedback_memories or []),
        }
        example = {
            "resolved_user_input": user_input,
            "should_carry_context": False,
            "selected_apis": [
                {
                    "service_name": routable_catalog[0]["service_name"] if routable_catalog else self.default_service_name,
                    "confidence": 0.0,
                    "reason": "Matched the user's business object to the API catalog.",
                }
            ],
            "requires_multi_api": False,
            "intent_summary": "",
            "business_domain": "",
            "business_object": "",
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
        }
        user_prompt = (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )
        try:
            raw = self._complete_nonempty_json_text(self._system_prompt(), user_prompt, max_tokens=1600)
            parsed = self._parse_route_json_with_repair(raw, user_prompt, example)
        except Exception as exc:
            fallback = self._skill_catalog_fallback_route(
                user_input,
                routable_catalog,
                reason=f"api_router_failed:{exc}",
                feedback_memories=feedback_memories or [],
            )
            if fallback.selected_apis:
                return fallback
            fallback = self._unavailable_route(routable_catalog or api_catalog)
            fallback.raw_response = {"accepted": False, "reason": f"api_router_failed:{exc}"}
            return fallback
        decision = self._materialize(parsed, routable_catalog, user_input)
        if not decision.selected_apis and not decision.needs_clarification:
            fallback = self._skill_catalog_fallback_route(
                user_input,
                routable_catalog,
                reason="api_router_empty_selection",
                feedback_memories=feedback_memories or [],
            )
            if fallback.selected_apis:
                return fallback
        return decision

    @staticmethod
    def _system_prompt() -> str:
        return f"{GLOBAL_SAP_ODATA_PROMPT}\n\n{API_ROUTER_TASK_PROMPT}"

    @staticmethod
    def _routable_api_catalog(api_catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [entry for entry in api_catalog if LlmApiRouter._is_odata_routable_catalog_entry(entry)]

    @staticmethod
    def _is_odata_routable_catalog_entry(entry: dict[str, Any]) -> bool:
        service_name = str(entry.get("service_name") or "").strip()
        if not service_name:
            return False
        service_kind = str(entry.get("service_kind") or "ODATA").strip().upper()
        if service_kind == "CDS_VIEW_ONLY":
            return False
        if entry.get("odata_runtime_available") is False:
            return False
        if entry.get("runtime_available") is False:
            return False
        return True

    @staticmethod
    def _json_repair_system_prompt() -> str:
        return (
            f"{GLOBAL_SAP_ODATA_PROMPT}\n\n"
            "You repair malformed JSON emitted by the SAP OData API router. "
            "Return only one valid JSON object. Do not add prose. Do not change the API routing decision, "
            "business reasoning, selected APIs, or clarification intent except as required to make the JSON valid."
        )

    @staticmethod
    def _json_repair_prompt(raw_response: str, example: dict[str, Any]) -> str:
        return (
            "The previous API router response was not valid JSON. Repair only the JSON syntax and preserve the "
            "original routing content.\n\n"
            "Expected JSON shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}\n\n"
            "Malformed response:\n"
            f"{raw_response}"
        )

    def _parse_route_json_with_repair(
        self,
        raw_response: str,
        original_user_prompt: str,
        example: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return LlmStructuredIntentPlanner._parse_json_object(raw_response)
        except json.JSONDecodeError:
            repaired_raw = self._complete_nonempty_json_text(
                self._json_repair_system_prompt(),
                self._json_repair_prompt(raw_response, example),
                max_tokens=1200,
                attempts=1,
            )
            try:
                return LlmStructuredIntentPlanner._parse_json_object(repaired_raw)
            except json.JSONDecodeError:
                regenerated_raw = self._complete_nonempty_json_text(
                    self._system_prompt(),
                    self._strict_regenerate_prompt(
                        original_user_prompt=original_user_prompt,
                        raw_response=raw_response,
                        repaired_response=repaired_raw,
                        example=example,
                    ),
                    max_tokens=1600,
                    attempts=1,
                )
                return LlmStructuredIntentPlanner._parse_json_object(regenerated_raw)

    @staticmethod
    def _strict_regenerate_prompt(
        *,
        original_user_prompt: str,
        raw_response: str,
        repaired_response: str,
        example: dict[str, Any],
    ) -> str:
        return (
            "The API router produced invalid JSON, and the JSON repair response was still invalid. "
            "Regenerate the API routing decision from the original input. Return exactly one valid JSON object. "
            "Do not use markdown. Do not add prose. Do not choose a programmatic fallback; use the catalog, "
            "feedback memories, top fields, and skill guidance in the original input.\n\n"
            "Expected JSON shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}\n\n"
            "Original router prompt:\n"
            f"{original_user_prompt}\n\n"
            "First malformed response:\n"
            f"{LlmApiRouter._truncate(raw_response, 1200)}\n\n"
            "Invalid repair response:\n"
            f"{LlmApiRouter._truncate(repaired_response, 1200)}"
        )

    def _complete_nonempty_json_text(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1100,
        attempts: int = 3,
    ) -> str:
        last_response = ""
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                response = self.llm_client.complete_json(system_prompt, user_prompt, max_tokens=max_tokens)
            except Exception as exc:
                last_error = exc
                if attempt + 1 < max(1, attempts):
                    time.sleep(0.5)
                    continue
                break
            if response and response.strip():
                return response
            last_response = response
        if last_error is not None:
            raise last_error
        raise ValueError(f"LLM returned empty content after {max(1, attempts)} attempts: {last_response!r}")

    def _skill_catalog_fallback_route(
        self,
        user_input: str,
        api_catalog: list[dict[str, Any]],
        *,
        reason: str,
        feedback_memories: list[dict[str, Any]],
    ) -> ApiRouteDecision:
        parsed = self._skill_catalog_fallback_parsed(
            user_input,
            api_catalog,
            reason=reason,
            feedback_memories=feedback_memories,
        )
        if parsed is None:
            return ApiRouteDecision(
                selected_apis=[],
                raw_response={
                    "accepted": False,
                    "reason": reason,
                    "router_fallback": "skill_catalog_no_match",
                },
            )
        return self._materialize(parsed, api_catalog, user_input)

    @staticmethod
    def _skill_catalog_fallback_parsed(
        user_input: str,
        api_catalog: list[dict[str, Any]],
        *,
        reason: str,
        feedback_memories: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        ranked: list[tuple[float, dict[str, Any], list[str]]] = []
        for entry in api_catalog:
            service_name = str(entry.get("service_name") or "")
            if not service_name:
                continue
            score, evidence = LlmApiRouter._score_catalog_entry_for_fallback(
                entry,
                user_input,
                feedback_memories=feedback_memories,
            )
            if score > 0:
                ranked.append((score, entry, evidence))
        if not ranked:
            return None
        ranked.sort(key=lambda item: item[0], reverse=True)
        top_score, top_entry, top_evidence = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        margin = max(4.0, top_score * 0.18)
        if top_score < 12.0 or top_score < second_score + margin:
            return None
        service_name = str(top_entry.get("service_name") or "")
        confidence = min(0.88, max(0.55, top_score / (top_score + second_score + 8.0)))
        business_objects = [str(item) for item in top_entry.get("primary_business_objects") or [] if str(item).strip()]
        selected = [
            {
                "service_name": service_name,
                "confidence": round(confidence, 3),
                "reason": (
                    "Skill/catalog fallback selected the strongest API match after Router LLM was unavailable "
                    "or returned no executable selection."
                ),
            }
        ]
        return {
            "resolved_user_input": user_input,
            "should_carry_context": False,
            "selected_apis": selected,
            "requires_multi_api": False,
            "intent_summary": "Route inferred from API skill/catalog similarity.",
            "business_domain": "",
            "business_object": business_objects[0] if business_objects else "",
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "accepted": True,
            "router_fallback": "skill_catalog_similarity",
            "fallback_reason": reason,
            "match_score": round(top_score, 3),
            "second_match_score": round(second_score, 3),
            "matched_evidence": top_evidence[:6],
        }

    @staticmethod
    def _score_catalog_entry_for_fallback(
        entry: dict[str, Any],
        user_input: str,
        *,
        feedback_memories: list[dict[str, Any]],
    ) -> tuple[float, list[str]]:
        score = 0.0
        evidence: list[str] = []

        weighted_texts = (
            ("short_description", str(entry.get("short_description") or ""), 1.2),
            ("primary_business_objects", " ".join(str(item) for item in entry.get("primary_business_objects") or []), 1.8),
            ("top_entities", " ".join(str(item) for item in entry.get("top_entities") or []), 0.7),
            ("top_filter_fields", " ".join(str(item) for item in entry.get("top_filter_fields") or []), 0.45),
            ("top_answer_fields", " ".join(str(item) for item in entry.get("top_answer_fields") or []), 0.4),
        )
        for label, text, weight in weighted_texts:
            match_score = LlmApiRouter._semantic_match_score(user_input, text)
            if match_score <= 0:
                continue
            score += match_score * weight
            evidence.append(f"{label}:{LlmApiRouter._truncate(text, 140)}")

        skill_summary = str(entry.get("api_skill_summary") or "")
        for raw_line in skill_summary.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match_score = LlmApiRouter._semantic_match_score(user_input, line)
            if match_score <= 0:
                continue
            if LlmApiRouter._is_negative_skill_line(line):
                score -= match_score * 6.0
                continue
            score += match_score * 2.8
            evidence.append(f"api_skill:{LlmApiRouter._truncate(line, 180)}")

        memory_score = LlmApiRouter._feedback_memory_match_score(entry, user_input, feedback_memories)
        if memory_score > 0:
            score += memory_score
            evidence.append("feedback_memory:matched preferred service/entity/field hints")

        synonym_score = LlmApiRouter._catalog_business_synonym_match_score(entry, user_input)
        if synonym_score > 0:
            score += synonym_score
            evidence.append("business_synonyms:matched user wording to catalog business terms")

        return score, evidence

    @staticmethod
    def _catalog_business_synonym_match_score(entry: dict[str, Any], user_input: str) -> float:
        catalog_text = LlmApiRouter._normalize_match_text(
            json.dumps(
                {
                    "service_name": entry.get("service_name") or "",
                    "short_description": entry.get("short_description") or "",
                    "primary_business_objects": entry.get("primary_business_objects") or [],
                    "top_entities": entry.get("top_entities") or [],
                    "top_filter_fields": entry.get("top_filter_fields") or [],
                    "top_answer_fields": entry.get("top_answer_fields") or [],
                    "api_skill_summary": entry.get("api_skill_summary") or "",
                },
                ensure_ascii=False,
            )
        )
        core_catalog_text = LlmApiRouter._normalize_match_text(
            json.dumps(
                {
                    "service_name": entry.get("service_name") or "",
                    "short_description": entry.get("short_description") or "",
                    "primary_business_objects": entry.get("primary_business_objects") or [],
                    "top_entities": entry.get("top_entities") or [],
                    "api_skill_summary": entry.get("api_skill_summary") or "",
                },
                ensure_ascii=False,
            )
        )
        if not catalog_text:
            return 0.0
        query_raw = str(user_input or "").lower()
        query_norm = LlmApiRouter._normalize_match_text(user_input)
        groups = (
            ("purchaseorder", "purchase order", "采购订单", "采购单"),
            ("schedulelinedeliverydate", "deliverydate", "delivery date", "arriving", "arrival", "到货", "交货日期", "交货"),
            ("supplier", "vendor", "供应商"),
            ("material", "product", "物料", "产品"),
            ("plant", "工厂"),
            ("salesorder", "sales order", "销售订单"),
            ("deliverydocument", "outbounddelivery", "outbound delivery", "交货单", "发货单"),
            ("invoice", "billing", "发票", "开票"),
            ("stock", "inventory", "库存"),
        )
        score = 0.0
        for group in groups:
            query_matches = [
                term
                for term in group
                if LlmApiRouter._contains_synonym_term(query_raw, query_norm, term)
            ]
            if not query_matches:
                continue
            candidate_text = core_catalog_text if group[0] == "purchaseorder" else catalog_text
            candidate_matches = [
                term
                for term in group
                if LlmApiRouter._normalize_match_text(term) in candidate_text
            ]
            if not candidate_matches:
                continue
            score += 6.0 + min(4.0, 1.5 * len(query_matches))
        return score

    @staticmethod
    def _contains_synonym_term(raw_text: str, normalized_text: str, term: str) -> bool:
        term_raw = str(term or "").lower()
        if not term_raw:
            return False
        if any("\u4e00" <= ch <= "\u9fff" for ch in term_raw):
            return term_raw in raw_text
        term_norm = LlmApiRouter._normalize_match_text(term_raw)
        return bool(term_norm and term_norm in normalized_text)

    @staticmethod
    def _feedback_memory_match_score(
        entry: dict[str, Any],
        user_input: str,
        feedback_memories: list[dict[str, Any]],
    ) -> float:
        if not feedback_memories:
            return 0.0
        service_name = LlmApiRouter._normalize_match_text(str(entry.get("service_name") or ""))
        catalog_text = LlmApiRouter._normalize_match_text(
            json.dumps(
                {
                    "service_name": entry.get("service_name") or "",
                    "top_entities": entry.get("top_entities") or [],
                    "top_filter_fields": entry.get("top_filter_fields") or [],
                    "top_answer_fields": entry.get("top_answer_fields") or [],
                    "primary_business_objects": entry.get("primary_business_objects") or [],
                },
                ensure_ascii=False,
            )
        )
        score = 0.0
        for memory in feedback_memories[:5]:
            if not isinstance(memory, dict):
                continue
            phrase_text = " ".join(str(item) for item in memory.get("user_phrases") or [])
            lesson = str(memory.get("lesson") or "")
            if LlmApiRouter._semantic_match_score(user_input, f"{phrase_text} {lesson}") < 3.0:
                continue
            preferred = " ".join(
                str(item)
                for item in [
                    *(memory.get("preferred_entities") or []),
                    *(memory.get("preferred_fields") or []),
                ]
            )
            preferred_norm = LlmApiRouter._normalize_match_text(preferred)
            if service_name and service_name in preferred_norm:
                score += 10.0
            if preferred_norm and any(term in catalog_text for term in LlmApiRouter._match_tokens(preferred)):
                score += 4.0
        return score

    @staticmethod
    def _semantic_match_score(query: str, candidate: str) -> float:
        query_text = str(query or "")
        candidate_text = str(candidate or "")
        if not query_text.strip() or not candidate_text.strip():
            return 0.0
        score = 0.0
        query_norm = LlmApiRouter._normalize_match_text(query_text)
        candidate_norm = LlmApiRouter._normalize_match_text(candidate_text)
        if len(query_norm) >= 6 and query_norm in candidate_norm:
            score += 8.0
        elif len(candidate_norm) >= 6 and candidate_norm in query_norm:
            score += 5.0

        query_tokens = {
            token
            for token in LlmApiRouter._match_tokens(query_text)
            if LlmApiRouter._is_signal_token(token)
        }
        candidate_tokens = {
            token
            for token in LlmApiRouter._match_tokens(candidate_text)
            if LlmApiRouter._is_signal_token(token)
        }
        score += 2.0 * len(query_tokens & candidate_tokens)

        query_terms = LlmApiRouter._cjk_terms(query_text)
        candidate_terms = LlmApiRouter._cjk_terms(candidate_text)
        for term in query_terms & candidate_terms:
            score += 1.0 + min(2.0, len(term) * 0.25)
        return score

    @staticmethod
    def _is_signal_token(token: str) -> bool:
        cleaned = str(token or "").lower()
        if len(cleaned) < 3:
            return False
        if any(ch.isdigit() for ch in cleaned):
            return False
        return cleaned not in {
            "query",
            "show",
            "list",
            "get",
            "what",
            "which",
            "with",
            "for",
            "and",
            "the",
            "all",
            "api",
            "srv",
        }

    @staticmethod
    def _cjk_terms(value: str) -> set[str]:
        terms: set[str] = set()
        for chunk in re.findall(r"[\u4e00-\u9fff]+", str(value or "")):
            if len(chunk) <= 1:
                continue
            if len(chunk) <= 6:
                terms.add(chunk)
            for size in (2, 3, 4, 5):
                if len(chunk) < size:
                    continue
                for index in range(0, len(chunk) - size + 1):
                    term = chunk[index : index + size]
                    if term in {"查询", "是否", "哪个", "什么", "所有", "这个", "一个"}:
                        continue
                    terms.add(term)
        return terms

    @staticmethod
    def _is_negative_skill_line(line: str) -> bool:
        lower = str(line or "").lower()
        return any(
            marker in lower
            for marker in (
                "do not use",
                "don't use",
                "not use this api",
                "does not contain",
                "do not answer",
                "not sufficient",
                "不要",
                "不使用",
                "不能",
                "不应",
                "不包含",
            )
        )

    @staticmethod
    def _compact_catalog_for_prompt(
        api_catalog: list[dict[str, Any]],
        user_input: str = "",
    ) -> list[dict[str, Any]]:
        """Keep the all-API router prompt small enough for provider limits."""

        compact: list[dict[str, Any]] = []
        for entry in api_catalog:
            item: dict[str, Any] = {
                "service_name": str(entry.get("service_name") or ""),
                "short_description": LlmApiRouter._truncate(str(entry.get("short_description") or ""), 110),
                "primary_business_objects": LlmApiRouter._compact_ranked_values(
                    entry.get("primary_business_objects") or [],
                    user_input=user_input,
                    base_limit=4,
                    max_limit=8,
                ),
                "top_entities": LlmApiRouter._compact_ranked_values(
                    entry.get("top_entities") or [],
                    user_input=user_input,
                    base_limit=4,
                    max_limit=8,
                ),
                "top_filter_fields": LlmApiRouter._compact_ranked_values(
                    entry.get("top_filter_fields") or [],
                    user_input=user_input,
                    base_limit=4,
                    max_limit=8,
                ),
                "top_answer_fields": LlmApiRouter._compact_ranked_values(
                    entry.get("top_answer_fields") or [],
                    user_input=user_input,
                    base_limit=4,
                    max_limit=10,
                ),
            }
            skill_summary = str(entry.get("api_skill_summary") or "")
            if skill_summary.strip():
                item["api_skill_summary"] = LlmApiRouter._compact_skill_summary_for_prompt(
                    skill_summary,
                    user_input=user_input,
                )
            if entry.get("odata_runtime_available") is False:
                item["odata_runtime_available"] = False
                item["runtime_notes"] = LlmApiRouter._truncate(str(entry.get("runtime_notes") or ""), 80)
            compact.append(item)
        return compact

    @staticmethod
    def _compact_ranked_values(
        values: list[Any],
        *,
        user_input: str,
        base_limit: int,
        max_limit: int,
    ) -> list[str]:
        cleaned = [str(value) for value in values if str(value).strip()]
        selected: list[str] = []
        for value in cleaned[:base_limit]:
            if value not in selected:
                selected.append(value)

        matched: list[tuple[tuple[int, int, int], str]] = []
        for index, value in enumerate(cleaned[base_limit:], start=base_limit):
            if value in selected:
                continue
            score = LlmApiRouter._catalog_value_match_score(value, user_input)
            if score <= 0:
                continue
            matched.append(((-score, index, len(value)), value))
        for _, value in sorted(matched):
            if len(selected) >= max_limit:
                break
            selected.append(value)
        return selected

    @staticmethod
    def _value_matches_user_input(value: str, user_input: str) -> bool:
        return LlmApiRouter._catalog_value_match_score(value, user_input) > 0

    @staticmethod
    def _catalog_value_match_score(value: str, user_input: str) -> int:
        query = LlmApiRouter._normalize_match_text(user_input)
        candidate = LlmApiRouter._normalize_match_text(value)
        if not query or not candidate:
            return 0
        if candidate in query:
            return 1000 + len(candidate)
        if query in candidate:
            return 900 + len(query)

        stop_tokens = {
            "api",
            "srv",
            "service",
            "query",
            "show",
            "list",
            "lists",
            "record",
            "records",
            "all",
            "for",
            "with",
            "from",
            "the",
            "and",
            "items",
            "item",
            "data",
            "main",
            "basic",
            "details",
            "detail",
            "sales",
            "order",
            "orders",
            "purchase",
            "material",
            "product",
            "supplier",
            "customer",
        }
        query_tokens = [
            token
            for token in LlmApiRouter._match_tokens(user_input)
            if len(token) >= 4 and token not in stop_tokens
        ]
        if not query_tokens:
            query_tokens = [
                token
                for token in LlmApiRouter._match_tokens(user_input)
                if len(token) >= 4 and token not in {"query", "show", "list", "records", "items", "details"}
            ]
        score = 0
        for token in query_tokens:
            if token in candidate:
                score += len(token) * 10
        return score

    @staticmethod
    def _normalize_match_text(value: str) -> str:
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    @staticmethod
    def _match_tokens(value: str) -> list[str]:
        text = str(value or "")
        split_camel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        return [
            token.lower()
            for token in re.findall(r"[A-Za-z0-9]+", split_camel)
            if token
        ]

    @staticmethod
    def _compact_recent_cases_for_prompt(recent_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep history useful for routing without sending result payloads."""

        compact: list[dict[str, Any]] = []
        for case in recent_cases[:5]:
            item = LlmApiRouter._compact_case_for_prompt(case)
            if item:
                compact.append(item)
        return compact

    @staticmethod
    def _compact_case_for_prompt(case: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(case, dict) or not case:
            return {}
        request = case.get("request") or {}
        initial_plan = case.get("initial_plan") or {}
        final_plan = case.get("final_plan") or {}
        route_decision = case.get("route_decision") or {}
        failure = case.get("failure_attribution") or {}
        result_snapshot = case.get("result_snapshot") or {}
        item: dict[str, Any] = {
            "case_id": str(case.get("case_id") or "")[:80],
            "user_input": LlmApiRouter._truncate(str(request.get("user_input") or case.get("user_input") or ""), 180),
            "effective_user_input": LlmApiRouter._truncate(str(case.get("effective_user_input") or ""), 220),
            "final_status": str(case.get("final_status") or case.get("status") or "")[:80],
            "selected_api": str(final_plan.get("service_name") or initial_plan.get("service_name") or ""),
            "entity_set": str(final_plan.get("entity_set") or initial_plan.get("entity_set") or ""),
            "final_query_url": LlmApiRouter._truncate(str(case.get("final_query_url") or ""), 220),
            "error_summary": LlmApiRouter._truncate(str(case.get("error_summary") or ""), 220),
            "failure_category": str(failure.get("category") or "")[:120],
            "failure_root_cause": LlmApiRouter._truncate(str(failure.get("root_cause") or ""), 220),
            "route_business_object": LlmApiRouter._truncate(str(route_decision.get("business_object") or ""), 120),
            "route_intent_summary": LlmApiRouter._truncate(str(route_decision.get("intent_summary") or ""), 180),
        }
        feedback_memories = case.get("feedback_memories_used") or result_snapshot.get("feedback_memories_used") or []
        if feedback_memories:
            item["feedback_memories_used"] = LlmApiRouter._compact_feedback_memories_for_prompt(feedback_memories)
        return {key: value for key, value in item.items() if value not in ("", [], {})}

    @staticmethod
    def _compact_feedback_memories_for_prompt(feedback_memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact: list[dict[str, Any]] = []
        for memory in feedback_memories[:5]:
            if not isinstance(memory, dict):
                continue
            item = {
                "case_id": str(memory.get("case_id") or "")[:80],
                "memory_type": str(memory.get("memory_type") or "")[:80],
                "lesson": LlmApiRouter._truncate(str(memory.get("lesson") or ""), 260),
                "condition": LlmApiRouter._truncate(str(memory.get("condition") or ""), 200),
                "user_phrases": [str(value)[:120] for value in (memory.get("user_phrases") or [])[:5]],
                "preferred_entities": [str(value)[:120] for value in (memory.get("preferred_entities") or [])[:5]],
                "preferred_fields": [str(value)[:120] for value in (memory.get("preferred_fields") or [])[:8]],
                "rejected_fields": [str(value)[:120] for value in (memory.get("rejected_fields") or [])[:8]],
            }
            compact.append({key: value for key, value in item.items() if value not in ("", [], {})})
        return compact

    @staticmethod
    def _compact_skill_summary_for_prompt(skill_summary: str, *, user_input: str) -> str:
        text = str(skill_summary or "").strip()
        if not text:
            return ""
        compact = LlmApiRouter._truncate(text, 180)
        relevant_lines = LlmApiRouter._relevant_skill_lines_for_prompt(text, user_input=user_input, max_lines=4)
        if relevant_lines:
            compact = f"{compact}\nRelevant skill guidance:\n" + "\n".join(
                f"- {line}" for line in relevant_lines
            )
        return LlmApiRouter._truncate(compact, 700)

    @staticmethod
    def _relevant_skill_lines_for_prompt(
        skill_summary: str,
        *,
        user_input: str,
        max_lines: int = 4,
    ) -> list[str]:
        ranked_lines: list[tuple[int, int, str]] = []
        text = str(skill_summary or "")
        for index, raw_line in enumerate(text.splitlines()):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if LlmApiRouter._skill_line_matches_user_input(line, user_input):
                cleaned = re.sub(r"^\s*[-*]\s*", "", line)
                if cleaned:
                    score = LlmApiRouter._skill_prompt_line_score(cleaned, user_input)
                    ranked_lines.append((score, index, cleaned))
        relevant_lines: list[str] = []
        for _, _, cleaned in sorted(ranked_lines, key=lambda item: (-item[0], item[1])):
            if cleaned not in relevant_lines:
                relevant_lines.append(cleaned)
            if len(relevant_lines) >= max_lines:
                break
        return relevant_lines

    @staticmethod
    def _skill_prompt_line_score(line: str, user_input: str) -> int:
        query = LlmApiRouter._normalize_match_text(user_input)
        candidate = LlmApiRouter._normalize_match_text(line)
        if not query or not candidate:
            return 0
        score = 0
        if query in candidate:
            score += 2000 + len(query)
        if candidate in query:
            score += 1500 + len(candidate)
        weak_tokens = {
            "query",
            "show",
            "list",
            "with",
            "from",
            "record",
            "records",
            "item",
            "items",
            "line",
            "lines",
            "data",
            "field",
            "fields",
            "name",
            "names",
        }
        query_tokens = {
            token
            for token in LlmApiRouter._match_tokens(user_input)
            if len(token) >= 4 and token not in weak_tokens
        }
        line_tokens = {
            token
            for token in LlmApiRouter._match_tokens(line)
            if len(token) >= 4 and token not in weak_tokens
        }
        score += 20 * len(query_tokens.intersection(line_tokens))
        for phrase in re.findall(r'"([^"]+)"|`([^`]+)`|\'([^\']+)\'', line):
            snippet = next((part for part in phrase if part), "")
            normalized_snippet = LlmApiRouter._normalize_match_text(snippet)
            if normalized_snippet and normalized_snippet in query:
                score += 1000 + len(normalized_snippet)
        if LlmApiRouter._is_negative_skill_line(line):
            score += 250
        return score

    @staticmethod
    def _skill_line_matches_user_input(line: str, user_input: str) -> bool:
        if LlmApiRouter._value_matches_user_input(line, user_input):
            return True
        query = LlmApiRouter._normalize_match_text(user_input)
        candidate = LlmApiRouter._normalize_match_text(line)
        synonym_groups = (
            ("company", "companycode", "company code", "公司", "公司代码", "法人公司"),
            ("chartofaccounts", "chart of accounts", "科目表", "会计科目表"),
            ("glaccount", "g/l account", "general ledger account", "总账科目", "会计科目", "科目"),
            ("balance", "trial balance", "account balance", "余额", "试算", "科目余额"),
            ("drilldown", "drill down", "line item", "line items", "下钻", "凭证明细", "行项目"),
            ("expense", "profitloss", "profit and loss", "费用", "损益", "损益类", "收入", "资产负债"),
            ("journalentry", "journal entry", "line item", "财务行项目", "日记账", "凭证行项目", "总账行项目"),
            ("functionalarea", "functional area", "职能范围", "功能范围"),
            ("ledger", "leading ledger", "分类账", "主导ledger", "主导分类账"),
            ("salesorder", "sales order", "销售订单", "销货订单"),
            ("deliverydocument", "outbounddelivery", "outbound delivery", "delivery", "交货单", "交货凭证", "出库交货"),
            ("orderid", "reference document", "referencesddocument", "参考文档", "参考凭证"),
            ("customer", "soldtoparty", "shiptoparty", "客户", "售达方", "收货方"),
            ("billing", "billingstatus", "billing status", "invoice", "invoiced", "not billed", "unbilled", "开票", "未开票", "没开票", "发票"),
            ("goodsmovement", "goods movement", "goods issue", "shipped", "delivered", "已发货", "发货", "已交货", "货物移动"),
        )
        synonym_groups = (
            *synonym_groups,
            ("supplier", "vendor", "供应商"),
            ("material", "product", "物料", "产品"),
            ("name", "names", "名称", "名字"),
            ("purchasinginforecord", "purchasing info record", "info record", "采购信息记录"),
            ("masterdata", "master data", "主数据"),
            ("productionorder", "production order", "生产订单"),
            ("operation", "operations", "工序", "作业"),
            ("component", "components", "组件"),
            ("stock", "inventory", "库存"),
            ("finishedproduct", "finished product", "成品"),
            ("workcenter", "work center", "work centers", "工作中心"),
            ("routing", "productionrouting", "production routing", "工艺路线", "工艺"),
        )
        for group in synonym_groups:
            query_matches = [
                LlmApiRouter._normalize_match_text(term)
                for term in group
                if LlmApiRouter._normalize_match_text(term) in query
            ]
            if not query_matches:
                continue
            if any(LlmApiRouter._normalize_match_text(term) in candidate for term in group):
                return True
        return False

    @staticmethod
    def _truncate(value: str, max_chars: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _contains_any_marker(user_input: str, markers: tuple[str, ...]) -> bool:
        raw = str(user_input or "").lower()
        compact_raw = re.sub(r"\s+", "", raw)
        normalized = LlmApiRouter._normalize_match_text(user_input)
        for marker in markers:
            marker_text = str(marker or "").lower()
            marker_compact = re.sub(r"\s+", "", marker_text)
            if marker_compact and marker_compact in compact_raw:
                return True
            normalized_marker = LlmApiRouter._normalize_match_text(marker_text)
            if normalized_marker and normalized_marker in normalized:
                return True
        return False

    def _materialize(
        self,
        parsed: dict[str, Any],
        api_catalog: list[dict[str, Any]],
        user_input: str,
    ) -> ApiRouteDecision:
        valid_services = {str(item.get("service_name", "")) for item in api_catalog}
        selected: list[SelectedApi] = []
        for item in parsed.get("selected_apis", []):
            if not isinstance(item, dict):
                continue
            service_name = str(item.get("service_name") or "")
            if service_name not in valid_services:
                continue
            selected.append(
                SelectedApi(
                    service_name=service_name,
                    confidence=self._float(item.get("confidence")),
                    reason=str(item.get("reason") or ""),
                )
            )
        selected = self._repair_incomplete_multi_api_selection(selected, parsed, valid_services)
        company_code_scoped_gl_request = self._looks_like_company_code_scoped_gl_request(user_input)
        selected = self._repair_company_code_scoped_gl_route(
            selected,
            valid_services,
            company_code_scoped_gl_request,
        )
        selected = self._repair_cost_center_master_route(selected, valid_services, user_input)
        selected = self._repair_trial_balance_route(selected, valid_services, user_input)
        selected = self._repair_operational_ap_ar_due_aging_route(selected, valid_services, user_input)
        selected = self._repair_journal_entry_item_route(selected, valid_services, user_input)
        selected = self._repair_operational_accounting_exception_route(selected, valid_services, user_input)
        selected = self._repair_gl_account_line_item_route(selected, valid_services, user_input)
        selected = self._repair_purchase_order_supplier_contact_route(selected, valid_services, user_input)
        selected = self._repair_skill_declared_companion_apis(
            selected,
            user_input=user_input,
            api_catalog=api_catalog,
            valid_services=valid_services,
        )
        if (
            not selected
            and valid_services
            and self.allow_default_fallback
            and not bool(parsed.get("needs_clarification", False))
        ):
            selected.append(SelectedApi(service_name=next(iter(valid_services)), confidence=0.0, reason="Fallback to first catalog API after invalid router selection."))
        needs_clarification = bool(parsed.get("needs_clarification", False))
        clarification_question = str(parsed.get("clarification_question") or "") or None
        clarification_options = [
            str(item)
            for item in parsed.get("clarification_options", [])
            if str(item).strip()
        ][:4]
        if selected and needs_clarification and self._looks_like_field_list_without_filter_intent(user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_read_only_bridge_permission(parsed):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and company_code_scoped_gl_request:
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_resolvable_trial_balance_request(selected, user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_resolvable_journal_entry_dimension_request(selected, user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_reference_to_fi_line_item_request(user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_ap_ar_due_aging_request(user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_resolvable_gl_line_item_request(selected, user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_cross_object_mapping_request(selected, user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_resolvable_production_order_operation_request(
            selected,
            user_input,
        ):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_company_scoped_list_request(user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_status_filtered_master_request(user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_master_attribute_request(user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_purchase_order_supplier_contact_request(user_input):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        if selected and needs_clarification and self._looks_like_resolvable_pricing_condition_request(
            selected,
            user_input,
            api_catalog,
        ):
            needs_clarification = False
            clarification_question = None
            clarification_options = []
        requires_multi_api = bool(parsed.get("requires_multi_api", False)) or len(selected) > 1
        materialized_raw_response = {
            **parsed,
            "selected_apis": [
                {
                    "service_name": item.service_name,
                    "confidence": item.confidence,
                    "reason": item.reason,
                }
                for item in selected
            ],
            "requires_multi_api": requires_multi_api,
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question or "",
            "clarification_options": clarification_options,
        }
        return ApiRouteDecision(
            resolved_user_input=str(parsed.get("resolved_user_input") or user_input),
            should_carry_context=bool(parsed.get("should_carry_context", False)),
            selected_apis=selected,
            requires_multi_api=requires_multi_api,
            intent_summary=str(parsed.get("intent_summary") or ""),
            business_domain=str(parsed.get("business_domain") or ""),
            business_object=str(parsed.get("business_object") or ""),
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            clarification_options=clarification_options,
            raw_response=materialized_raw_response,
        )

    @staticmethod
    def _repair_incomplete_multi_api_selection(
        selected: list[SelectedApi],
        parsed: dict[str, Any],
        valid_services: set[str],
    ) -> list[SelectedApi]:
        if not bool(parsed.get("requires_multi_api", False)):
            return selected
        selected_names = {item.service_name for item in selected}
        parsed_text = json.dumps(parsed, ensure_ascii=False)
        repaired = list(selected)
        for service_name in sorted(valid_services):
            if service_name in selected_names or service_name not in parsed_text:
                continue
            repaired.append(
                SelectedApi(
                    service_name=service_name,
                    confidence=0.5,
                    reason="Router marked the request as multi-API and mentioned this valid service in its reasoning.",
                )
            )
            selected_names.add(service_name)
            if len(repaired) >= 4:
                break
        return repaired

    @staticmethod
    def _repair_skill_declared_companion_apis(
        selected: list[SelectedApi],
        *,
        user_input: str,
        api_catalog: list[dict[str, Any]],
        valid_services: set[str],
    ) -> list[SelectedApi]:
        if not selected or not valid_services:
            return selected
        selected_names = {item.service_name for item in selected}
        catalog_by_service = {
            str(item.get("service_name") or ""): item
            for item in api_catalog
            if str(item.get("service_name") or "")
        }
        repaired = list(selected)
        for selected_item in selected:
            entry = catalog_by_service.get(selected_item.service_name) or {}
            relevant_lines = LlmApiRouter._relevant_skill_lines_for_prompt(
                str(entry.get("api_skill_summary") or ""),
                user_input=user_input,
                max_lines=20,
            )
            for line in relevant_lines:
                normalized_line = line.lower()
                if "do not use" in normalized_line or "don't use" in normalized_line:
                    if LlmApiRouter._negative_route_condition_excludes_request(line, user_input):
                        continue
                    replacement = LlmApiRouter._skill_declared_replacement_apis(
                        line,
                        selected_item.service_name,
                        valid_services,
                    )
                    if replacement and LlmApiRouter._companion_line_is_specific_enough(line, user_input):
                        preserved = [
                            item
                            for item in repaired
                            if item.service_name != selected_item.service_name
                        ]
                        selected_names.discard(selected_item.service_name)
                        for service_name in replacement:
                            if service_name in selected_names:
                                continue
                            preserved.append(
                                SelectedApi(
                                    service_name=service_name,
                                    confidence=0.62,
                                    reason=(
                                        "Selected API skill guidance explicitly routes this "
                                        "matched request to another API."
                                    ),
                                )
                            )
                            selected_names.add(service_name)
                        repaired = preserved
                    continue
                if not LlmApiRouter._companion_line_is_specific_enough(line, user_input):
                    continue
                for service_name in sorted(valid_services):
                    if service_name in selected_names or service_name not in line:
                        continue
                    repaired.append(
                        SelectedApi(
                            service_name=service_name,
                            confidence=0.55,
                            reason=(
                                "Selected API skill guidance references this companion API "
                                "for the user request."
                            ),
                        )
                    )
                    selected_names.add(service_name)
                    if len(repaired) >= 4:
                        return repaired
        return repaired

    @staticmethod
    def _skill_declared_replacement_apis(
        line: str,
        selected_service_name: str,
        valid_services: set[str],
    ) -> list[str]:
        lowered = str(line or "").lower()
        if "route" not in lowered and "use `" not in lowered and "use " not in lowered:
            return []
        services: list[str] = []
        for service_name in sorted(valid_services):
            if service_name == selected_service_name:
                continue
            if service_name not in line:
                continue
            route_index = lowered.find("route")
            service_index = line.find(service_name)
            if route_index >= 0 and service_index > route_index:
                services.append(service_name)
                continue
            if "use" in lowered[:service_index]:
                services.append(service_name)
        return services

    @staticmethod
    def _negative_route_condition_excludes_request(line: str, user_input: str) -> bool:
        lowered_line = str(line or "").lower()
        lowered_user = str(user_input or "").lower()
        exclusion_markers = ("without", "do not ask for", "does not ask for", "not ask for")
        for marker in exclusion_markers:
            index = lowered_line.find(marker)
            if index < 0:
                continue
            clause = lowered_line[index:]
            if "name" in clause and re.search(r"\bname\b|\bnames\b", lowered_user):
                return True
            if "master-data" in clause and "name" in lowered_user:
                return True
        return False

    @staticmethod
    def _companion_line_is_specific_enough(line: str, user_input: str) -> bool:
        query = LlmApiRouter._normalize_match_text(user_input)
        candidate = LlmApiRouter._normalize_match_text(line)
        if query and candidate and (query in candidate or candidate in query):
            return True

        synonym_groups = (
            ("company", "companycode", "company code"),
            ("journalentry", "journal entry", "line item", "line items"),
            ("costcenter", "cost center"),
            ("profitcenter", "profit center"),
            ("glaccount", "g/l account", "general ledger account", "总账科目", "会计科目", "科目"),
            ("balance", "trial balance", "account balance", "余额", "试算", "科目余额"),
            ("drilldown", "drill down", "line item", "line items", "下钻", "凭证明细", "行项目"),
            ("supplier", "vendor", "供应商"),
            ("material", "product", "物料", "产品"),
            ("name", "names", "名称"),
            ("purchasinginforecord", "purchasing info record", "info record", "采购信息记录"),
            ("plannedorder", "planned order", "计划订单"),
            ("productionorder", "production order", "生产订单"),
            ("operation", "operations", "工序", "作业"),
            ("component", "components", "组件", "部件"),
            ("stock", "inventory", "库存"),
            ("finishedproduct", "finished product", "成品"),
            ("workcenter", "work center", "work centers", "工作中心"),
            ("routing", "productionrouting", "production routing", "工艺路线", "工艺"),
            ("delivery", "deliverydocument", "outbounddelivery", "交货单"),
            ("billing", "invoice", "开票", "发票"),
        )
        matched_groups = 0
        query_text = str(user_input or "").lower()
        candidate_text = str(line or "").lower()
        for group in synonym_groups:
            query_has_group = any(
                LlmApiRouter._text_contains_business_term(query_text, term)
                for term in group
            )
            candidate_has_group = any(
                LlmApiRouter._text_contains_business_term(candidate_text, term)
                for term in group
            )
            if query_has_group and candidate_has_group:
                matched_groups += 1
        return matched_groups >= 2

    @staticmethod
    def _text_contains_business_term(text: str, term: str) -> bool:
        raw_term = str(term or "").lower().strip()
        if not raw_term:
            return False
        if re.fullmatch(r"[a-z0-9][a-z0-9 ]*[a-z0-9]", raw_term):
            pattern = r"(?<![a-z0-9])" + re.escape(raw_term) + r"(?![a-z0-9])"
            return re.search(pattern, text) is not None
        return LlmApiRouter._normalize_match_text(raw_term) in LlmApiRouter._normalize_match_text(text)

    @staticmethod
    def _looks_like_read_only_bridge_permission(parsed: dict[str, Any]) -> bool:
        text = json.dumps(parsed, ensure_ascii=False).lower()
        bridge_markers = (
            "allow first",
            "allow to first",
            "permission",
            "先查询",
            "允许先",
            "获取科目表",
            "bridge",
            "lookup",
        )
        read_markers = (
            "read",
            "query",
            "retrieve",
            "查询",
            "读取",
            "获取",
        )
        return any(marker in text for marker in bridge_markers) and any(
            marker in text for marker in read_markers
        )

    @staticmethod
    def _repair_company_code_scoped_gl_route(
        selected: list[SelectedApi],
        valid_services: set[str],
        company_code_scoped_gl_request: bool,
    ) -> list[SelectedApi]:
        gl_service = "API_GLACCOUNTINCHARTOFACCOUNTS_SRV"
        company_service = "API_COMPANYCODE_SRV"
        selected_names = {item.service_name for item in selected}
        if gl_service not in selected_names or company_service in selected_names:
            return selected
        if gl_service not in valid_services or company_service not in valid_services:
            return selected
        if not company_code_scoped_gl_request:
            return selected
        return [
            SelectedApi(
                service_name=company_service,
                confidence=0.6,
                reason="Company-code-scoped G/L account questions need the company code chart-of-accounts bridge.",
            ),
            *selected,
        ]

    @staticmethod
    def _repair_cost_center_master_route(
        selected: list[SelectedApi],
        valid_services: set[str],
        user_input: str,
    ) -> list[SelectedApi]:
        cost_center_service = "API_COSTCENTER_SRV"
        company_service = "API_COMPANYCODE_SRV"
        if cost_center_service not in valid_services:
            return selected
        if not LlmApiRouter._looks_like_cost_center_master_request(user_input):
            return selected
        selected_names = {item.service_name for item in selected}
        if cost_center_service in selected_names:
            return selected
        if selected_names == {company_service}:
            return [
                SelectedApi(
                    service_name=cost_center_service,
                    confidence=0.75,
                    reason="Cost-center master-data wording should use the cost center API; company code is only a filter.",
                )
            ]
        return selected

    @staticmethod
    def _looks_like_cost_center_master_request(user_input: str) -> bool:
        text = str(user_input or "").lower()
        if not any(marker in text for marker in ("成本中心", "cost center")):
            return False
        transactional_markers = (
            "财务行项目",
            "日记账",
            "总账行项目",
            "运营会计",
            "journal",
            "line item",
            "g/l line",
            "operational accounting",
        )
        return not any(marker in text for marker in transactional_markers)

    @staticmethod
    def _looks_like_company_code_scoped_gl_request(user_input: str) -> bool:
        normalized = LlmApiRouter._normalize_match_text(user_input)
        has_company = any(token in normalized for token in ("公司", "公司代码", "company", "companycode"))
        has_gl = any(
            token in normalized
            for token in (
                "科目表",
                "总账科目",
                "会计科目",
                "科目",
                "chartofaccounts",
                "glaccount",
                "generalledgeraccount",
            )
        )
        return has_company and has_gl

    @staticmethod
    def _repair_purchase_order_supplier_contact_route(
        selected: list[SelectedApi],
        valid_services: set[str],
        user_input: str,
    ) -> list[SelectedApi]:
        po_service = "API_PURCHASEORDER_PROCESS_SRV"
        bp_service = "API_BUSINESS_PARTNER"
        if po_service not in valid_services or bp_service not in valid_services:
            return selected
        if not LlmApiRouter._looks_like_purchase_order_supplier_contact_request(user_input):
            return selected

        selected_names = {item.service_name for item in selected}
        repaired = [item for item in selected if item.service_name in valid_services]
        if po_service not in selected_names:
            repaired.insert(
                0,
                SelectedApi(
                    service_name=po_service,
                    confidence=0.78,
                    reason="Purchase-order delivery scope must be resolved from the purchase order API.",
                ),
            )
        if bp_service not in selected_names:
            repaired.append(
                SelectedApi(
                    service_name=bp_service,
                    confidence=0.72,
                    reason="Supplier contact details must be resolved from business partner master data.",
                )
            )

        deduped: list[SelectedApi] = []
        seen: set[str] = set()
        for item in repaired:
            if item.service_name in seen:
                continue
            deduped.append(item)
            seen.add(item.service_name)
        return deduped

    @staticmethod
    def _looks_like_purchase_order_supplier_contact_request(user_input: str) -> bool:
        normalized = LlmApiRouter._normalize_match_text(user_input)
        if not normalized:
            return False

        def has_any(*terms: str) -> bool:
            return any(LlmApiRouter._normalize_match_text(term) in normalized for term in terms)

        has_purchase_order = has_any("purchase order", "purchaseorder", "po", "\u91c7\u8d2d\u8ba2\u5355")
        has_supplier = has_any("supplier", "vendor", "\u4f9b\u5e94\u5546")
        has_contact = has_any("contact", "contact person", "contact info", "\u8054\u7cfb\u4eba", "\u8054\u7cfb\u4fe1\u606f")
        has_delivery_scope = has_any(
            "delivery date",
            "arrival date",
            "arriving",
            "arrive",
            "\u5230\u8d27",
            "\u4ea4\u8d27",
            "\u9001\u8d27",
        )
        has_plant = has_any("plant", "\u5de5\u5382") or re.search(
            r"(?i)\bplant\s*[a-z0-9_-]+\b",
            user_input or "",
        ) is not None
        return has_purchase_order and has_supplier and has_contact and has_delivery_scope and has_plant

    @staticmethod
    def _repair_trial_balance_route(
        selected: list[SelectedApi],
        valid_services: set[str],
        user_input: str,
    ) -> list[SelectedApi]:
        trial_balance_service = "C_TRIALBALANCE_CDS"
        line_item_service = "API_GLACCOUNTLINEITEM"
        ledger_service = "API_LEDGER_SRV"
        if trial_balance_service not in valid_services:
            return selected
        if not LlmApiRouter._looks_like_trial_balance_financial_statement_request(user_input):
            return selected

        selected_names = {item.service_name for item in selected}
        drilldown = LlmApiRouter._looks_like_trial_balance_drilldown_request(user_input)
        replaced_services = {
            "API_JOURNALENTRYITEMBASIC_SRV",
            "API_OPLACCTGDOCITEMCUBE_SRV",
            "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
            "API_COMPANYCODE_SRV",
        }
        if drilldown:
            replaced_services.discard(line_item_service)
        repaired = [item for item in selected if item.service_name not in replaced_services]
        if trial_balance_service not in selected_names:
            trial_balance_api = SelectedApi(
                service_name=trial_balance_service,
                confidence=0.78,
                reason=(
                    "Trial balance, G/L balance, financial statement balance, and P&L amount "
                    "wording should use the parameterized trial balance API."
                ),
            )
            if drilldown and any(item.service_name == line_item_service for item in repaired):
                repaired.append(trial_balance_api)
            else:
                repaired.insert(0, trial_balance_api)
        if drilldown and line_item_service in valid_services and line_item_service not in selected_names:
            repaired.append(
                SelectedApi(
                    service_name=line_item_service,
                    confidence=0.7,
                    reason="Financial statement or balance drilldown needs G/L line items as the detail API.",
                )
            )
        if (
            LlmApiRouter._looks_like_trial_balance_all_ledgers_request(user_input)
            and ledger_service in valid_services
            and ledger_service not in {item.service_name for item in repaired}
        ):
            repaired.append(
                SelectedApi(
                    service_name=ledger_service,
                    confidence=0.65,
                    reason="All-ledger trial balance requests need the ledger master API to enumerate ledgers.",
                )
            )
        return repaired

    @staticmethod
    def _looks_like_trial_balance_financial_statement_request(user_input: str) -> bool:
        balance_markers = (
            "trialbalance",
            "glaccountbalance",
            "g/laccountbalance",
            "financialstatement",
            "balancesheet",
            "profitandloss",
            "profitloss",
            "试算表",
            "试算平衡",
            "科目余额",
            "总账余额",
            "总账科目余额",
            "余额",
            "财务报表",
            "资产负债表",
            "损益表",
            "损益金额",
        )
        blocked_detail_markers = ("openitem", "未清项目", "未清项", "清账关系")
        return LlmApiRouter._contains_any_marker(user_input, balance_markers) and not LlmApiRouter._contains_any_marker(
            user_input, blocked_detail_markers
        )

    @staticmethod
    def _looks_like_trial_balance_drilldown_request(user_input: str) -> bool:
        return LlmApiRouter._looks_like_trial_balance_financial_statement_request(
            user_input
        ) and LlmApiRouter._contains_any_marker(
            user_input,
            (
                "drilldown",
                "drillinto",
                "lineitem",
                "lineitems",
                "下钻",
                "凭证明细",
                "行项目",
                "明细",
            ),
        )

    @staticmethod
    def _looks_like_trial_balance_all_ledgers_request(user_input: str) -> bool:
        return LlmApiRouter._contains_any_marker(
            user_input,
            (
                "differentledger",
                "differentledgers",
                "allledger",
                "allledgers",
                "byledger",
                "parallelledger",
                "parallelledgers",
                "不同分类账",
                "各分类账",
                "所有分类账",
                "平行分类账",
                "按分类账",
                "不同ledger",
                "各ledger",
            ),
        )

    @staticmethod
    def _looks_like_resolvable_trial_balance_request(
        selected: list[SelectedApi],
        user_input: str,
    ) -> bool:
        if "C_TRIALBALANCE_CDS" not in {item.service_name for item in selected}:
            return False
        text = str(user_input or "")
        has_company = re.search(r"(?:公司(?:代码)?|company\s*code|company)\s*[:：=\-\s]*(\d{3,8})", text, re.I)
        has_year = re.search(r"(?<!\d)(20\d{2}|19\d{2})\s*(?:年|\b)", text)
        return bool(has_company and has_year and LlmApiRouter._looks_like_trial_balance_financial_statement_request(text))

    @staticmethod
    def _repair_operational_ap_ar_due_aging_route(
        selected: list[SelectedApi],
        valid_services: set[str],
        user_input: str,
    ) -> list[SelectedApi]:
        operational_item_service = "API_OPLACCTGDOCITEMCUBE_SRV"
        line_item_service = "API_GLACCOUNTLINEITEM"
        if operational_item_service not in valid_services:
            return selected
        if not LlmApiRouter._looks_like_ap_ar_due_aging_request(user_input):
            return selected
        selected_names = {item.service_name for item in selected}
        repaired = [
            item
            for item in selected
            if item.service_name
            not in {
                "API_JOURNALENTRYITEMBASIC_SRV",
                "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                "C_TRIALBALANCE_CDS",
                "API_COMPANYCODE_SRV",
            }
        ]
        if operational_item_service not in selected_names:
            repaired.insert(
                0,
                SelectedApi(
                    service_name=operational_item_service,
                    confidence=0.78,
                    reason="AP/AR aging, overdue, net due date, and payment block wording needs operational accounting item fields.",
                ),
            )
        if (
            LlmApiRouter._looks_like_ap_ar_reconciliation_request(user_input)
            and line_item_service in valid_services
            and line_item_service not in {item.service_name for item in repaired}
        ):
            repaired.append(
                SelectedApi(
                    service_name=line_item_service,
                    confidence=0.65,
                    reason="Reconciliation wording also needs G/L line items for the open-item detail side.",
                )
            )
        return repaired

    @staticmethod
    def _looks_like_ap_ar_due_aging_request(user_input: str) -> bool:
        partner_scope = (
            "supplier",
            "vendor",
            "customer",
            "ap",
            "ar",
            "供应商",
            "客户",
            "应付",
            "应收",
            "付款",
            "收款",
        )
        due_aging_scope = (
            "aging",
            "overdue",
            "duedate",
            "netduedate",
            "paymentblock",
            "paymentblocked",
            "账龄",
            "逾期",
            "到期",
            "付款冻结",
            "冻结",
            "未清应付",
            "未清应收",
            "还没收款",
            "未收款",
            "应付项目",
            "应收项目",
        )
        return LlmApiRouter._contains_any_marker(user_input, partner_scope) and LlmApiRouter._contains_any_marker(
            user_input, due_aging_scope
        )

    @staticmethod
    def _looks_like_ap_ar_reconciliation_request(user_input: str) -> bool:
        return LlmApiRouter._contains_any_marker(
            user_input, ("reconcile", "reconciliation", "核对", "对账")
        ) and LlmApiRouter._contains_any_marker(
            user_input, ("lineitem", "lineitems", "行项目", "明细")
        )

    @staticmethod
    def _repair_gl_account_line_item_route(
        selected: list[SelectedApi],
        valid_services: set[str],
        user_input: str,
    ) -> list[SelectedApi]:
        line_item_service = "API_GLACCOUNTLINEITEM"
        journal_service = "API_JOURNALENTRYITEMBASIC_SRV"
        operational_item_service = "API_OPLACCTGDOCITEMCUBE_SRV"
        company_service = "API_COMPANYCODE_SRV"
        ledger_service = "API_LEDGER_SRV"
        trial_balance_service = "C_TRIALBALANCE_CDS"
        if line_item_service not in valid_services:
            return selected
        if LlmApiRouter._looks_like_reference_to_fi_line_item_request(user_input):
            repaired = [item for item in selected if item.service_name != line_item_service]
            repaired.insert(
                0,
                SelectedApi(
                    service_name=line_item_service,
                    confidence=0.78,
                    reason="Reference-document tracing to FI/accounting line items should use GLAccountLineItem.ReferenceDocument first.",
                ),
            )
            return repaired
        if LlmApiRouter._looks_like_ar_dimension_analysis_request(user_input):
            repaired = [
                item
                for item in selected
                if item.service_name
                not in {journal_service, operational_item_service, company_service, line_item_service, trial_balance_service}
            ]
            repaired.insert(
                0,
                SelectedApi(
                    service_name=line_item_service,
                    confidence=0.78,
                    reason="AR dimension analysis by customer group, sales organization, or profit center needs G/L line item dimensions.",
                ),
            )
            return repaired
        if not LlmApiRouter._looks_like_gl_account_line_item_request(user_input):
            return selected
        selected_names = {item.service_name for item in selected}
        if journal_service in selected_names and LlmApiRouter._looks_like_journal_entry_item_request(user_input):
            return selected
        if LlmApiRouter._looks_like_partner_special_gl_item_request(user_input):
            repaired = [
                item
                for item in selected
                if item.service_name
                not in {
                    "API_BUSINESS_PARTNER",
                    journal_service,
                    operational_item_service,
                    company_service,
                    line_item_service,
                    trial_balance_service,
                }
            ]
            repaired.insert(
                0,
                SelectedApi(
                    service_name=line_item_service,
                    confidence=0.78,
                    reason="Partner special G/L item wording needs transaction line items with SpecialGLCode.",
                ),
            )
            return repaired
        if (
            operational_item_service in selected_names
            and LlmApiRouter._looks_like_ap_ar_due_aging_request(user_input)
        ):
            if line_item_service in selected_names:
                return selected
            return [
                *selected,
                SelectedApi(
                    service_name=line_item_service,
                    confidence=0.65,
                    reason="Open-item detail wording also needs G/L line items alongside operational AP/AR due-date data.",
                ),
            ]
        if line_item_service in selected_names and journal_service not in selected_names:
            if (
                LlmApiRouter._looks_like_leading_ledger_request(user_input)
                and ledger_service in valid_services
                and ledger_service not in selected_names
            ):
                return [
                    SelectedApi(
                        service_name=ledger_service,
                        confidence=0.7,
                        reason="Leading-ledger G/L line item requests need the ledger master API to resolve the leading ledger.",
                    ),
                    *selected,
                ]
            return selected
        repaired = [
            item
            for item in selected
            if item.service_name
            not in {journal_service, operational_item_service, company_service, line_item_service, trial_balance_service}
        ]
        if (
            LlmApiRouter._looks_like_leading_ledger_request(user_input)
            and ledger_service in valid_services
            and all(item.service_name != ledger_service for item in repaired)
        ):
            repaired.append(
                SelectedApi(
                    service_name=ledger_service,
                    confidence=0.7,
                    reason="Leading-ledger G/L line item requests need the ledger master API to resolve the leading ledger.",
                )
            )
        repaired.append(
            SelectedApi(
                service_name=line_item_service,
                confidence=0.75,
                reason="G/L account line item wording should use the dedicated G/L account line item API.",
            )
        )
        return repaired

    @staticmethod
    def _looks_like_gl_account_line_item_request(user_input: str) -> bool:
        text = str(user_input or "").lower()
        if LlmApiRouter._looks_like_reference_to_fi_line_item_request(user_input):
            return True
        if LlmApiRouter._looks_like_ar_dimension_analysis_request(user_input):
            return True
        explicit_line_item_terms = (
            "glaccountlineitem",
            "generalledgerlineitem",
            "journalentrylineitem",
            "总账行项目",
            "总账科目明细",
            "会计凭证行项目",
            "财务凭证行项目",
            "凭证明细",
            "行项目",
        )
        if LlmApiRouter._contains_any_marker(user_input, explicit_line_item_terms):
            return True
        if LlmApiRouter._looks_like_ap_ar_due_aging_request(user_input) and not any(
            LlmApiRouter._contains_any_marker(user_input, (term,))
            for term in ("未清行项目", "行项目", "明细", "核对", "对账")
        ):
            return False
        partner_line_item_terms = (
            "未清项目",
            "未清应付项目",
            "未清应收项目",
            "还没收款清账",
            "已清项目",
            "已经清账",
            "清账日期",
            "清账关系",
            "特殊总账",
            "统驭科目",
            "应付余额结构",
            "应收明细",
            "应付项目",
            "应收项目",
        )
        partner_scope_terms = ("供应商", "客户", "supplier", "vendor", "customer", "应付", "应收")
        if LlmApiRouter._contains_any_marker(user_input, partner_line_item_terms) and LlmApiRouter._contains_any_marker(
            user_input, partner_scope_terms
        ):
            return True
        markers = (
            "总账行项目",
            "总账行项目清单",
            "g/l account line item",
            "g/l account line items",
            "gl account line item",
            "gl account line items",
            "general ledger line item",
            "general ledger line items",
        )
        if any(marker in text for marker in markers):
            return True

        gl_account_markers = (
            "总账科目",
            "g/l科目",
            "g/l account",
            "gl account",
            "general ledger account",
        )
        line_item_semantics = (
            "发生明细",
            "明细账",
            "未清项目",
            "未清项目日期",
            "已清项目",
            "还没有清账",
            "没有清账",
            "尚未清账",
            "已经清账",
            "清账日期",
            "clearing date",
            "open item",
            "open items",
            "cleared item",
            "cleared items",
            "not cleared",
            "line item detail",
            "line item details",
            "费用明细",
            "科目明细",
            "归集",
        )
        has_line_item_semantics = any(marker in text for marker in line_item_semantics)
        if not has_line_item_semantics:
            return False
        if any(marker in text for marker in gl_account_markers):
            return True
        has_account_number = re.search(
            r"(?:科目|account)\s*[:：#-]?\s*[a-z0-9]{4,}",
            str(user_input or ""),
            flags=re.IGNORECASE,
        )
        return has_account_number is not None

    @staticmethod
    def _looks_like_reference_to_fi_line_item_request(user_input: str) -> bool:
        reference_terms = (
            "ReferenceDocument",
            "reference document",
            "business reference",
            "业务参考凭证",
            "参考凭证",
            "源凭证",
        )
        accounting_terms = (
            "财务凭证行项目",
            "会计凭证行项目",
            "财务凭证",
            "会计凭证",
            "FI document",
            "accounting document",
            "journal entry",
        )
        trace_terms = (
            "追溯",
            "产生",
            "生成",
            "对应",
            "line item",
            "line items",
            "行项目",
        )
        return (
            LlmApiRouter._contains_any_marker(user_input, reference_terms)
            and LlmApiRouter._contains_any_marker(user_input, accounting_terms)
            and LlmApiRouter._contains_any_marker(user_input, trace_terms)
        )

    @staticmethod
    def _repair_operational_accounting_exception_route(
        selected: list[SelectedApi],
        valid_services: set[str],
        user_input: str,
    ) -> list[SelectedApi]:
        operational_item_service = "API_OPLACCTGDOCITEMCUBE_SRV"
        if operational_item_service not in valid_services:
            return selected
        if not LlmApiRouter._looks_like_operational_accounting_exception_request(user_input):
            return selected
        selected_names = {item.service_name for item in selected}
        if operational_item_service in selected_names:
            return selected
        replaced_services = {
            "API_GLACCOUNTLINEITEM",
            "API_JOURNALENTRYITEMBASIC_SRV",
            "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
        }
        repaired = [item for item in selected if item.service_name not in replaced_services]
        repaired.append(
            SelectedApi(
                service_name=operational_item_service,
                confidence=0.76,
                reason="Accounting exception wording with manual document type, creator, or amount threshold should use the operational accounting document item cube.",
            )
        )
        return repaired

    @staticmethod
    def _looks_like_operational_accounting_exception_request(user_input: str) -> bool:
        text = str(user_input or "").lower()
        exception_markers = (
            "手工凭证",
            "凭证类型",
            "过账用户",
            "大额",
            "金额超过",
            "金额大于",
            "异常项目",
            "manual document",
            "document type",
            "created by",
            "large amount",
            "amount over",
            "amount greater",
        )
        accounting_scope_markers = (
            "总账项目",
            "会计凭证",
            "财务凭证",
            "会计项目",
            "accounting document",
            "accounting item",
            "g/l item",
            "gl item",
        )
        return any(marker in text for marker in exception_markers) and any(
            marker in text for marker in accounting_scope_markers
        )

    @staticmethod
    def _repair_journal_entry_item_route(
        selected: list[SelectedApi],
        valid_services: set[str],
        user_input: str,
    ) -> list[SelectedApi]:
        journal_service = "API_JOURNALENTRYITEMBASIC_SRV"
        line_item_service = "API_GLACCOUNTLINEITEM"
        operational_item_service = "API_OPLACCTGDOCITEMCUBE_SRV"
        if journal_service not in valid_services:
            return selected
        if not LlmApiRouter._looks_like_journal_entry_item_request(user_input):
            return selected
        selected_names = {item.service_name for item in selected}
        if journal_service in selected_names:
            return selected
        if line_item_service not in selected_names and operational_item_service not in selected_names:
            return selected
        repaired = [
            item
            for item in selected
            if item.service_name not in {line_item_service, operational_item_service}
        ]
        repaired.append(
            SelectedApi(
                service_name=journal_service,
                confidence=0.75,
                reason="Journal-entry item wording should use the journal entry item API, not another accounting line-item API.",
            )
        )
        return repaired

    @staticmethod
    def _looks_like_journal_entry_item_request(user_input: str) -> bool:
        text = str(user_input or "").lower()
        markers = (
            "日记账行项目",
            "日记帐行项目",
            "会计行项目",
            "财务行项目",
            "journal entry item",
            "journal entry items",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _looks_like_resolvable_journal_entry_dimension_request(
        selected: list[SelectedApi],
        user_input: str,
    ) -> bool:
        selected_names = {item.service_name for item in selected}
        if "API_JOURNALENTRYITEMBASIC_SRV" not in selected_names:
            return False
        if not LlmApiRouter._looks_like_journal_entry_item_request(user_input):
            return False
        text = str(user_input or "").lower()
        dimension_markers = (
            "职能范围",
            "功能范围",
            "成本中心",
            "利润中心",
            "客户",
            "工厂",
            "会计期间",
            "functional area",
            "cost center",
            "profit center",
            "customer",
            "plant",
            "fiscal year period",
        )
        return any(marker in text for marker in dimension_markers)

    @staticmethod
    def _looks_like_cross_object_mapping_request(
        selected: list[SelectedApi],
        user_input: str,
    ) -> bool:
        if len({item.service_name for item in selected}) < 2:
            return False
        text = str(user_input or "").lower()
        mapping_markers = (
            "对应",
            "关联",
            "分配",
            "映射",
            "关系",
            "mapping",
            "assignment",
            "assigned",
            "related",
        )
        scope_markers = (
            "公司",
            "公司代码",
            "工厂",
            "客户",
            "供应商",
            "物料",
            "company",
            "plant",
            "customer",
            "supplier",
            "material",
        )
        return any(marker in text for marker in mapping_markers) and any(marker in text for marker in scope_markers)

    @staticmethod
    def _looks_like_resolvable_production_order_operation_request(
        selected: list[SelectedApi],
        user_input: str,
    ) -> bool:
        selected_names = {item.service_name for item in selected}
        if "API_PRODUCTION_ORDER_2_SRV" not in selected_names:
            return False
        normalized = LlmApiRouter._normalize_match_text(user_input)
        has_production_order = any(
            marker in normalized
            for marker in (
                "productionorder",
                "manufacturingorder",
                "生产订单",
            )
        )
        has_operation = any(
            marker in normalized
            for marker in (
                "operation",
                "operations",
                "工序",
                "作业",
            )
        )
        has_resolvable_scope = any(
            marker in normalized
            for marker in (
                "plant",
                "工厂",
                "workcenter",
                "工作中心",
                "manufacturingorder",
            )
        )
        return has_production_order and has_operation and has_resolvable_scope

    @staticmethod
    def _looks_like_company_scoped_list_request(user_input: str) -> bool:
        text = str(user_input or "").lower()
        if any(marker in text for marker in ("哪个", "哪一个", "具体哪个", "specific", "which one")):
            return False
        has_company_scope = any(marker in text for marker in ("公司", "公司代码", "company", "company code"))
        has_list_object = any(
            marker in text
            for marker in (
                "有哪些",
                "哪些",
                "所有",
                "列表",
                "清单",
                "名称",
                "英文名称",
                "assigned",
                "assignment",
                "list",
                "names",
            )
        )
        return has_company_scope and has_list_object

    @staticmethod
    def _looks_like_status_filtered_master_request(user_input: str) -> bool:
        text = str(user_input or "").lower()
        status_markers = (
            "冻结",
            "锁定",
            "禁止",
            "blocked",
            "frozen",
            "locked",
        )
        object_markers = (
            "利润中心",
            "成本中心",
            "供应商",
            "客户",
            "物料",
            "profit center",
            "cost center",
            "supplier",
            "customer",
            "material",
        )
        return any(marker in text for marker in status_markers) and any(marker in text for marker in object_markers)

    @staticmethod
    def _looks_like_master_attribute_request(user_input: str) -> bool:
        text = str(user_input or "").lower()
        object_markers = (
            "利润中心",
            "成本中心",
            "供应商",
            "客户",
            "物料",
            "profit center",
            "cost center",
            "supplier",
            "customer",
            "material",
        )
        attribute_markers = (
            "标准层级",
            "层级",
            "类别",
            "类型",
            "负责人",
            "货币",
            "standard hierarchy",
            "hierarchy",
            "category",
            "type",
            "responsible",
            "currency",
        )
        return any(marker in text for marker in object_markers) and any(marker in text for marker in attribute_markers)

    @staticmethod
    def _looks_like_resolvable_pricing_condition_request(
        selected: list[SelectedApi],
        user_input: str,
        api_catalog: list[dict[str, Any]],
    ) -> bool:
        query = LlmApiRouter._normalize_match_text(user_input)
        if not query:
            return False
        pricing_terms = {
            "price",
            "pricing",
            "condition",
            "conditions",
            "pricecondition",
            "pricingcondition",
            "价格",
            "定价",
            "条件",
            "价格条件",
            "定价条件",
        }
        if not any(LlmApiRouter._normalize_match_text(term) in query for term in pricing_terms):
            return False

        selected_names = {item.service_name for item in selected}
        for entry in api_catalog:
            if str(entry.get("service_name") or "") not in selected_names:
                continue
            evidence = json.dumps(
                {
                    "top_entities": entry.get("top_entities") or [],
                    "top_filter_fields": entry.get("top_filter_fields") or [],
                    "top_answer_fields": entry.get("top_answer_fields") or [],
                    "api_skill_summary": entry.get("api_skill_summary") or "",
                    "primary_business_objects": entry.get("primary_business_objects") or [],
                },
                ensure_ascii=False,
            ).lower()
            if any(
                marker in evidence
                for marker in (
                    "pric",
                    "prcg",
                    "conditiontype",
                    "conditionamount",
                    "conditioncurrency",
                    "pricingprocedurestep",
                    "定价",
                    "价格条件",
                )
            ):
                return True
        return False

    @staticmethod
    def _looks_like_partner_special_gl_item_request(user_input: str) -> bool:
        return LlmApiRouter._contains_any_marker(
            user_input,
            ("特殊总账", "special g/l", "special gl", "specialgl", "special general ledger"),
        ) and LlmApiRouter._contains_any_marker(
            user_input,
            ("项目", "明细", "行项目", "供应商", "客户", "supplier", "vendor", "customer", "item", "line item"),
        )

    @staticmethod
    def _looks_like_ar_dimension_analysis_request(user_input: str) -> bool:
        return LlmApiRouter._contains_any_marker(
            user_input,
            ("应收", "客户", "receivable", "ar", "customer"),
        ) and LlmApiRouter._contains_any_marker(
            user_input,
            (
                "客户组",
                "销售组织",
                "利润中心",
                "customergroup",
                "customer group",
                "salesorganization",
                "sales organization",
                "profitcenter",
                "profit center",
            ),
        )

    @staticmethod
    def _looks_like_resolvable_gl_line_item_request(selected: list[SelectedApi], user_input: str) -> bool:
        if "API_GLACCOUNTLINEITEM" not in {item.service_name for item in selected}:
            return False
        if not LlmApiRouter._looks_like_gl_account_line_item_request(user_input):
            return False
        return LlmApiRouter._contains_any_marker(
            user_input,
            (
                "公司",
                "公司代码",
                "供应商",
                "客户",
                "科目",
                "凭证",
                "supplier",
                "vendor",
                "customer",
                "company",
                "company code",
                "gl account",
            ),
        )

    @staticmethod
    def _looks_like_leading_ledger_request(user_input: str) -> bool:
        text = str(user_input or "").lower()
        return any(marker in text for marker in ("主导ledger", "主导分类账", "leading ledger"))

    def _unavailable_route(self, api_catalog: list[dict[str, Any]]) -> ApiRouteDecision:
        if not self.allow_default_fallback:
            return ApiRouteDecision(
                selected_apis=[],
                raw_response={"accepted": False, "reason": "api_router_unavailable"},
            )
        service_name = (
            self.default_service_name
            if any(item.get("service_name") == self.default_service_name for item in api_catalog)
            else str((api_catalog[0] if api_catalog else {}).get("service_name") or self.default_service_name)
        )
        return ApiRouteDecision(
            selected_apis=[SelectedApi(service_name=service_name, confidence=0.0, reason="router_unavailable")],
            raw_response={"accepted": False, "reason": "router_unavailable"},
        )

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _looks_like_field_list_without_filter_intent(user_input: str) -> bool:
        text = f" {user_input or ''} ".lower()
        field_list_markers = (
            " with ",
            " include ",
            " includes ",
            " including ",
            " display ",
            " show ",
            " list ",
        )
        if not any(marker in text for marker in field_list_markers):
            return False
        explicit_filter_markers = (
            " only ",
            " where ",
            " equal ",
            " equals ",
            " greater than ",
            " less than ",
            " at least ",
            " at most ",
            " nonzero ",
            " non-zero ",
            " true ",
            " false ",
            " open ",
            " closed ",
            " completed ",
            " incomplete ",
            " unreceived ",
            " undelivered ",
            " pending ",
            " overdue ",
            " not yet ",
            "仅",
            "只",
            "大于",
            "小于",
            "等于",
            "为",
            "是",
            "否",
            "未",
            "已",
        )
        return not any(marker in text for marker in explicit_filter_markers)
