from __future__ import annotations

from pathlib import Path
from typing import Any

from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader


class ApiCatalogProvider:
    """Build a compact API catalog for LLM routing.

    The catalog is intentionally small: it summarizes indexed APIs without
    exposing every field. The router uses this to pick the API before any
    API-specific metadata is loaded.
    """

    def __init__(self, index_root: str | Path = "data/index", default_service_name: str = "API_BUSINESS_PARTNER") -> None:
        self.index_root = Path(index_root)
        self.default_service_name = default_service_name
        self.loader = LocalIndexLoader(index_root=index_root)

    def load(self) -> list[dict[str, Any]]:
        service_names = self._discover_service_names()
        catalog: list[dict[str, Any]] = []
        for service_name in service_names:
            try:
                snapshot = self.loader.load(service_name)
            except FileNotFoundError:
                continue
            catalog.append(self._catalog_entry(snapshot))
        return catalog

    def _discover_service_names(self) -> list[str]:
        if not self.index_root.exists():
            return [self.default_service_name]
        names = [
            path.name
            for path in self.index_root.iterdir()
            if path.is_dir() and (path / "entities.json").exists()
        ]
        if self.default_service_name not in names:
            names.insert(0, self.default_service_name)
        return list(dict.fromkeys(names))

    @staticmethod
    def _catalog_entry(snapshot) -> dict[str, Any]:
        service = snapshot.services[0] if snapshot.services else {}
        top_entities = [str(entity.get("entity_set", "")) for entity in snapshot.entities[:24] if entity.get("entity_set")]
        business_terms = []
        for term in snapshot.business_terms[:80]:
            for value in (term.get("term"), term.get("label"), term.get("description")):
                text = str(value or "").strip()
                if text and text not in business_terms:
                    business_terms.append(text)
                if len(business_terms) >= 30:
                    break
            if len(business_terms) >= 30:
                break
        field_terms = []
        for field in snapshot.fields[:200]:
            for value in (field.get("label"), field.get("description"), field.get("field_name")):
                text = str(value or "").strip()
                if text and text not in field_terms:
                    field_terms.append(text)
                if len(field_terms) >= 50:
                    break
            if len(field_terms) >= 50:
                break
        return {
            "service_name": snapshot.service_name,
            "description": service.get("description", ""),
            "business_scope": business_terms[:30],
            "typical_questions": service.get("typical_questions", []),
            "top_entities": top_entities,
            "field_vocabulary_sample": field_terms[:50],
            "entity_count": len(snapshot.entities),
            "field_count": len(snapshot.fields),
        }
