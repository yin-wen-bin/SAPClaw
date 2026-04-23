from __future__ import annotations

import re

from sap_odata_agent.domain.models import CardinalityPolicy, QueryShape


class QueryShapeClassifier:
    LIST_TERMS = {
        "\u5217\u51fa",
        "\u5217\u8868",
        "\u90fd\u6709\u54ea\u4e9b",
        "\u6709\u54ea\u4e9b",
        "\u5168\u90e8",
        "\u6240\u6709",
        "\u6bcf\u4e2a",
        "list",
        "which",
        "what are",
    }
    BOOLEAN_TERMS = {
        "\u662f\u5426",
        "\u662f\u4e0d\u662f",
        "\u662f\u5426",
        "\u6709\u65e0",
        "is ",
        "does ",
        "flag",
        "true",
        "false",
    }
    CONTAINS_TERMS = {"\u5305\u542b", "\u540d\u5b57\u4e2d", "contains", "contain", "like"}
    OBJECT_TERMS = {
        "supplier": {"\u4f9b\u5e94\u5546", "supplier", "vendor"},
        "customer": {"\u5ba2\u6237", "customer"},
        "business_partner": {"\u4e1a\u52a1\u4f19\u4f34", "business partner", "bp"},
    }

    def classify(self, query: str, previous_clarification_question: str | None = None) -> tuple[QueryShape, CardinalityPolicy, dict]:
        text = (query or "").strip()
        lowered = text.lower()
        diagnostics = {"matched_terms": []}

        if any(term in lowered for term in self.CONTAINS_TERMS):
            diagnostics["matched_terms"].append("contains")
            if self._mentions_business_partner(lowered):
                return QueryShape.NAME_CONTAINS_SEARCH, CardinalityPolicy.MANY, diagnostics
            return QueryShape.SEARCH_BY_ATTRIBUTE, CardinalityPolicy.MANY, diagnostics

        if any(term in lowered for term in self.BOOLEAN_TERMS):
            diagnostics["matched_terms"].append("boolean")
            return QueryShape.BOOLEAN_CHECK, CardinalityPolicy.ONE, diagnostics

        if any(term in lowered for term in self.LIST_TERMS):
            diagnostics["matched_terms"].append("list")
            return QueryShape.LIST_QUERY, CardinalityPolicy.MANY, diagnostics

        if self._looks_like_attribute_filter(text):
            diagnostics["matched_terms"].append("attribute")
            cardinality = CardinalityPolicy.MANY if self._mentions_list_intent(lowered) else CardinalityPolicy.UNKNOWN
            return QueryShape.SEARCH_BY_ATTRIBUTE, cardinality, diagnostics

        if text:
            diagnostics["matched_terms"].append("fallback_single_fact")
            return QueryShape.SINGLE_FACT, CardinalityPolicy.ONE, diagnostics

        return QueryShape.UNKNOWN, CardinalityPolicy.UNKNOWN, diagnostics

    @classmethod
    def _mentions_list_intent(cls, lowered: str) -> bool:
        question_list_terms = {
            "\u54ea\u4e9b",
            "\u6709\u54ea\u4e9b",
            "\u90fd\u6709\u54ea\u4e9b",
            "\u67e5\u627e",
            "\u5bfb\u627e",
            "\u627e\u51fa",
        }
        return any(term in lowered for term in cls.LIST_TERMS) or any(term in lowered for term in question_list_terms)

    @classmethod
    def _mentions_business_partner(cls, lowered: str) -> bool:
        return any(term in lowered for term in cls.OBJECT_TERMS["business_partner"])

    @staticmethod
    def _looks_like_attribute_filter(text: str) -> bool:
        if not text:
            return False
        return bool(
            re.search(
                r"[\w\u4e00-\u9fff][\w\u4e00-\u9fff\s\-_/]{0,24}(?:\u4e3a|\u662f|=|:)\s*[\w\u4e00-\u9fff@.\-_/]{1,}",
                text,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"[\w\u4e00-\u9fff][\w\u4e00-\u9fff\s\-_/]{0,24}\s*[A-Za-z0-9_-]{2,}\s*(?:\u7684|\u4e0b|\u4e2d|\u91cc)",
                text,
                flags=re.IGNORECASE,
            )
            or (
                bool(re.search(r"[A-Za-z0-9_-]{2,}", text))
                and bool(re.search(r"(?:\u5b58\u5728\u4e8e|\u5c5e\u4e8e|\u4f4d\u4e8e)", text))
                and bool(re.search(r"(?:\u54ea\u4e9b|\u6240\u6709|\u5168\u90e8|which|all)", text, flags=re.IGNORECASE))
            )
        )
