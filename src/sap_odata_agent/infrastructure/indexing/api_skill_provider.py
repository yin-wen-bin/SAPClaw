from __future__ import annotations

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

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "path": self.path,
            "summary": self.summary,
            "routing_hints": self.routing_hints.as_dict(),
            "content": self.content,
        }


class ApiSkillProvider:
    """Loads API-specific LLM skills.

    Skills are semantic playbooks for the LLM. They do not replace the local
    index, and schema validation remains authoritative for fields and entities.
    """

    def __init__(self, skill_root: str | Path = "data/api_skills", max_summary_chars: int = 4000) -> None:
        self.skill_root = Path(skill_root)
        self.max_summary_chars = max_summary_chars
        self._cache_lock = RLock()
        self._skill_cache: dict[str, tuple[tuple[int, int, int] | None, ApiSkill | None]] = {}

    def load(self, service_name: str) -> ApiSkill | None:
        service = str(service_name or "").strip()
        if not service:
            return None
        path = self.skill_root / service / "skill.md"
        with self._cache_lock:
            signature = self._skill_signature(path)
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

    @staticmethod
    def _truncate(value: str, max_chars: int) -> str:
        if len(value) <= max_chars:
            return value
        return value[: max_chars - 3].rstrip() + "..."

    def _skill_signature(self, path: Path) -> tuple[int, int, int] | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size, self.max_summary_chars)
