from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class LocalIndexSnapshot:
    service_name: str
    root_dir: Path
    services: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    fields: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    entity_graph: list[dict[str, Any]] = field(default_factory=list)
    lookup_paths: list[dict[str, Any]] = field(default_factory=list)
    business_terms: list[dict[str, Any]] = field(default_factory=list)
    vector_documents: list[dict[str, Any]] = field(default_factory=list)
    doc_chunks: list[dict[str, Any]] = field(default_factory=list)


class LocalIndexLoader:
    def __init__(self, index_root: str | Path = "data/index") -> None:
        self.index_root = Path(index_root)

    def load(self, service_name: str) -> LocalIndexSnapshot:
        return _load_snapshot(str(self.index_root.resolve()), service_name)


@lru_cache(maxsize=16)
def _load_snapshot(index_root: str, service_name: str) -> LocalIndexSnapshot:
    service_dir = Path(index_root) / service_name
    if not service_dir.exists():
        raise FileNotFoundError(f"Local index directory does not exist: {service_dir}")

    return LocalIndexSnapshot(
        service_name=service_name,
        root_dir=service_dir,
        services=_read_json(service_dir / "services.json"),
        entities=_read_json(service_dir / "entities.json"),
        fields=_read_json(service_dir / "fields.json"),
        relations=_read_json(service_dir / "relations.json"),
        entity_graph=_read_json(service_dir / "entity_graph.json"),
        lookup_paths=_read_json(service_dir / "lookup_paths.json"),
        business_terms=_read_json(service_dir / "business_terms.json"),
        vector_documents=_read_jsonl(service_dir / "vector_documents.jsonl"),
        doc_chunks=_read_jsonl(service_dir / "doc_chunks.jsonl"),
    )


def _read_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return [payload]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows
