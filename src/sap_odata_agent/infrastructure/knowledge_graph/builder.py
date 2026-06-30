from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_local_knowledge_graph(
    *,
    index_root: str | Path = "data/index",
    api_skill_root: str | Path = "data/api_skills",
    output_root: str | Path = "data/knowledge_graph",
    feedback_memory_path: str | Path = "data/cases/feedback_memory.jsonl",
    include_feedback: bool = False,
) -> dict[str, Any]:
    index_root = Path(index_root)
    api_skill_root = Path(api_skill_root)
    output_root = Path(output_root)
    feedback_memory_path = Path(feedback_memory_path)

    services = _load_index_services(index_root)
    fields = _load_index_fields(index_root)
    relations = _load_index_relations(index_root)
    skills = _load_api_skills(api_skill_root)

    business_terms = _build_business_terms(fields, skills)
    field_semantics = _build_field_semantics(fields, skills)
    business_paths = _build_business_paths(relations, skills)
    api_candidates = _build_api_candidates(services, skills)
    candidate_facts = _build_candidate_facts(feedback_memory_path) if include_feedback else []

    builder_options = {
        "business_term_limit_per_service": 250,
        "include_feedback": include_feedback,
    }
    summary = {
        "build_version": _build_version(services, fields, relations, skills, builder_options),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "index_root": str(index_root),
            "api_skill_root": str(api_skill_root),
            "feedback_memory_path": str(feedback_memory_path) if include_feedback else "",
            "feedback_included": include_feedback,
        },
        "builder_options": builder_options,
        "counts": {
            "business_terms": len(business_terms),
            "field_semantics": len(field_semantics),
            "business_paths": len(business_paths),
            "api_candidates": len(api_candidates),
            "candidate_kg_facts": len(candidate_facts),
        },
    }

    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(output_root / "business_terms.json", business_terms)
    _write_json(output_root / "field_semantics.json", field_semantics)
    _write_json(output_root / "business_paths.json", business_paths)
    _write_json(output_root / "api_candidates.json", api_candidates)
    _write_json(output_root / "candidate_kg_facts.json", candidate_facts)
    _write_json(output_root / "build_summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build SAPClaw local knowledge graph JSON files.")
    parser.add_argument("--index-root", default="data/index")
    parser.add_argument("--api-skill-root", default="data/api_skills")
    parser.add_argument("--output-root", default="data/knowledge_graph")
    parser.add_argument("--feedback-memory-path", default="data/cases/feedback_memory.jsonl")
    parser.add_argument(
        "--include-feedback",
        action="store_true",
        help="Include local feedback memory as candidate-only facts. Disabled by default to avoid exporting local cases.",
    )
    args = parser.parse_args(argv)
    summary = build_local_knowledge_graph(
        index_root=args.index_root,
        api_skill_root=args.api_skill_root,
        output_root=args.output_root,
        feedback_memory_path=args.feedback_memory_path,
        include_feedback=args.include_feedback,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _load_index_services(index_root: Path) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    for service_dir in _service_dirs(index_root):
        for item in _read_json_list(service_dir / "services.json"):
            if isinstance(item, dict):
                services.append(item)
    return services


def _load_index_fields(index_root: Path) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for service_dir in _service_dirs(index_root):
        for item in _read_json_list(service_dir / "fields.json"):
            if isinstance(item, dict):
                fields.append(item)
    return fields


def _load_index_relations(index_root: Path) -> list[dict[str, Any]]:
    relations: list[dict[str, Any]] = []
    for service_dir in _service_dirs(index_root):
        for item in _read_json_list(service_dir / "relations.json"):
            if isinstance(item, dict):
                relations.append(item)
    return relations


def _load_api_skills(api_skill_root: Path) -> dict[str, dict[str, Any]]:
    skills: dict[str, dict[str, Any]] = {}
    if not api_skill_root.exists():
        return skills
    for service_dir in sorted(path for path in api_skill_root.iterdir() if path.is_dir()):
        path = service_dir / "skill.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        skills[service_dir.name] = {
            "service_name": service_dir.name,
            "path": str(path),
            "text": text,
            "sections": _markdown_sections(text),
        }
    return skills


