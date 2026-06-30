from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class KnowledgeGraphProvider:
    """Read-only local semantic grounding provider.

    The provider never executes SAP calls and never mutates query plans. It only
    returns compact evidence that downstream agents may use as semantic guidance.
    """

    def __init__(
        self,
        kg_root: str | Path = "data/knowledge_graph",
        *,
        enabled: bool = True,
        max_evidence: int = 5,
    ) -> None:
        self.kg_root = Path(kg_root)
        self.enabled = enabled
        self.max_evidence = max(1, int(max_evidence or 5))
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._data: dict[str, Any] = {}

    def recommend_apis(self, user_input: str) -> list[dict[str, Any]]:
        data = self._load()
        if not data:
            return []
        ranked: list[tuple[float, dict[str, Any]]] = []
        for fact in data.get("api_candidates", []):
            if not isinstance(fact, dict):
                continue
            score = self._fact_score(user_input, fact, fields=("terms", "business_objects", "evidence_text"))
            if score <= 0:
                continue
            confidence = float(fact.get("confidence") or 0.0)
            ranked.append(
                (
                    score + confidence,
                    {
                        "service_name": str(fact.get("service_name") or ""),
                        "confidence": round(min(1.0, confidence + min(score / 30.0, 0.35)), 3),
                        "reason": self._compact_text(str(fact.get("evidence_text") or ""), 220),
                        "matched_terms": self._matched_terms(user_input, fact.get("terms") or []),
                        "source": fact.get("source") or "",
                        "confirmed": bool(fact.get("confirmed", True)),
                        "evidence_text": self._compact_text(str(fact.get("evidence_text") or ""), 280),
                    },
                )
            )
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in ranked[: self.max_evidence] if item.get("service_name")]

    def recommend_fields(self, user_input: str, service_name: str) -> list[dict[str, Any]]:
        data = self._load()
        if not data:
            return []
        service = str(service_name or "")
        ranked: list[tuple[float, dict[str, Any]]] = []
        for fact in data.get("field_semantics", []):
            if not isinstance(fact, dict):
                continue
            if service and str(fact.get("service_name") or "") != service:
                continue
            score = self._fact_score(
                user_input,
                fact,
                fields=("supports_meaning", "does_not_support", "field_name", "evidence_text"),
            )
            if score <= 0:
                continue
            ranked.append((score + float(fact.get("confidence") or 0.0), self._compact_fact(fact)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in ranked[: self.max_evidence]]

    def recommend_paths(self, user_input: str, selected_apis: list[str]) -> list[dict[str, Any]]:
        data = self._load()
        if not data:
            return []
        selected = {str(name or "") for name in selected_apis if str(name or "")}
        ranked: list[tuple[float, dict[str, Any]]] = []
        for fact in data.get("business_paths", []):
            if not isinstance(fact, dict):
                continue
            services = {str(name or "") for name in fact.get("service_names") or [] if str(name or "")}
            if selected and services and not (selected & services):
                continue
            score = self._fact_score(user_input, fact, fields=("intent", "steps", "evidence_text"))
            if score <= 0:
                continue
            ranked.append((score + float(fact.get("confidence") or 0.0), self._compact_fact(fact)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in ranked[: self.max_evidence]]

    def business_terms(self, user_input: str, service_name: str = "") -> list[dict[str, Any]]:
        data = self._load()
        if not data:
            return []
        service = str(service_name or "")
        ranked: list[tuple[float, dict[str, Any]]] = []
        for fact in data.get("business_terms", []):
            if not isinstance(fact, dict):
                continue
            if service and str(fact.get("service_name") or "") != service:
                continue
            score = self._fact_score(user_input, fact, fields=("term", "semantic_role", "evidence_text"))
            if score <= 0:
                continue
            ranked.append((score + float(fact.get("confidence") or 0.0), self._compact_fact(fact)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in ranked[: self.max_evidence]]

    def semantic_warnings(self, user_input: str, plan: Any) -> list[dict[str, Any]]:
        data = self._load()
        if not data:
            return []
        plan_fields = self._plan_field_names(plan)
        service_name = str(getattr(plan, "service_name", "") or "")
        warnings: list[dict[str, Any]] = []
        for fact in data.get("field_semantics", []):
            if not isinstance(fact, dict):
                continue
            if service_name and str(fact.get("service_name") or "") not in ("", service_name):
                continue
            field_name = str(fact.get("field_name") or "")
            if field_name and field_name not in plan_fields:
                continue
            meaning = " ".join(str(item) for item in fact.get("does_not_support") or [])
            if not meaning:
                continue
            if self._fact_score(user_input, {"evidence_text": meaning}, fields=("evidence_text",)) <= 0:
                continue
            confirmed = bool(fact.get("confirmed", True))
            warnings.append(
                {
                    "code": "kg_semantic_warning",
                    "service_name": fact.get("service_name") or "",
                    "entity_set": fact.get("entity_set") or "",
                    "field_name": field_name,
                    "message": self._compact_text(str(fact.get("evidence_text") or meaning), 360),
                    "blocking": bool(fact.get("blocking")) and confirmed,
                    "confirmed": confirmed,
                    "confidence": fact.get("confidence", 0.0),
                    "repair_hints": fact.get("repair_hints") or {},
                    "source": fact.get("source") or "",
                }
            )
        return warnings[: self.max_evidence]

    def build_debug_payload(
        self,
        *,
        evidence_used: list[dict[str, Any]] | None = None,
        semantic_warnings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        data = self._load()
        summary = data.get("build_summary") if isinstance(data, dict) else {}
        return {
            "kg_enabled": bool(self.enabled),
            "kg_build_version": str((summary or {}).get("build_version") or ""),
            "kg_evidence_used": (evidence_used or [])[: self.max_evidence],
            "kg_semantic_warnings": (semantic_warnings or [])[: self.max_evidence],
        }

    def _load(self) -> dict[str, Any]:
        if not self.enabled:
            return {}
        signature = self._current_signature()
        if signature == self._signature:
            return self._data
        self._signature = signature
        self._data = {
            "business_terms": self._read_list("business_terms.json"),
            "field_semantics": self._read_list("field_semantics.json"),
            "business_paths": self._read_list("business_paths.json"),
            "api_candidates": self._read_list("api_candidates.json"),
            "candidate_kg_facts": self._read_list("candidate_kg_facts.json"),
            "build_summary": self._read_dict("build_summary.json"),
        }
        if self._data.get("candidate_kg_facts"):
            for fact in self._data["candidate_kg_facts"]:
                if isinstance(fact, dict):
                    fact["confirmed"] = False
                    fact["blocking"] = False
        return self._data

    def _current_signature(self) -> tuple[tuple[str, int, int], ...]:
        paths = [
            self.kg_root / name
            for name in (
                "business_terms.json",
                "field_semantics.json",
                "business_paths.json",
                "api_candidates.json",
                "candidate_kg_facts.json",
                "build_summary.json",
            )
        ]
        signature = []
        for path in paths:
            try:
                stat = path.stat()
            except FileNotFoundError:
                signature.append((str(path), 0, 0))
            else:
                signature.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _read_list(self, filename: str) -> list[dict[str, Any]]:
        path = self.kg_root / filename
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        return value if isinstance(value, list) else []

    def _read_dict(self, filename: str) -> dict[str, Any]:
        path = self.kg_root / filename
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _fact_score(cls, user_input: str, fact: dict[str, Any], *, fields: tuple[str, ...]) -> float:
        query = str(user_input or "")
        if not query.strip():
            return 0.0
        text_parts: list[str] = []
        for field in fields:
            value = fact.get(field)
            if isinstance(value, list):
                text_parts.extend(str(item) for item in value)
            elif isinstance(value, dict):
                text_parts.append(json.dumps(value, ensure_ascii=False))
            else:
                text_parts.append(str(value or ""))
        candidate = " ".join(text_parts)
        if not candidate.strip():
            return 0.0
        score = 0.0
        query_norm = cls._normalize(query)
        candidate_norm = cls._normalize(candidate)
        if len(query_norm) >= 6 and query_norm in candidate_norm:
            score += 8.0
        if len(candidate_norm) >= 6 and candidate_norm in query_norm:
            score += 5.0
        query_tokens = cls._tokens(query)
        candidate_tokens = cls._tokens(candidate)
        score += 2.0 * len(query_tokens & candidate_tokens)
        score += 1.5 * len(cls._cjk_terms(query) & cls._cjk_terms(candidate))
        return score

    @classmethod
    def _matched_terms(cls, user_input: str, terms: list[Any]) -> list[str]:
        raw = str(user_input or "").lower()
        normalized = cls._normalize(user_input)
        matched = []
        for term in terms:
            text = str(term or "")
            if not text:
                continue
            if any("\u4e00" <= ch <= "\u9fff" for ch in text):
                if text in raw:
                    matched.append(text)
                continue
            if cls._normalize(text) in normalized:
                matched.append(text)
        return matched[:8]

    @staticmethod
    def _compact_fact(fact: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "term",
            "service_name",
            "entity_set",
            "field_name",
            "semantic_role",
            "supports_meaning",
            "does_not_support",
            "intent",
            "service_names",
            "steps",
            "source",
            "confidence",
            "confirmed",
            "evidence_text",
            "repair_hints",
        }
        compact = {key: value for key, value in fact.items() if key in allowed and value not in ("", [], {})}
        if "evidence_text" in compact:
            compact["evidence_text"] = KnowledgeGraphProvider._compact_text(str(compact["evidence_text"]), 320)
        return compact

    @staticmethod
    def _plan_field_names(plan: Any) -> set[str]:
        fields: set[str] = set()
        for value in getattr(plan, "select_fields", []) or []:
            fields.add(str(value))
        for value in getattr(plan, "response_summary_fields", []) or []:
            fields.add(str(value))
        for condition in getattr(plan, "filters", []) or []:
            fields.add(str(getattr(condition, "field", "")))
        for step in getattr(plan, "steps", []) or []:
            for value in getattr(step, "select_fields", []) or []:
                fields.add(str(value))
            for value in getattr(step, "response_summary_fields", []) or []:
                fields.add(str(value))
            for condition in getattr(step, "filters", []) or []:
                fields.add(str(getattr(condition, "field", "")))
        return {field for field in fields if field}

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    @staticmethod
    def _tokens(value: str) -> set[str]:
        split_camel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
        return {token.lower() for token in re.findall(r"[A-Za-z0-9]+", split_camel) if len(token) >= 3}

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
                    terms.add(chunk[index : index + size])
        return terms

    @staticmethod
    def _compact_text(value: str, limit: int) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else f"{text[: limit - 3]}..."
