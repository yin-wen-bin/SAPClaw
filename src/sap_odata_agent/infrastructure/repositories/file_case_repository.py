from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sap_odata_agent.domain.models import CaseRecord


class JsonlCaseRepository:
    GENERIC_FEEDBACK_TERMS = {
        "all",
        "bp",
        "business",
        "customer",
        "partner",
        "supplier",
        "vendor",
        "业务伙伴",
        "供应商",
        "客户",
        "分别",
        "全部",
        "所有",
        "查询",
        "什么",
        "哪些",
        "多少",
        "多久",
    }

    def __init__(self, file_path: str, memory_path: str | None = None) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path = Path(memory_path) if memory_path else self.file_path.with_name("feedback_memory.jsonl")
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, record: CaseRecord) -> None:
        with self.file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, default=str) + "\n")

    def list_recent(self, limit: int = 20, conversation_id: str | None = None) -> list[dict[str, Any]]:
        entries = self._load_entries()
        if conversation_id:
            entries = [
                entry
                for entry in entries
                if ((entry.get("request") or {}).get("conversation_id") or "") == conversation_id
            ]
        entries.sort(key=self._entry_sort_key, reverse=True)
        return entries[: max(1, limit)]

    def get_by_case_id(self, case_id: str) -> dict[str, Any] | None:
        for entry in self._load_entries():
            if entry.get("case_id") == case_id:
                return entry
        return None

    def update_feedback(
        self,
        case_id: str,
        status: str,
        comment: str = "",
        expected_result: str = "",
    ) -> dict[str, Any] | None:
        entries = self._load_entries()
        updated: dict[str, Any] | None = None
        for entry in entries:
            if entry.get("case_id") != case_id:
                continue
            entry["feedback"] = {
                "status": status,
                "comment": comment,
                "expected_result": expected_result,
                "created_at": datetime.now().astimezone().isoformat(),
            }
            updated = entry
            break
        if updated is None:
            return None
        self._write_entries(entries)
        return updated

    def save_feedback_memory(self, case_id: str, memory: dict[str, Any]) -> None:
        payload = {
            "case_id": case_id,
            "created_at": datetime.now().astimezone().isoformat(),
            **memory,
        }
        with self.memory_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def search_feedback_memory(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_terms = self._tokenize(query)
        if not query_terms or not self.memory_path.exists():
            return []
        candidates: list[tuple[float, dict[str, Any]]] = []
        for entry in self._load_memory_entries():
            haystack = " ".join(
                [
                    str(entry.get("lesson") or ""),
                    str(entry.get("condition") or ""),
                    " ".join(str(item) for item in entry.get("user_phrases", []) or []),
                    " ".join(str(item) for item in entry.get("preferred_fields", []) or []),
                    " ".join(str(item) for item in entry.get("preferred_entities", []) or []),
                    " ".join(str(item) for item in entry.get("rejected_fields", []) or []),
                ]
            )
            haystack_terms = self._tokenize(haystack)
            overlap = query_terms & haystack_terms
            if not overlap:
                continue
            informative_overlap = {
                term
                for term in overlap
                if not term.isdigit() and term not in self.GENERIC_FEEDBACK_TERMS and len(term) >= 2
            }
            if not informative_overlap:
                continue
            score = self._score_terms(query_terms, haystack_terms, informative_overlap)
            candidates.append((score, entry))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in candidates[: max(1, limit)]]

    def find_latest_clarification(self, conversation_id: str) -> dict[str, Any] | None:
        if not conversation_id:
            return None
        for entry in self.list_recent(limit=20, conversation_id=conversation_id):
            if entry.get("final_status") == "clarification_requested":
                return entry
        return None

    def search_feedback(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        query_terms = self._tokenize(query)
        if not query_terms:
            return []
        candidates: list[tuple[float, dict[str, Any]]] = []
        for entry in self._load_entries():
            feedback = entry.get("feedback") or {}
            if feedback.get("status") != "incorrect":
                continue
            haystack = " ".join(
                [
                    str((entry.get("request") or {}).get("user_input") or ""),
                    str(entry.get("effective_user_input") or ""),
                    str(feedback.get("comment") or ""),
                    str(feedback.get("expected_result") or ""),
                ]
            )
            haystack_terms = self._tokenize(haystack)
            overlap = query_terms & haystack_terms
            if not overlap:
                continue
            informative_overlap = {
                term
                for term in overlap
                if not term.isdigit() and term not in self.GENERIC_FEEDBACK_TERMS and len(term) >= 3
            }
            if not informative_overlap:
                continue
            score = self._score_terms(query_terms, haystack_terms, informative_overlap)
            if score < 6.0:
                continue
            score += 0.01 * self._entry_sort_key(entry).timestamp()
            candidates.append((score, entry))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in candidates[: max(1, limit)]]

    def _load_entries(self) -> list[dict[str, Any]]:
        if not self.file_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for raw_line in self.file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
        return entries

    def _write_entries(self, entries: list[dict[str, Any]]) -> None:
        lines = [json.dumps(entry, ensure_ascii=False, default=str) for entry in entries]
        payload = "\n".join(lines)
        if payload:
            payload += "\n"
        self.file_path.write_text(payload, encoding="utf-8")

    def _load_memory_entries(self) -> list[dict[str, Any]]:
        if not self.memory_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for raw_line in self.memory_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
        return entries

    @staticmethod
    def _entry_sort_key(entry: dict[str, Any]) -> datetime:
        raw_value = entry.get("created_at")
        if isinstance(raw_value, str):
            try:
                return datetime.fromisoformat(raw_value)
            except ValueError:
                pass
        return datetime.min

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        lowered = (text or "").lower()
        english = re.findall(r"[a-z][a-z0-9_]+", lowered)
        numbers = re.findall(r"\d{2,}", lowered)
        chinese_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", lowered)
        chinese_terms: set[str] = set()
        for chunk in chinese_chunks:
            max_size = min(6, len(chunk))
            for size in range(2, max_size + 1):
                for index in range(0, len(chunk) - size + 1):
                    chinese_terms.add(chunk[index : index + size])
        return {token for token in [*english, *numbers, *chinese_terms] if token}

    def _score_terms(
        self,
        query_terms: set[str],
        haystack_terms: set[str],
        informative_overlap: set[str],
    ) -> float:
        score = 0.0
        for term in query_terms & haystack_terms:
            if term.isdigit():
                score += 0.25
            elif term in self.GENERIC_FEEDBACK_TERMS:
                score += 0.75
            else:
                score += min(len(term), 8)
        score += sum(min(len(term), 8) * 0.75 for term in informative_overlap)
        return score