def _build_business_terms(fields: list[dict[str, Any]], skills: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for field in fields:
        service_name = str(field.get("service_name") or "")
        entity_set = str(field.get("entity_set") or "")
        field_name = str(field.get("field_name") or "")
        if not service_name or not entity_set or not field_name:
            continue
        raw_terms = [
            field_name,
            field.get("label") or "",
            *(field.get("business_aliases") or []),
        ]
        for term in raw_terms:
            text = _clean_text(str(term or ""))
            if not text or len(text) > 120:
                continue
            key = (service_name, entity_set, field_name, text.lower())
            if key in seen:
                continue
            seen.add(key)
            terms.append(
                {
                    "term": text,
                    "service_name": service_name,
                    "entity_set": entity_set,
                    "field_name": field_name,
                    "semantic_role": "field_alias",
                    "source": "data/index/fields.json",
                    "confidence": 0.82 if text == field_name else 0.72,
                    "evidence_text": text,
                    "confirmed": True,
                }
            )

    for service_name, skill in skills.items():
        for line in _skill_signal_lines(skill):
            for phrase in _extract_business_phrases(line):
                key = (service_name, "", "", phrase.lower())
                if key in seen:
                    continue
                seen.add(key)
                terms.append(
                    {
                        "term": phrase,
                        "service_name": service_name,
                        "semantic_role": "api_skill_business_term",
                        "source": skill["path"],
                        "confidence": 0.76,
                        "evidence_text": line,
                        "confirmed": True,
                    }
                )
    return _limit_facts_by_service(terms, limit_per_service=250)


def _build_field_semantics(
    fields: list[dict[str, Any]],
    skills: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_service_field = {
        (str(field.get("service_name") or ""), str(field.get("field_name") or "")): field
        for field in fields
        if field.get("service_name") and field.get("field_name")
    }
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for service_name, skill in skills.items():
        for line in _skill_signal_lines(skill):
            field_refs = _extract_field_refs(line)
            if not field_refs:
                continue
            negative = _is_negative_semantic_line(line)
            for entity_set, field_name in field_refs:
                indexed = by_service_field.get((service_name, field_name), {})
                entity = entity_set or str(indexed.get("entity_set") or "")
                if not entity or not field_name:
                    continue
                key = (service_name, entity, field_name, line)
                if key in seen:
                    continue
                seen.add(key)
                fact: dict[str, Any] = {
                    "service_name": service_name,
                    "entity_set": entity,
                    "field_name": field_name,
                    "source": skill["path"],
                    "confidence": 0.9 if negative else 0.82,
                    "evidence_text": line,
                    "confirmed": True,
                    "blocking": negative,
                }
                if negative:
                    fact["does_not_support"] = [_line_meaning(line)]
                    fact["repair_hints"] = _repair_hints_from_line(line, field_name)
                else:
                    fact["supports_meaning"] = [_line_meaning(line)]
                facts.append(fact)
    return facts


def _build_business_paths(relations: list[dict[str, Any]], skills: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for service_name, skill in skills.items():
        for heading, body in skill.get("sections", {}).items():
            normalized_heading = heading.lower()
            if "pattern" not in normalized_heading and "planning" not in normalized_heading:
                continue
            for title, lines in _subsections(body):
                if not lines:
                    continue
                steps = [_clean_text(line.lstrip("-*0123456789. ").strip()) for line in lines if _clean_text(line)]
                if not steps:
                    continue
                facts.append(
                    {
                        "intent": _clean_text(title) or "Common Planning Pattern",
                        "service_names": [service_name],
                        "steps": steps[:8],
                        "source": skill["path"],
                        "confidence": 0.86,
                        "evidence_text": " ".join(steps[:4]),
                        "confirmed": True,
                    }
                )

    for relation in relations:
        service_name = str(relation.get("service_name") or "")
        source = str(relation.get("from_entity_set") or "")
        target = str(relation.get("to_entity_set") or "")
        navigation = str(relation.get("navigation_name") or "")
        if not service_name or not source or not target:
            continue
        facts.append(
            {
                "intent": f"{source} to {target}",
                "service_names": [service_name],
                "steps": [f"{source}.{navigation} -> {target}" if navigation else f"{source} -> {target}"],
                "source": "data/index/relations.json",
                "confidence": 0.72,
                "evidence_text": navigation or f"{source} -> {target}",
                "confirmed": True,
            }
        )
    return facts


def _build_api_candidates(
    services: list[dict[str, Any]],
    skills: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for service in services:
        service_name = str(service.get("service_name") or "")
        if not service_name or service_name in seen:
            continue
        seen.add(service_name)
        description = _clean_text(str(service.get("description") or ""))
        entity_sets = [str(item) for item in service.get("entity_sets") or [] if str(item)]
        skill = skills.get(service_name, {})
        skill_lines = _skill_signal_lines(skill) if skill else []
        terms = _service_terms(service_name, description, entity_sets, skill_lines)
        candidates.append(
            {
                "service_name": service_name,
                "terms": terms[:80],
                "business_objects": entity_sets[:24],
                "source": "data/index/services.json"
                + (f"; {skill.get('path')}" if skill else ""),
                "confidence": 0.86 if skill else 0.74,
                "evidence_text": " ".join([description, *skill_lines[:8]])[:2000],
                "confirmed": True,
            }
        )
    return candidates


def _build_candidate_facts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    facts: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            memory = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(memory, dict):
            continue
        evidence = _clean_text(
            " ".join(
                str(value)
                for value in [
                    memory.get("lesson"),
                    memory.get("condition"),
                    *(memory.get("user_phrases") or []),
                    *(memory.get("preferred_entities") or []),
                    *(memory.get("preferred_fields") or []),
                ]
                if value
            )
        )
        if not evidence:
            continue
        facts.append(
            {
                "source": f"{path}:{line_number}",
                "confidence": 0.45,
                "evidence_text": evidence[:600],
                "confirmed": False,
                "blocking": False,
            }
        )
    return facts


def _service_dirs(index_root: Path) -> list[Path]:
    if not index_root.exists():
        return []
    return sorted(path for path in index_root.iterdir() if path.is_dir() and path.name != "raw")


def _read_json_list(path: Path) -> list[Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return value if isinstance(value, list) else []


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _markdown_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            current = heading.group(2).strip()
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return sections


def _skill_signal_lines(skill: dict[str, Any]) -> list[str]:
    text = str(skill.get("text") or "")
    lines = []
    for raw_line in text.splitlines():
        line = _clean_text(raw_line.lstrip("-* ").strip())
        if not line or line.startswith("#"):
            continue
        if len(line) < 8:
            continue
        if any(
            marker in line.lower()
            for marker in (
                "use ",
                "prefer",
                "do not",
                "not sufficient",
                "not enough",
                "field",
                "entity",
                "filter",
                "query",
                "must",
                "should",
                "采购",
                "销售",
                "库存",
                "生产",
                "财务",
                "发票",
                "收货",
                "发货",
                "科目",
                "余额",
            )
        ):
            lines.append(line)
    return lines[:500]


def _extract_business_phrases(line: str) -> list[str]:
    phrases: list[str] = []
    for text in re.findall(r"`([^`]+)`", line):
        if "." not in text and 2 <= len(text) <= 80:
            phrases.append(text)
    for chunk in re.findall(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9 /_-]{1,60}", line):
        cleaned = _clean_text(chunk.strip(" .,:;()[]"))
        if 2 <= len(cleaned) <= 60:
            phrases.append(cleaned)
    return list(dict.fromkeys(phrases))[:12]


def _extract_field_refs(line: str) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for text in re.findall(r"`([^`]+)`", line):
        if "." in text:
            left, right = text.rsplit(".", 1)
            refs.append((left.strip(), right.strip()))
        elif re.match(r"^[A-Za-z][A-Za-z0-9_]{2,}$", text):
            refs.append(("", text.strip()))
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9_]{2,})\.([A-Z][A-Za-z0-9_]{2,})\b", line):
        refs.append((match.group(1), match.group(2)))
    return list(dict.fromkeys(refs))


def _is_negative_semantic_line(line: str) -> bool:
    lower = line.lower()
    return any(
        marker in lower
        for marker in (
            "do not",
            "does not",
            "not sufficient",
            "not enough",
            "cannot",
            "wrong",
            "avoid",
            "不要",
            "不能",
            "不应",
            "不足以",
            "不代表",
            "不等于",
            "不是",
        )
    )


def _line_meaning(line: str) -> str:
    return _clean_text(re.sub(r"`", "", line))[:360]


def _repair_hints_from_line(line: str, rejected_field: str) -> dict[str, Any]:
    preferred_fields = []
    for _, field_name in _extract_field_refs(line):
        if field_name != rejected_field and field_name not in preferred_fields:
            preferred_fields.append(field_name)
    hints: dict[str, Any] = {
        "reason": _line_meaning(line),
        "rejected_fields": [rejected_field],
    }
    if preferred_fields:
        hints["preferred_select_fields"] = preferred_fields[:8]
    return hints


def _subsections(lines: list[str]) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current = ""
    buffer: list[str] = []
    for line in lines:
        heading = re.match(r"^#{3,5}\s+(.+)$", line.strip())
        if heading:
            if current or buffer:
                sections.append((current, buffer))
            current = heading.group(1).strip()
            buffer = []
            continue
        if line.strip():
            buffer.append(line.strip())
    if current or buffer:
        sections.append((current, buffer))
    return sections


def _service_terms(service_name: str, description: str, entity_sets: list[str], skill_lines: list[str]) -> list[str]:
    terms = [service_name, description, *entity_sets]
    for token in re.split(r"[_\W]+", service_name):
        if len(token) >= 3:
            terms.append(token)
    for line in skill_lines[:80]:
        terms.extend(_extract_business_phrases(line))
    return [_clean_text(item) for item in dict.fromkeys(terms) if _clean_text(item)]


def _limit_facts_by_service(facts: list[dict[str, Any]], *, limit_per_service: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    limited: list[dict[str, Any]] = []
    for fact in facts:
        service_name = str(fact.get("service_name") or "")
        count = counts.get(service_name, 0)
        if count >= limit_per_service:
            continue
        counts[service_name] = count + 1
        limited.append(fact)
    return limited


def _build_version(*values: Any) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    return digest.hexdigest()[:16]


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split())
