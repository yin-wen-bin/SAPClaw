from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(slots=True)
class ApiSkillRoutingHints:
    route_when: list[str]
    route_not_when: list[str]
    business_terms: list[str]
    anchor_terms: list[str]
    companion_apis: list[str]
    anti_patterns: list[str]

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "route_when": list(self.route_when),
            "route_not_when": list(self.route_not_when),
            "business_terms": list(self.business_terms),
            "anchor_terms": list(self.anchor_terms),
            "companion_apis": list(self.companion_apis),
            "anti_patterns": list(self.anti_patterns),
        }


@dataclass(slots=True)
class ApiSkill:
    service_name: str
    path: str
    content: str
    summary: str
    routing_hints: ApiSkillRoutingHints
    runtime_rules: dict[str, Any]

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "path": self.path,
            "summary": self.summary,
            "routing_hints": self.routing_hints.as_dict(),
            "runtime_rules": self.runtime_rules,
            "content": self.content,
        }


class ApiSkillProvider:
    """Loads API-specific planning skills.

    Skills are semantic playbooks for Codex. They do not replace the local
    index, and schema validation remains authoritative for fields and entities.
    """

    def __init__(self, skill_root: str | Path = "data/api_skills", max_summary_chars: int = 4000) -> None:
        self.skill_root = Path(skill_root)
        self.max_summary_chars = max_summary_chars
        self._cache_lock = RLock()
        self._skill_cache: dict[str, tuple[tuple[int, ...] | None, ApiSkill | None]] = {}

    def load(self, service_name: str) -> ApiSkill | None:
        service = str(service_name or "").strip()
        if not service:
            return None
        path = self.skill_root / service / "skill.md"
        rules_path = self.skill_root / service / "runtime_rules.json"
        with self._cache_lock:
            signature = self._skill_signature(path, rules_path)
            cached = self._skill_cache.get(service)
            if cached is not None and cached[0] == signature:
                return cached[1]
            if signature is None:
                self._skill_cache[service] = (signature, None)
                return None
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                self._skill_cache[service] = (signature, None)
                return None
            skill = ApiSkill(
                service_name=service,
                path=str(path),
                content=content,
                summary=self._summarize(content),
                routing_hints=self._extract_routing_hints(service, content),
                runtime_rules=self._load_runtime_rules(rules_path),
            )
            self._skill_cache[service] = (signature, skill)
            return skill

    def enrich_catalog(self, api_catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for entry in api_catalog:
            service_name = str(entry.get("service_name") or "")
            skill = self.load(service_name)
            if skill is None:
                enriched.append(dict(entry))
                continue
            enriched.append(
                {
                    **entry,
                    "api_skill_summary": skill.summary,
                    "api_skill_routing_hints": skill.routing_hints.as_dict(),
                }
            )
        return enriched

    def recommend_services(
        self,
        user_input: str,
        service_names: list[str] | set[str] | tuple[str, ...],
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return compact, advisory candidate evidence from authored API Skills.

        This is retrieval only. It never selects a service, modifies a plan, or
        overrides catalog/schema availability. Matching the complete Skill
        patterns is important because the short catalog summary can omit a
        precise business phrase found later in a skill's planning patterns.
        """

        query = str(user_input or "").strip()
        if not query:
            return []

        ranked: list[tuple[float, str, dict[str, Any]]] = []
        for service_name in dict.fromkeys(str(name or "").strip() for name in service_names):
            if not service_name:
                continue
            skill = self.load(service_name)
            if skill is None:
                continue
            lines = [
                *skill.routing_hints.route_when,
                *skill.routing_hints.business_terms,
                *skill.routing_hints.anchor_terms,
            ]
            best_score = 0.0
            best_line = ""
            matched_terms: list[str] = []
            for line in lines:
                score, matches = self._skill_match_score(query, line)
                if score > best_score:
                    best_score = score
                    best_line = line
                    matched_terms = matches
            if best_score <= 0:
                continue
            ranked.append(
                (
                    best_score,
                    service_name,
                    {
                        "service_name": service_name,
                        "confidence": round(min(1.0, 0.55 + best_score / 20.0), 3),
                        "matched_terms": matched_terms[:8],
                        "reason": self._truncate(best_line, 280),
                        "source": skill.path,
                        "confirmed": True,
                        "evidence_text": self._truncate(best_line, 360),
                    },
                )
            )
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item for _, _, item in ranked[: max(1, int(limit or 1))]]

    def _summarize(self, content: str) -> str:
        sections_by_heading = self._extract_sections_by_heading(
            content,
            wanted={
                "purpose",
                "when to use",
                "business semantics",
                "common planning patterns",
                "pitfalls",
            },
        )
        sections = [
            sections_by_heading[heading]
            for heading in (
                "common planning patterns",
                "business semantics",
                "pitfalls",
                "purpose",
                "when to use",
            )
            if heading in sections_by_heading
        ]
        summary = "\n\n".join(section for section in sections if section).strip()
        if not summary:
            summary = content
        return self._truncate(summary, self.max_summary_chars)

    @staticmethod
    def _extract_sections(content: str, wanted: set[str]) -> list[str]:
        return list(ApiSkillProvider._extract_sections_by_heading(content, wanted).values())

    def _extract_routing_hints(self, service_name: str, content: str) -> ApiSkillRoutingHints:
        sections = self._extract_sections_by_heading(
            content,
            wanted={
                "when to use",
                "when not to use",
                "business semantics",
                "common planning patterns",
                "pitfalls",
            },
        )
        route_when = self._extract_hint_lines(sections.get("when to use", ""))
        route_not_when = self._extract_hint_lines(sections.get("when not to use", ""))
        business_terms = self._extract_hint_lines(sections.get("business semantics", ""))
        anchor_terms = self._extract_hint_lines(sections.get("common planning patterns", ""))
        pitfalls = self._extract_hint_lines(sections.get("pitfalls", ""))
        anti_patterns = [
            line
            for line in [*route_not_when, *pitfalls]
            if self._is_negative_route_line(line)
        ]
        companion_apis = self._extract_companion_apis(
            service_name,
            [*route_when, *route_not_when, *business_terms, *anchor_terms, *pitfalls],
        )
        return ApiSkillRoutingHints(
            route_when=route_when,
            route_not_when=route_not_when + [line for line in pitfalls if line not in route_not_when],
            business_terms=business_terms,
            anchor_terms=anchor_terms,
            companion_apis=companion_apis,
            anti_patterns=anti_patterns,
        )

    @staticmethod
    def _extract_sections_by_heading(content: str, wanted: set[str]) -> dict[str, str]:
        lines = content.splitlines()
        sections: dict[str, str] = {}
        current_heading = ""
        current_lines: list[str] = []

        def flush() -> None:
            normalized_heading = ApiSkillProvider._normalize_heading(current_heading)
            if current_heading and normalized_heading in wanted:
                text = "\n".join(current_lines).strip()
                if text:
                    sections[normalized_heading] = f"## {current_heading}\n{text}"

        for line in lines:
            match = re.match(r"^##\s+(.+?)\s*$", line)
            if match:
                flush()
                current_heading = match.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)
        flush()
        return sections

    @staticmethod
    def _normalize_heading(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    @staticmethod
    def _extract_hint_lines(section_text: str) -> list[str]:
        lines: list[str] = []
        for raw_line in str(section_text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("###"):
                continue
            line = re.sub(r"^\s*[-*]\s*", "", line).strip()
            if not line:
                continue
            lines.append(line)
        return list(dict.fromkeys(lines))

    @staticmethod
    def _extract_companion_apis(service_name: str, lines: list[str]) -> list[str]:
        companions: list[str] = []
        for line in lines:
            for candidate in re.findall(r"\b[A-Z][A-Z0-9_]*\b", str(line or "")):
                if candidate == service_name or not candidate.startswith(("API_", "C_", "I_")):
                    continue
                if candidate not in companions:
                    companions.append(candidate)
        return companions

    @staticmethod
    def _is_negative_route_line(line: str) -> bool:
        lower = str(line or "").lower()
        return any(
            marker in lower
            for marker in (
                "do not use",
                "don't use",
                "do not route",
                "not use this api",
                "does not contain",
                "do not answer",
                "not sufficient",
                "不要",
                "不使用",
                "不能",
                "不应",
                "不包含",
            )
        )

    @classmethod
    def _skill_match_score(cls, query: str, candidate: str) -> tuple[float, list[str]]:
        query_text = str(query or "")
        candidate_text = str(candidate or "")
        if not query_text.strip() or not candidate_text.strip():
            return 0.0, []

        score = 0.0
        query_normalized = cls._normalize_search_text(query_text)
        candidate_normalized = cls._normalize_search_text(candidate_text)
        if len(query_normalized) >= 6 and query_normalized in candidate_normalized:
            score += 10.0
        if len(candidate_normalized) >= 6 and candidate_normalized in query_normalized:
            score += 7.0

        common_tokens = cls._search_tokens(query_text) & cls._search_tokens(candidate_text)
        score += 2.0 * len(common_tokens)

        common_cjk_terms = cls._cjk_terms(query_text) & cls._cjk_terms(candidate_text)
        meaningful_cjk_terms = sorted((term for term in common_cjk_terms if len(term) >= 2), key=lambda term: (-len(term), term))
        score += 1.5 * len(meaningful_cjk_terms)
        matched_terms = [*meaningful_cjk_terms, *sorted(common_tokens)]
        return score, matched_terms

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        return "".join(char for char in str(value or "").lower() if char.isalnum())

    @staticmethod
    def _search_tokens(value: str) -> set[str]:
        split_camel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(value or ""))
        return {token.lower() for token in re.findall(r"[A-Za-z0-9]+", split_camel) if len(token) >= 3}

    @staticmethod
    def _cjk_terms(value: str) -> set[str]:
        terms: set[str] = set()
        for chunk in re.findall(r"[\u4e00-\u9fff]+", str(value or "")):
            for size in (2, 3, 4, 5, 6):
                if len(chunk) < size:
                    continue
                terms.update(chunk[index : index + size] for index in range(0, len(chunk) - size + 1))
        return terms

    @staticmethod
    def _truncate(value: str, max_chars: int) -> str:
        if len(value) <= max_chars:
            return value
        return value[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _load_runtime_rules(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Runtime rules must be a JSON object: {path}")
        return payload

    def _skill_signature(self, path: Path, rules_path: Path) -> tuple[int, ...] | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        try:
            rules_stat = rules_path.stat()
            rules_signature = (rules_stat.st_mtime_ns, rules_stat.st_size)
        except FileNotFoundError:
            rules_signature = (0, 0)
        return (stat.st_mtime_ns, stat.st_size, *rules_signature, self.max_summary_chars)
