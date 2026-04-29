from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ServiceMetadata:
    service_name: str
    service_version: str | None = None
    base_path: str = ""
    service_kind: str = "ODATA"
    runtime_path_template: str = "/sap/opu/odata/sap/{service_name}"
    description: str = ""
    entity_sets: list[str] = field(default_factory=list)
    allowed_methods: list[str] = field(default_factory=lambda: ["GET"])
    source: str = ""
    source_documents: list[str] = field(default_factory=list)
    runtime_available: bool = True
    odata_runtime_available: bool = True
    documentation_available: bool = False
    documentation_url: str = ""
    openapi_version: str = ""
    runtime_notes: str = ""


@dataclass(slots=True)
class EntityMetadata:
    service_name: str
    entity_set: str
    entity_type: str = ""
    key_fields: list[str] = field(default_factory=list)
    default_select_fields: list[str] = field(default_factory=list)
    supports_filter: bool = True
    supports_orderby: bool = True
    supports_top: bool = True
    navigations: list[str] = field(default_factory=list)
    description: str = ""
    supported_methods: list[str] = field(default_factory=lambda: ["GET"])
    source_documents: list[str] = field(default_factory=list)
    runtime_available: bool = True
    documentation_available: bool = False


@dataclass(slots=True)
class FieldMetadata:
    service_name: str
    entity_set: str
    field_name: str
    label: str = ""
    business_aliases: list[str] = field(default_factory=list)
    data_type: str = ""
    nullable: bool = True
    is_key: bool = False
    selectable: bool = True
    filterable: bool = True
    sortable: bool = True
    allowed_operators: list[str] = field(default_factory=lambda: ["eq"])
    description: str = ""
    source_documents: list[str] = field(default_factory=list)
    runtime_available: bool = True
    documentation_available: bool = False


@dataclass(slots=True)
class NavigationMetadata:
    service_name: str
    from_entity_set: str
    navigation_name: str
    to_entity_set: str
    cardinality: str = ""
    source_documents: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BusinessTermAlias:
    term: str
    intent_type: str
    mapped_service: str = ""
    mapped_entity_set: str = ""
    mapped_fields: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = ""


@dataclass(slots=True)
class LookupPathMetadata:
    path_id: str
    service_name: str
    anchor_object: str
    target_entity_set: str
    target_field: str
    path_kind: str = "lookup"
    return_object: str = ""
    filter_fields: list[str] = field(default_factory=list)
    result_fields: list[str] = field(default_factory=list)
    description: str = ""
    business_aliases: list[str] = field(default_factory=list)
    steps: list[dict[str, object]] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(slots=True)
class EntityGraphEdge:
    service_name: str
    from_entity_set: str
    to_entity_set: str
    edge_type: str
    from_field: str = ""
    to_field: str = ""
    via_path_id: str = ""
    description: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class VectorDocument:
    doc_id: str
    doc_type: str
    service_name: str
    content: str
    entity_set: str = ""
    field_name: str = ""
    path_id: str = ""
    keywords: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentChunk:
    chunk_id: str
    content: str
    service_name: str = ""
    entity_set: str = ""
    field_names: list[str] = field(default_factory=list)
    source_file: str = ""
    section: str = ""
    keywords: list[str] = field(default_factory=list)
    source_type: str = ""
