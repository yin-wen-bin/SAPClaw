from __future__ import annotations

import json
from typing import Any

from sap_odata_agent.domain.models import FailureDiagnosis
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner
from sap_odata_agent.infrastructure.llm.prompts import FAILURE_DIAGNOSIS_TASK_PROMPT, GLOBAL_SAP_ODATA_PROMPT


class LlmFailureDiagnoser:
    def __init__(self, llm_client: AnthropicCompatibleMessagesClient | None = None, enabled: bool = True) -> None:
        self.llm_client = llm_client
        self.enabled = enabled

    def diagnose(self, payload: dict[str, Any]) -> FailureDiagnosis:
        if not self.enabled or self.llm_client is None:
            return FailureDiagnosis(
                category=str(payload.get("fallback_category") or "unknown"),
                root_cause=str(payload.get("fallback_root_cause") or "LLM failure diagnosis is unavailable."),
                evidence=[str(item) for item in payload.get("fallback_evidence", [])],
            )
        example = {
            "category": "api_routing_error | schema_gap | wrong_business_level | invalid_field | invalid_filter | path_binding_failure | odata_syntax_error | sap_runtime_error | authorization_or_network | empty_result | unknown",
            "root_cause": "",
            "evidence": [],
            "suggested_next_action": "",
        }
        try:
            raw = self.llm_client.complete_json(
                f"{GLOBAL_SAP_ODATA_PROMPT}\n\n{FAILURE_DIAGNOSIS_TASK_PROMPT}",
                (
                    f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}\n\n"
                    "Return JSON with this shape:\n"
                    f"{json.dumps(example, ensure_ascii=False, indent=2)}"
                ),
                max_tokens=900,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            fallback_evidence = [str(item) for item in payload.get("fallback_evidence", [])]
            return FailureDiagnosis(
                category=str(payload.get("fallback_category") or "unknown"),
                root_cause=str(payload.get("fallback_root_cause") or f"Failure diagnosis LLM call failed: {exc}"),
                evidence=[*fallback_evidence, f"failure_diagnosis_llm_error:{exc}"],
                suggested_next_action=str(payload.get("fallback_suggested_next_action") or ""),
                raw_response={"diagnoser_error": str(exc)},
            )
        return FailureDiagnosis(
            category=str(parsed.get("category") or "unknown"),
            root_cause=str(parsed.get("root_cause") or ""),
            evidence=[str(item) for item in parsed.get("evidence", [])],
            suggested_next_action=str(parsed.get("suggested_next_action") or ""),
            raw_response=parsed,
        )
