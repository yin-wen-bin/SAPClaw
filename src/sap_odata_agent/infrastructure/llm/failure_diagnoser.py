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
                root_cause=self._localize_text(
                    payload,
                    str(payload.get("fallback_root_cause") or "LLM failure diagnosis is unavailable."),
                    "失败诊断不可用，请查看执行详情。",
                ),
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
                    "Use the same natural language as original_user_input/resolved_user_input for root_cause and suggested_next_action. Keep SAP technical field names unchanged.\n\n"
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
                root_cause=self._localize_text(
                    payload,
                    str(payload.get("fallback_root_cause") or f"Failure diagnosis LLM call failed: {exc}"),
                    "失败诊断调用失败，请查看执行详情。",
                ),
                evidence=[*fallback_evidence, f"failure_diagnosis_llm_error:{exc}"],
                suggested_next_action=self._localize_text(
                    payload,
                    str(payload.get("fallback_suggested_next_action") or ""),
                    "请根据执行详情重新规划查询。",
                ),
                raw_response={"diagnoser_error": str(exc)},
            )
        return FailureDiagnosis(
            category=str(parsed.get("category") or "unknown"),
            root_cause=self._localize_text(
                payload,
                str(parsed.get("root_cause") or ""),
                "查询失败原因无法用当前返回数据可靠确认，请查看执行详情。",
            ),
            evidence=[str(item) for item in parsed.get("evidence", [])],
            suggested_next_action=self._localize_text(
                payload,
                str(parsed.get("suggested_next_action") or ""),
                "请根据执行详情重新规划查询。",
            ),
            raw_response=parsed,
        )

    @staticmethod
    def _localize_text(payload: dict[str, Any], text: str, chinese_fallback: str) -> str:
        if not text:
            return text
        user_text = str(payload.get("resolved_user_input") or payload.get("original_user_input") or "")
        if not any("\u4e00" <= char <= "\u9fff" for char in user_text):
            return text
        if any("\u4e00" <= char <= "\u9fff" for char in text):
            return text
        return chinese_fallback
