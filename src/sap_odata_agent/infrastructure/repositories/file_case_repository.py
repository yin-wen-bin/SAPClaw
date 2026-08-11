from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

class JsonlCaseRepository:
    _MAX_ENTRY_CACHE_BYTES = 50 * 1024 * 1024

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

    def __init__(
        self,
        file_path: str,
        memory_path: str | None = None,
        feedback_path: str | None = None,
    ) -> None:
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path = Path(memory_path) if memory_path else self.file_path.with_name("feedback_memory.jsonl")
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.feedback_path = Path(feedback_path) if feedback_path else self.file_path.with_name("feedback_events.jsonl")
        self.feedback_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_lock = RLock()
        self._entries_cache: list[dict[str, Any]] | None = None
        self._entries_signature: tuple[int, int] | None = None
        self._memory_cache: list[dict[str, Any]] | None = None
        self._memory_signature: tuple[int, int] | None = None
        self._feedback_cache: list[dict[str, Any]] | None = None
        self._feedback_signature: tuple[int, int] | None = None

    def save_entry(self, entry: dict[str, Any]) -> None:
        """Append a structured SAPClaw Runtime case record."""
        payload = self._normalize_json(entry)
        with self._cache_lock:
            before_signature = self._file_signature(self.file_path)
            with self.file_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            after_signature = self._file_signature(self.file_path)
            if self._entries_cache is not None and self._entries_signature == before_signature:
                self._entries_cache.append(payload)
                self._entries_signature = after_signature
            else:
                self._entries_cache = None
                self._entries_signature = None

    def list_recent(self, limit: int = 20, conversation_id: str | None = None) -> list[dict[str, Any]]:
        feedback_by_case_id = self._feedback_by_case_id()
        max_items = max(1, limit)
        entries: list[dict[str, Any]] = []
        for entry in self._iter_entries():
            if conversation_id and ((entry.get("request") or {}).get("conversation_id") or "") != conversation_id:
                continue
            entries.append(self._entry_with_feedback(entry, feedback_by_case_id))
            if len(entries) > max_items * 4:
                entries.sort(key=self._entry_sort_key, reverse=True)
                del entries[max_items:]
        entries.sort(key=self._entry_sort_key, reverse=True)
        return entries[:max_items]

    def get_by_case_id(self, case_id: str) -> dict[str, Any] | None:
        feedback_by_case_id = self._feedback_by_case_id()
        for entry in self._iter_entries():
            if entry.get("case_id") == case_id:
                return self._entry_with_feedback(entry, feedback_by_case_id)
        return None

    def update_feedback(
        self,
        case_id: str,
        status: str,
        comment: str = "",
        expected_result: str = "",
    ) -> dict[str, Any] | None:
        feedback = {
            "status": status,
            "comment": comment,
            "expected_result": expected_result,
            "created_at": datetime.now().astimezone().isoformat(),
        }
        with self._cache_lock:
            entry: dict[str, Any] | None = None
            cache_is_current = (
                self._entries_cache is not None
                and self._entries_signature == self._file_signature(self.file_path)
            )
            if cache_is_current:
                entry = next((item for item in self._entries_cache or [] if item.get("case_id") == case_id), None)
                if entry is None:
                    return None
            elif status != "correct":
                entry = next((item for item in self._iter_entries() if item.get("case_id") == case_id), None)
                if entry is None:
                    return None

            self._append_feedback_event(case_id, feedback)
            if entry is None:
                return {"case_id": case_id, "feedback": feedback}
            return self._entry_with_feedback(entry, {case_id: feedback})

    def save_feedback_memory(self, case_id: str, memory: dict[str, Any]) -> None:
        payload = {
            "case_id": case_id,
            "created_at": datetime.now().astimezone().isoformat(),
            **memory,
        }
        payload = self._normalize_json(payload)
        with self._cache_lock:
            before_signature = self._file_signature(self.memory_path)
            with self.memory_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            after_signature = self._file_signature(self.memory_path)
            if self._memory_cache is not None and self._memory_signature == before_signature:
                self._memory_cache.append(payload)
                self._memory_signature = after_signature
            else:
                self._memory_cache = None
                self._memory_signature = None

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
        feedback_by_case_id = self._feedback_by_case_id()
        for raw_entry in self._iter_entries():
            entry = self._entry_with_feedback(raw_entry, feedback_by_case_id)
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
        with self._cache_lock:
            signature = self._file_signature(self.file_path)
            if self._entries_cache is not None and self._entries_signature == signature:
                return self._entries_cache
            if signature == (0, 0):
                self._entries_cache = []
                self._entries_signature = signature
                return self._entries_cache
            entries = list(self._iter_jsonl_file(self.file_path))
            if signature[1] <= self._MAX_ENTRY_CACHE_BYTES:
                self._entries_cache = entries
                self._entries_signature = signature
                return self._entries_cache
            self._entries_cache = None
            self._entries_signature = None
            return entries

    def _iter_entries(self):
        with self._cache_lock:
            signature = self._file_signature(self.file_path)
            if self._entries_cache is not None and self._entries_signature == signature:
                yield from self._entries_cache
                return
        yield from self._iter_jsonl_file(self.file_path)

    def _entries_with_feedback(self) -> list[dict[str, Any]]:
        feedback_by_case_id = self._feedback_by_case_id()
        return [self._entry_with_feedback(entry, feedback_by_case_id) for entry in self._load_entries()]

    @staticmethod
    def _entry_with_feedback(
        entry: dict[str, Any],
        feedback_by_case_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        merged = dict(entry)
        case_id = entry.get("case_id")
        if isinstance(case_id, str) and case_id in feedback_by_case_id:
            merged["feedback"] = feedback_by_case_id[case_id]
        return merged

    def _feedback_by_case_id(self) -> dict[str, dict[str, Any]]:
        feedback_by_case_id: dict[str, dict[str, Any]] = {}
        for event in self._load_feedback_entries():
            case_id = event.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                continue
            feedback = self._feedback_from_event(event)
            if feedback:
                feedback_by_case_id[case_id] = feedback
        return feedback_by_case_id

    @staticmethod
    def _feedback_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
        nested_feedback = event.get("feedback")
        if isinstance(nested_feedback, dict):
            return dict(nested_feedback)
        status = event.get("status")
        if not isinstance(status, str) or not status:
            return None
        return {
            "status": status,
            "comment": str(event.get("comment") or ""),
            "expected_result": str(event.get("expected_result") or ""),
            "created_at": str(event.get("created_at") or ""),
        }

    def _append_feedback_event(self, case_id: str, feedback: dict[str, Any]) -> None:
        event = self._normalize_json({"case_id": case_id, **feedback})
        before_signature = self._file_signature(self.feedback_path)
        with self.feedback_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        after_signature = self._file_signature(self.feedback_path)
        if self._feedback_cache is not None and self._feedback_signature == before_signature:
            self._feedback_cache.append(event)
            self._feedback_signature = after_signature
        else:
            self._feedback_cache = None
            self._feedback_signature = None

    def _write_entries(self, entries: list[dict[str, Any]]) -> None:
        with self._cache_lock:
            normalized_entries = [self._normalize_json(entry) for entry in entries]
            lines = [json.dumps(entry, ensure_ascii=False, default=str) for entry in normalized_entries]
            payload = "\n".join(lines)
            if payload:
                payload += "\n"
            self.file_path.write_text(payload, encoding="utf-8")
            self._entries_cache = normalized_entries
            self._entries_signature = self._file_signature(self.file_path)

    def _load_memory_entries(self) -> list[dict[str, Any]]:
        with self._cache_lock:
            signature = self._file_signature(self.memory_path)
            if self._memory_cache is not None and self._memory_signature == signature:
                return self._memory_cache
            if signature == (0, 0):
                self._memory_cache = []
                self._memory_signature = signature
                return self._memory_cache
            entries = list(self._iter_jsonl_file(self.memory_path))
            self._memory_cache = entries
            self._memory_signature = signature
            return self._memory_cache

    def _load_feedback_entries(self) -> list[dict[str, Any]]:
        with self._cache_lock:
            signature = self._file_signature(self.feedback_path)
            if self._feedback_cache is not None and self._feedback_signature == signature:
                return self._feedback_cache
            if signature == (0, 0):
                self._feedback_cache = []
                self._feedback_signature = signature
                return self._feedback_cache
            entries = list(self._iter_jsonl_file(self.feedback_path))
            self._feedback_cache = entries
            self._feedback_signature = signature
            return self._feedback_cache

    @staticmethod
    def _iter_jsonl_file(path: Path):
        try:
            handle = path.open("r", encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            return
        with handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    yield parsed

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return (0, 0)
        return (stat.st_mtime_ns, stat.st_size)

    @staticmethod
    def _normalize_json(payload: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(payload, ensure_ascii=False, default=str))

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
