from __future__ import annotations

import re

from sap_odata_agent.domain.models import ContextCarryDecision, QueryShape


class ContextCarryGate:
    ACTION_TERMS = ("查", "列出", "查询", "帮我", "显示", "告诉我", "给我", "show", "list", "query", "find", "what", "which")
    CONTEXTUAL_REPLY_TERMS = (
        "没有时间限制",
        "不限",
        "全部",
        "所有",
        "无",
        "没有",
        "all",
        "any",
        "none",
        "no limit",
    )

    def decide(
        self,
        current_input: str,
        query_shape: QueryShape,
        latest_clarification_case: dict | None,
    ) -> ContextCarryDecision:
        if latest_clarification_case is None:
            return ContextCarryDecision(False, "no_clarification_context", 1.0)

        normalized = (current_input or "").strip()
        if not normalized:
            return ContextCarryDecision(False, "empty_input", 0.95)

        if self._looks_like_standalone_question(normalized):
            return ContextCarryDecision(False, "standalone_question_detected", 0.97)

        if self._looks_like_clarification_answer(normalized):
            return ContextCarryDecision(True, "short_contextual_reply_detected", 0.9)

        if query_shape in {QueryShape.LIST_QUERY, QueryShape.SEARCH_BY_ATTRIBUTE, QueryShape.NAME_CONTAINS_SEARCH, QueryShape.BOOLEAN_CHECK}:
            return ContextCarryDecision(False, "query_shape_indicates_new_question", 0.88)

        return ContextCarryDecision(False, "default_do_not_carry", 0.7)

    @classmethod
    def _looks_like_standalone_question(cls, text: str) -> bool:
        lowered = text.lower()
        has_action = any(term in lowered for term in cls.ACTION_TERMS)
        has_identifier = bool(re.search(r"\d{2,}", text))
        has_question_punctuation = "？" in text or "?" in text
        has_assignment_filter = bool(re.search(r"[\w\u4e00-\u9fff][\w\u4e00-\u9fff\s]{0,24}\s*(?:为|是|=|:|：)\s*[\w\u4e00-\u9fff\-]+", text))
        has_named_subject = bool(re.search(r"[\w\u4e00-\u9fff\-]{2,}\s*(?:的|下|中|里)", text))
        if has_action and (has_identifier or has_assignment_filter or has_named_subject):
            return True
        if has_question_punctuation and (has_identifier or has_assignment_filter or has_named_subject):
            return True
        if len(text) >= 12 and (has_action or has_assignment_filter):
            return True
        if len(text) >= 16 and has_named_subject:
            return True
        return False

    @classmethod
    def _looks_like_clarification_answer(cls, text: str) -> bool:
        lowered = text.lower()
        if len(text) > 24:
            return False
        if not re.fullmatch(r"[\w\u4e00-\u9fff\s\-_/]+", text):
            return False
        if re.fullmatch(r"\d{2,}", text):
            return True
        return any(term in lowered for term in cls.CONTEXTUAL_REPLY_TERMS)
