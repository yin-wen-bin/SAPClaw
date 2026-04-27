from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ApiSkill:
    service_name: str
    path: str
    content: str
    summary: str

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "service_name": self.service_name,
            "path": self.path,
            "summary": self.summary,
            "content": self.content,
        }


class ApiSkillProvider:
    """Loads API-specific LLM skills.

    Skills are semantic playbooks for the LLM. They do not replace the local
    index, and schema validation remains authoritative for fields and entities.
    """

    def __init__(self, skill_root: str | Path = "data/api_skills", max_summary_chars: int = 2200) -> None:
        self.skill_root = Path(skill_root)
        self.max_summary_chars = max_summary_chars

    def load(self, service_name: str) -> ApiSkill | None:
        service = str(service_name or "").strip()
        if not service:
            return None
        path = self.skill_root / service / "skill.md"
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        return ApiSkill(
            service_name=service,
            path=str(path),
            content=content,
            summary=self._summarize(content),
        )

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
                }
            )
        return enriched

    def _summarize(self, content: str) -> str:
        sections = self._extract_sections(
            content,
            wanted={
                "purpose",
                "when to use",
                "business semantics",
                "common planning patterns",
                "pitfalls",
            },
        )
        summary = "\n\n".join(section for section in sections if section).strip()
        if not summary:
            summary = content
        return self._truncate(summary, self.max_summary_chars)

    @staticmethod
    def _extract_sections(content: str, wanted: set[str]) -> list[str]:
        lines = content.splitlines()
        sections: list[str] = []
        current_heading = ""
        current_lines: list[str] = []

        def flush() -> None:
            if current_heading and ApiSkillProvider._normalize_heading(current_heading) in wanted:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append(f"## {current_heading}\n{text}")

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
    def _truncate(value: str, max_chars: int) -> str:
        if len(value) <= max_chars:
            return value
        return value[: max_chars - 3].rstrip() + "..."
