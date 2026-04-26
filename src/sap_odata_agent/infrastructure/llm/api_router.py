from __future__ import annotations

import json
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
            "api_catalog": api_catalog,
            "recent_cases": recent_cases or [],
            "latest_clarification_case": latest_clarification_case or {},
            "feedback_memories": feedback_memories or [],
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
        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                (
                    f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                    "Return JSON with this shape:\n"
                    f"{json.dumps(example, ensure_ascii=False, indent=2)}"
                ),
                max_tokens=1100,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            fallback = self._unavailable_route(api_catalog)
            fallback.raw_response = {"accepted": False, "reason": f"api_router_failed:{exc}"}
            return fallback
        return self._materialize(parsed, api_catalog, user_input)

    @staticmethod
    def _system_prompt() -> str:
        return f"{GLOBAL_SAP_ODATA_PROMPT}\n\n{API_ROUTER_TASK_PROMPT}"

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
        return ApiRouteDecision(
            resolved_user_input=str(parsed.get("resolved_user_input") or user_input),
            should_carry_context=bool(parsed.get("should_carry_context", False)),
            selected_apis=selected,
            requires_multi_api=bool(parsed.get("requires_multi_api", False)),
            intent_summary=str(parsed.get("intent_summary") or ""),
            business_domain=str(parsed.get("business_domain") or ""),
            business_object=str(parsed.get("business_object") or ""),
            needs_clarification=bool(parsed.get("needs_clarification", False)),
            clarification_question=str(parsed.get("clarification_question") or "") or None,
            clarification_options=[str(item) for item in parsed.get("clarification_options", []) if str(item).strip()][:4],
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
