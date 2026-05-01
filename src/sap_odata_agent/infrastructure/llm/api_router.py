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
        if not self.enabled or self.llm_client is None:
            return self._unavailable_route(api_catalog)
        payload = {
            "user_input": user_input,
            "api_catalog": self._compact_catalog_for_prompt(api_catalog, user_input=user_input),
            "recent_cases": self._compact_recent_cases_for_prompt(recent_cases or []),
            "latest_clarification_case": self._compact_case_for_prompt(latest_clarification_case or {}),
            "feedback_memories": self._compact_feedback_memories_for_prompt(feedback_memories or []),
        }
        example = {
            "resolved_user_input": user_input,
            "should_carry_context": False,
            "selected_apis": [
                {
                    "service_name": api_catalog[0]["service_name"] if api_catalog else self.default_service_name,
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
            raw = self._complete_nonempty_json_text(self._system_prompt(), user_prompt, max_tokens=1100)
            try:
                parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
            except json.JSONDecodeError:
                repaired_raw = self._complete_nonempty_json_text(
                    self._json_repair_system_prompt(),
                    self._json_repair_prompt(raw, example),
                    max_tokens=900,
                    attempts=1,
                )
                parsed = LlmStructuredIntentPlanner._parse_json_object(repaired_raw)
        except Exception as exc:
            fallback = self._unavailable_route(api_catalog)
            fallback.raw_response = {"accepted": False, "reason": f"api_router_failed:{exc}"}
            return fallback
        return self._materialize(parsed, api_catalog, user_input)

    @staticmethod
    def _system_prompt() -> str:
        return f"{GLOBAL_SAP_ODATA_PROMPT}\n\n{API_ROUTER_TASK_PROMPT}"

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
                item["api_skill_summary"] = LlmApiRouter._truncate(skill_summary, 120)
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
        for value in cleaned[base_limit:]:
            if len(selected) >= max_limit:
                break
            if value not in selected and LlmApiRouter._value_matches_user_input(value, user_input):
                selected.append(value)
        return selected

    @staticmethod
    def _value_matches_user_input(value: str, user_input: str) -> bool:
        query = LlmApiRouter._normalize_match_text(user_input)
        candidate = LlmApiRouter._normalize_match_text(value)
        if not query or not candidate:
            return False
        return candidate in query or query in candidate or any(
            len(token) >= 4 and token in candidate
            for token in LlmApiRouter._match_tokens(user_input)
        )

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
    def _truncate(value: str, max_chars: int) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

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
        return ApiRouteDecision(
            resolved_user_input=str(parsed.get("resolved_user_input") or user_input),
            should_carry_context=bool(parsed.get("should_carry_context", False)),
            selected_apis=selected,
            requires_multi_api=bool(parsed.get("requires_multi_api", False)),
            intent_summary=str(parsed.get("intent_summary") or ""),
            business_domain=str(parsed.get("business_domain") or ""),
            business_object=str(parsed.get("business_object") or ""),
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            clarification_options=clarification_options,
            raw_response=parsed,
        )

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
