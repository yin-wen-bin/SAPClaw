from __future__ import annotations

import json
from typing import Any

from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner


class LlmFeedbackSummarizer:
    """Convert user feedback into reusable planning memory."""

    def __init__(
        self,
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.enabled = enabled

    def summarize(self, case_entry: dict[str, Any]) -> dict[str, Any]:
        fallback = self._fallback_memory(case_entry)
        if not self.enabled or self.llm_client is None:
            return fallback
        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(case_entry),
                max_tokens=700,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception:
            return fallback

        memory = {
            **fallback,
            "memory_type": str(parsed.get("memory_type", fallback["memory_type"]) or fallback["memory_type"]),
            "lesson": str(parsed.get("lesson", fallback["lesson"]) or fallback["lesson"]),
            "user_phrases": self._string_list(parsed.get("user_phrases")) or fallback["user_phrases"],
            "preferred_fields": self._string_list(parsed.get("preferred_fields")),
            "preferred_entities": self._string_list(parsed.get("preferred_entities")),
            "rejected_fields": self._string_list(parsed.get("rejected_fields")),
            "condition": str(parsed.get("condition", "") or ""),
            "source": "llm_feedback_summarizer",
        }
        return memory

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You turn SAP OData query feedback into reusable planning memory. "
            "Extract general lessons, not one-off case patches. Return JSON only."
        )

    @staticmethod
    def _user_prompt(case_entry: dict[str, Any]) -> str:
        feedback = case_entry.get("feedback") or {}
        plan = case_entry.get("final_plan") or case_entry.get("initial_plan") or {}
        example = {
            "memory_type": "field_disambiguation",
            "lesson": "When the user's wording matches a metadata label or description, prefer that field over a similarly named but semantically different field.",
            "user_phrases": ["user phrase from feedback"],
            "preferred_fields": ["PreferredFieldFromMetadata"],
            "preferred_entities": ["PreferredEntityFromMetadata"],
            "rejected_fields": ["RejectedField"],
            "condition": "Use only when the future query has the same semantic distinction.",
        }
        payload = {
            "user_input": (case_entry.get("request") or {}).get("user_input", ""),
            "effective_user_input": case_entry.get("effective_user_input", ""),
            "final_status": case_entry.get("final_status", ""),
            "plan": {
                "entity_set": plan.get("entity_set", ""),
                "select_fields": plan.get("select_fields", []),
                "filters": plan.get("filters", []),
                "path_id": plan.get("path_id", ""),
            },
            "presentation": case_entry.get("presentation") or {},
            "feedback": {
                "status": feedback.get("status", ""),
                "comment": feedback.get("comment", ""),
                "expected_result": feedback.get("expected_result", ""),
            },
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Create a reusable lesson for future planning. Avoid hard-coding the specific identifier value unless the feedback is about identity parsing. "
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _fallback_memory(case_entry: dict[str, Any]) -> dict[str, Any]:
        feedback = case_entry.get("feedback") or {}
        request = case_entry.get("request") or {}
        plan = case_entry.get("final_plan") or case_entry.get("initial_plan") or {}
        return {
            "memory_type": "feedback_lesson",
            "lesson": " ".join(
                part
                for part in [
                    str(feedback.get("comment", "") or "").strip(),
                    str(feedback.get("expected_result", "") or "").strip(),
                ]
                if part
            ),
            "user_phrases": [str(request.get("user_input", "") or "")],
            "preferred_fields": [],
            "preferred_entities": [],
            "rejected_fields": [str(field) for field in plan.get("select_fields", []) or []],
            "condition": "",
            "source": "fallback_feedback_summarizer",
        }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
