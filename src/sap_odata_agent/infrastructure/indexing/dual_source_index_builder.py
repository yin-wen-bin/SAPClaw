from __future__ import annotations

import json
import ssl
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sap_odata_agent.domain.index_models import (
    BusinessTermAlias,
    DocumentChunk,
    EntityMetadata,
    EntityGraphEdge,
    FieldMetadata,
    LookupPathMetadata,
    NavigationMetadata,
    ServiceMetadata,
    VectorDocument,
)


EDM_NS = "http://schemas.microsoft.com/ado/2008/09/edm"
SAP_NS = "http://www.sap.com/Protocols/SAPData"
NS = {"edm": EDM_NS}

@dataclass(slots=True)
class SapConnectionConfig:
    base_url: str
    username: str
    password: str
    client: str = ""
    verify_ssl: bool = True
    auth_type: str = "basic"
    timeout_seconds: int = 30


@dataclass(slots=True)
class IndexBundle:
    services: list[ServiceMetadata] = field(default_factory=list)
    entities: list[EntityMetadata] = field(default_factory=list)
    fields: list[FieldMetadata] = field(default_factory=list)
    relations: list[NavigationMetadata] = field(default_factory=list)
    entity_graph: list[EntityGraphEdge] = field(default_factory=list)
    lookup_paths: list[LookupPathMetadata] = field(default_factory=list)
    business_terms: list[BusinessTermAlias] = field(default_factory=list)
    vector_documents: list[VectorDocument] = field(default_factory=list)
    doc_chunks: list[DocumentChunk] = field(default_factory=list)
    raw_metadata_xml: str = ""
    raw_openapi_spec: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedSapMetadata:
    services: list[ServiceMetadata]
    entities: list[EntityMetadata]
    fields: list[FieldMetadata]
    relations: list[NavigationMetadata]
    doc_chunks: list[DocumentChunk]
    raw_xml: str


@dataclass(slots=True)
class ParsedOpenApiSpec:
    service_name: str
    service_description: str
    service_title: str
    openapi_version: str
    external_docs_url: str
    entity_descriptions: dict[str, str]
    entity_methods: dict[str, list[str]]
    field_descriptions: dict[str, dict[str, str]]
    doc_chunks: list[DocumentChunk]
    business_terms: list[BusinessTermAlias]
    raw_spec: dict[str, Any]


def load_env_file(env_path: str | Path) -> dict[str, str]:
    env_vars: dict[str, str] = {}
    for raw_line in Path(env_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_vars[key.strip()] = value.strip()
    return env_vars


def build_connection_config(env_path: str | Path) -> SapConnectionConfig:
    env_vars = load_env_file(env_path)
    timeout_ms = int(env_vars.get("SAP_ODATA_TIMEOUT_MS", "30000"))
    return SapConnectionConfig(
        base_url=env_vars["SAP_BASE_URL"].rstrip("/"),
        username=env_vars["SAP_USERNAME"],
        password=env_vars["SAP_PASSWORD"],
        client=env_vars.get("SAP_CLIENT", ""),
        verify_ssl=env_vars.get("SAP_VERIFY_SSL", "true").lower() == "true",
        auth_type=env_vars.get("SAP_AUTH_TYPE", "basic"),
        timeout_seconds=max(1, timeout_ms // 1000),
    )


class SapMetadataFetcher:
    def fetch(self, config: SapConnectionConfig, service_name: str) -> tuple[str, str]:
        if config.auth_type.lower() != "basic":
            raise ValueError(f"Unsupported SAP auth type for index builder: {config.auth_type}")

        query = f"?sap-client={config.client}" if config.client else ""
        metadata_url = f"{config.base_url}/sap/opu/odata/sap/{service_name}/$metadata{query}"
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, config.base_url, config.username, config.password)
        auth_handler = urllib.request.HTTPBasicAuthHandler(password_mgr)

        https_handler = None
        if metadata_url.lower().startswith("https://") and not config.verify_ssl:
            https_handler = urllib.request.HTTPSHandler(context=ssl._create_unverified_context())

        handlers = [auth_handler]
        if https_handler is not None:
            handlers.append(https_handler)

        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(metadata_url, headers={"Accept": "application/xml"})
        with opener.open(request, timeout=config.timeout_seconds) as response:
            xml_bytes = response.read()
        return xml_bytes.decode("utf-8"), metadata_url


class SapMetadataParser:
    def parse(self, xml_text: str, service_name: str, metadata_url: str) -> ParsedSapMetadata:
        root = ET.fromstring(xml_text)
        schema = root.find(".//edm:Schema", NS)
        if schema is None:
            raise ValueError("No EDM schema found in SAP metadata XML.")

        entity_types = {entity.attrib["Name"]: entity for entity in schema.findall("edm:EntityType", NS)}
        entity_sets = schema.findall(".//edm:EntitySet", NS)

        parsed_services: list[ServiceMetadata] = []
        parsed_entities: list[EntityMetadata] = []
        parsed_fields: list[FieldMetadata] = []
        parsed_relations: list[NavigationMetadata] = []
        parsed_chunks: list[DocumentChunk] = []

        service_entity_sets: list[str] = []
        service_methods: set[str] = set()

        for entity_set in entity_sets:
            entity_set_name = entity_set.attrib["Name"]
            service_entity_sets.append(entity_set_name)
            entity_type_name = entity_set.attrib.get("EntityType", "").split(".")[-1]
            entity_type = entity_types.get(entity_type_name)

            key_fields: set[str] = set()
            navigation_names: list[str] = []
            if entity_type is not None:
                key_node = entity_type.find("edm:Key", NS)
                if key_node is not None:
                    key_fields = {
                        prop_ref.attrib["Name"] for prop_ref in key_node.findall("edm:PropertyRef", NS)
                    }

            supported_methods = self._extract_supported_methods(entity_set)
            service_methods.update(supported_methods)

            entity_description = entity_set.attrib.get(f"{{{SAP_NS}}}label", "") or entity_type_name
            parsed_entities.append(
                EntityMetadata(
                    service_name=service_name,
                    entity_set=entity_set_name,
                    entity_type=entity_type_name,
                    key_fields=sorted(key_fields),
                    default_select_fields=[],
                    supports_filter=entity_set.attrib.get(f"{{{SAP_NS}}}filterable", "true") != "false",
                    supports_orderby=entity_set.attrib.get(f"{{{SAP_NS}}}sortable", "true") != "false",
                    supports_top=True,
                    navigations=navigation_names,
                    description=entity_description,
                    supported_methods=sorted(supported_methods),
                    source_documents=["sap_metadata"],
                    runtime_available=True,
                    documentation_available=False,
                )
            )

            parsed_chunks.append(
                DocumentChunk(
                    chunk_id=f"sap-entity-{service_name}-{entity_set_name}",
                    service_name=service_name,
                    entity_set=entity_set_name,
                    field_names=[],
                    content=f"Entity set {entity_set_name} in service {service_name} maps to {entity_type_name}.",
                    source_file=metadata_url,
                    section="entity_overview",
                    keywords=[entity_set_name, entity_type_name],
                    source_type="sap_metadata",
                )
            )

            if entity_type is None:
                continue

            default_select_fields: list[str] = []

            for prop in entity_type.findall("edm:Property", NS):
                field_name = prop.attrib["Name"]
                filterable = prop.attrib.get(f"{{{SAP_NS}}}filterable", "true") != "false"
                sortable = prop.attrib.get(f"{{{SAP_NS}}}sortable", "true") != "false"
                allowed_operators = self._extract_allowed_operators(prop, filterable)
                label = prop.attrib.get(f"{{{SAP_NS}}}label", "")
                description = prop.attrib.get(f"{{{SAP_NS}}}quickinfo", "") or label
                field_record = FieldMetadata(
                    service_name=service_name,
                    entity_set=entity_set_name,
                    field_name=field_name,
                    label=label,
                    business_aliases=[alias for alias in [label] if alias],
                    data_type=prop.attrib.get("Type", ""),
                    nullable=prop.attrib.get("Nullable", "true") != "false",
                    is_key=field_name in key_fields,
                    selectable=True,
                    filterable=filterable,
                    sortable=sortable,
                    allowed_operators=allowed_operators,
                    description=description,
                    source_documents=["sap_metadata"],
                    runtime_available=True,
                    documentation_available=False,
                )
                parsed_fields.append(field_record)
                if field_record.selectable:
                    default_select_fields.append(field_name)

                parsed_chunks.append(
                    DocumentChunk(
                        chunk_id=f"sap-field-{service_name}-{entity_set_name}-{field_name}",
                        service_name=service_name,
                        entity_set=entity_set_name,
                        field_names=[field_name],
                        content=(
                            f"Field {field_name} on {entity_set_name} has type {field_record.data_type}. "
                            f"Label: {label or 'n/a'}. Description: {description or 'n/a'}."
                        ),
                        source_file=metadata_url,
                        section="field_definition",
                        keywords=[entity_set_name, field_name, label] if label else [entity_set_name, field_name],
                        source_type="sap_metadata",
                    )
                )

            for nav_prop in entity_type.findall("edm:NavigationProperty", NS):
                navigation_name = nav_prop.attrib["Name"]
                navigation_names.append(navigation_name)
                target_entity = nav_prop.attrib.get("ToRole", "")
                parsed_relations.append(
                    NavigationMetadata(
                        service_name=service_name,
                        from_entity_set=entity_set_name,
                        navigation_name=navigation_name,
                        to_entity_set=target_entity,
                        cardinality=self._extract_cardinality(nav_prop.attrib.get("Relationship", "")),
                        source_documents=["sap_metadata"],
                    )
                )

            parsed_entities[-1].default_select_fields = default_select_fields[:10]
            parsed_entities[-1].navigations = navigation_names

        parsed_services.append(
            ServiceMetadata(
                service_name=service_name,
                service_version="0001",
                base_path=f"/sap/opu/odata/sap/{service_name}",
                description="",
                entity_sets=sorted(service_entity_sets),
                allowed_methods=sorted(service_methods or {"GET"}),
                source=metadata_url,
                source_documents=["sap_metadata"],
                runtime_available=True,
                documentation_available=False,
            )
        )

        return ParsedSapMetadata(
            services=parsed_services,
            entities=parsed_entities,
            fields=parsed_fields,
            relations=parsed_relations,
            doc_chunks=parsed_chunks,
            raw_xml=xml_text,
        )

    @staticmethod
    def _extract_supported_methods(entity_set: ET.Element) -> set[str]:
        methods = set()
        if entity_set.attrib.get(f"{{{SAP_NS}}}creatable", "false") == "true":
            methods.add("POST")
        if entity_set.attrib.get(f"{{{SAP_NS}}}updatable", "false") == "true":
            methods.add("PATCH")
        if entity_set.attrib.get(f"{{{SAP_NS}}}deletable", "false") == "true":
            methods.add("DELETE")
        if entity_set.attrib.get(f"{{{SAP_NS}}}pageable", "true") == "true":
            methods.add("GET")
        return methods or {"GET"}

    @staticmethod
    def _extract_allowed_operators(prop: ET.Element, filterable: bool) -> list[str]:
        if not filterable:
            return []

        restriction = prop.attrib.get(f"{{{SAP_NS}}}filter-restriction", "")
        if restriction == "single-value":
            return ["eq", "ne"]
        if restriction == "multi-value":
            return ["eq", "ne", "in"]
        if restriction == "interval":
            return ["eq", "ne", "ge", "gt", "le", "lt"]
        return ["eq", "ne", "ge", "gt", "le", "lt"]

    @staticmethod
    def _extract_cardinality(relationship: str) -> str:
        if relationship:
            return "association"
        return ""


class OpenApiDocumentParser:
    def parse(self, spec: dict[str, Any], source_file: str) -> ParsedOpenApiSpec:
        info = spec.get("info", {})
        service_name = self._extract_service_name(spec)
        entity_methods: dict[str, set[str]] = {}
        entity_descriptions: dict[str, str] = {}
        field_descriptions: dict[str, dict[str, str]] = {}
        doc_chunks: list[DocumentChunk] = []
        business_terms: list[BusinessTermAlias] = []

        for path, path_item in spec.get("paths", {}).items():
            entity_set = self._extract_entity_set_from_path(path)
            if not entity_set:
                continue
            entity_methods.setdefault(entity_set, set())
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                entity_methods[entity_set].add(method.upper())
                summary = ""
                description = ""
                if isinstance(operation, dict):
                    summary = operation.get("summary", "") or ""
                    description = operation.get("description", "") or ""
                    for tag in operation.get("tags", []):
                        business_terms.append(
                            BusinessTermAlias(
                                term=tag,
                                intent_type="documentation_tag",
                                mapped_service=service_name,
                                mapped_entity_set=entity_set,
                                confidence=0.4,
                                source="openapi_json",
                            )
                        )

                entity_descriptions.setdefault(entity_set, summary or description)
                if summary or description:
                    doc_chunks.append(
                        DocumentChunk(
                            chunk_id=f"openapi-path-{entity_set}-{method.lower()}",
                            service_name=service_name,
                            entity_set=entity_set,
                            field_names=[],
                            content=f"{method.upper()} {path}: {summary or description}",
                            source_file=source_file,
                            section="path_operation",
                            keywords=[entity_set, method.upper()],
                            source_type="openapi_json",
                        )
                    )

        for schema_name, schema in spec.get("components", {}).get("schemas", {}).items():
            base_name = self._normalize_schema_name(schema_name)
            entity_type = base_name
            entity_set = base_name[:-4] if base_name.endswith("Type") else base_name

            if not isinstance(schema, dict):
                continue

            schema_description = schema.get("description", "") or ""
            if schema_description:
                entity_descriptions.setdefault(entity_set, schema_description)

            field_descriptions.setdefault(entity_type, {})
            for field_name, field_schema in schema.get("properties", {}).items():
                if not isinstance(field_schema, dict):
                    continue
                field_description = field_schema.get("description", "") or ""
                if field_description and field_name not in field_descriptions[entity_type]:
                    field_descriptions[entity_type][field_name] = field_description
                    doc_chunks.append(
                        DocumentChunk(
                            chunk_id=f"openapi-field-{entity_set}-{field_name}",
                            service_name=service_name,
                            entity_set=entity_set,
                            field_names=[field_name],
                            content=f"Field {field_name} on {entity_set}: {field_description}",
                            source_file=source_file,
                            section="field_description",
                            keywords=[entity_set, field_name],
                            source_type="openapi_json",
                        )
                    )

        unique_terms = self._deduplicate_terms(business_terms)
        return ParsedOpenApiSpec(
            service_name=service_name,
            service_description=info.get("description", "") or spec.get("x-sap-shortText", "") or "",
            service_title=info.get("title", "") or service_name,
            openapi_version=info.get("version", "") or "",
            external_docs_url=(spec.get("externalDocs") or {}).get("url", ""),
            entity_descriptions=entity_descriptions,
            entity_methods={key: sorted(value) for key, value in entity_methods.items()},
            field_descriptions=field_descriptions,
            doc_chunks=doc_chunks,
            business_terms=unique_terms,
            raw_spec=spec,
        )

    @staticmethod
    def _extract_service_name(spec: dict[str, Any]) -> str:
        servers = spec.get("servers") or []
        if servers:
            server_url = (servers[0] or {}).get("url", "")
            if server_url:
                return server_url.rstrip("/").split("/")[-1]
        return "UNKNOWN_OPENAPI_SERVICE"

    @staticmethod
    def _extract_entity_set_from_path(path: str) -> str:
        normalized = path.strip("/")
        if not normalized:
            return ""
        segment = normalized.split("/")[0]
        if segment.startswith("$"):
            return ""
        if "(" in segment:
            segment = segment.split("(", 1)[0]
        return segment

    @staticmethod
    def _normalize_schema_name(schema_name: str) -> str:
        local_name = schema_name.split(".")[-1]
        for suffix in ("-create", "-update"):
            if local_name.endswith(suffix):
                return local_name[: -len(suffix)]
        return local_name

    @staticmethod
    def _deduplicate_terms(aliases: list[BusinessTermAlias]) -> list[BusinessTermAlias]:
        seen: set[tuple[str, str]] = set()
        deduped: list[BusinessTermAlias] = []
        for alias in aliases:
            key = (alias.term, alias.mapped_entity_set)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(alias)
        return deduped


class DualSourceIndexBuilder:
    def __init__(
        self,
        fetcher: SapMetadataFetcher | None = None,
        metadata_parser: SapMetadataParser | None = None,
        openapi_parser: OpenApiDocumentParser | None = None,
    ) -> None:
        self.fetcher = fetcher or SapMetadataFetcher()
        self.metadata_parser = metadata_parser or SapMetadataParser()
        self.openapi_parser = openapi_parser or OpenApiDocumentParser()

    def build(
        self,
        sap_config: SapConnectionConfig,
        sap_service_name: str,
        openapi_json_path: str | Path,
        output_root: str | Path,
        index_service_name: str | None = None,
    ) -> IndexBundle:
        target_service_name = index_service_name or sap_service_name
        xml_text, metadata_url = self.fetcher.fetch(sap_config, sap_service_name)
        openapi_path = Path(openapi_json_path)
        openapi_spec = json.loads(openapi_path.read_text(encoding="utf-8-sig"))

        parsed_metadata = self.metadata_parser.parse(xml_text, target_service_name, metadata_url)
        parsed_openapi = self.openapi_parser.parse(openapi_spec, str(openapi_path))
        bundle = self._merge(parsed_metadata, parsed_openapi, target_service_name)
        self._write_bundle(bundle, Path(output_root), target_service_name, openapi_path)
        return bundle

    def _merge(
        self,
        sap_metadata: ParsedSapMetadata,
        openapi_doc: ParsedOpenApiSpec,
        service_name: str,
    ) -> IndexBundle:
        service_map = {record.service_name: record for record in sap_metadata.services}
        entity_map = {(record.service_name, record.entity_set): record for record in sap_metadata.entities}
        field_map = {(record.service_name, record.entity_set, record.field_name): record for record in sap_metadata.fields}
        relations = list(sap_metadata.relations)
        doc_chunks = list(sap_metadata.doc_chunks)
        doc_chunks.extend(openapi_doc.doc_chunks)
        business_terms = list(openapi_doc.business_terms)

        service_record = service_map.get(service_name)
        if service_record is None:
            service_record = ServiceMetadata(service_name=service_name)
            service_map[service_name] = service_record
        service_record.description = service_record.description or openapi_doc.service_description or openapi_doc.service_title
        service_record.documentation_available = True
        service_record.documentation_url = openapi_doc.external_docs_url
        service_record.openapi_version = openapi_doc.openapi_version
        service_record.source_documents = sorted(set(service_record.source_documents + ["sap_metadata", "openapi_json"]))

        for (svc_name, entity_set), entity_record in list(entity_map.items()):
            if svc_name != service_name:
                continue
            entity_record.documentation_available = entity_set in openapi_doc.entity_methods or entity_set in openapi_doc.entity_descriptions
            entity_record.source_documents = sorted(
                set(entity_record.source_documents + (["openapi_json"] if entity_record.documentation_available else []))
            )
            entity_record.description = openapi_doc.entity_descriptions.get(entity_set) or entity_record.description
            entity_record.supported_methods = sorted(
                set(entity_record.supported_methods + openapi_doc.entity_methods.get(entity_set, []))
            ) or ["GET"]

        for entity_set, methods in openapi_doc.entity_methods.items():
            key = (service_name, entity_set)
            if key in entity_map:
                continue
            entity_map[key] = EntityMetadata(
                service_name=service_name,
                entity_set=entity_set,
                entity_type=f"{entity_set}Type",
                description=openapi_doc.entity_descriptions.get(entity_set, ""),
                supported_methods=methods or ["GET"],
                source_documents=["openapi_json"],
                runtime_available=False,
                documentation_available=True,
            )

        entity_type_to_set = {
            record.entity_type: record.entity_set
            for record in entity_map.values()
            if record.service_name == service_name and record.entity_type
        }

        for entity_type, descriptions in openapi_doc.field_descriptions.items():
            entity_set = entity_type_to_set.get(entity_type)
            if entity_set is None and entity_type.endswith("Type"):
                entity_set = entity_type[:-4]

            if not entity_set:
                continue

            for field_name, description in descriptions.items():
                key = (service_name, entity_set, field_name)
                if key in field_map:
                    field_record = field_map[key]
                    field_record.documentation_available = True
                    field_record.source_documents = sorted(set(field_record.source_documents + ["openapi_json"]))
                    if not field_record.description:
                        field_record.description = description
                else:
                    field_map[key] = FieldMetadata(
                        service_name=service_name,
                        entity_set=entity_set,
                        field_name=field_name,
                        description=description,
                        allowed_operators=["eq"],
                        source_documents=["openapi_json"],
                        runtime_available=False,
                        documentation_available=True,
                    )

        self._apply_metadata_field_aliases(field_map)
        business_terms.extend(self._build_field_business_terms(service_name, field_map))
        business_terms = self._deduplicate_business_terms(business_terms)
        lookup_paths = self._build_lookup_paths(service_name, entity_map, field_map)
        entity_graph = self._build_entity_graph(service_name, relations, lookup_paths)
        vector_documents = self._build_vector_documents(service_name, field_map, lookup_paths)

        summary = {
            "service_name": service_name,
            "sap_metadata_entity_count": len(sap_metadata.entities),
            "sap_metadata_field_count": len(sap_metadata.fields),
            "openapi_documented_entity_count": len(openapi_doc.entity_methods),
            "openapi_documented_entity_type_count": len(openapi_doc.field_descriptions),
            "merged_entity_count": len(entity_map),
            "merged_field_count": len(field_map),
            "relation_count": len(relations),
            "entity_graph_edge_count": len(entity_graph),
            "lookup_path_count": len(lookup_paths),
            "business_term_count": len(business_terms),
            "vector_document_count": len(vector_documents),
            "doc_chunk_count": len(doc_chunks),
        }

        return IndexBundle(
            services=list(service_map.values()),
            entities=sorted(entity_map.values(), key=lambda item: (item.service_name, item.entity_set)),
            fields=sorted(field_map.values(), key=lambda item: (item.service_name, item.entity_set, item.field_name)),
            relations=sorted(relations, key=lambda item: (item.service_name, item.from_entity_set, item.navigation_name)),
            entity_graph=sorted(entity_graph, key=lambda item: (item.from_entity_set, item.to_entity_set, item.edge_type)),
            lookup_paths=sorted(lookup_paths, key=lambda item: item.path_id),
            business_terms=sorted(business_terms, key=lambda item: (item.mapped_entity_set, item.term)),
            vector_documents=sorted(vector_documents, key=lambda item: item.doc_id),
            doc_chunks=doc_chunks,
            raw_metadata_xml=sap_metadata.raw_xml,
            raw_openapi_spec=openapi_doc.raw_spec,
            summary=summary,
        )

    @staticmethod
    def _apply_metadata_field_aliases(field_map: dict[tuple[str, str, str], FieldMetadata]) -> None:
        for field_record in field_map.values():
            aliases = list(field_record.business_aliases)
            if field_record.label:
                aliases.append(field_record.label)
            if field_record.description and field_record.description != field_record.label:
                aliases.append(field_record.description)
            deduped: list[str] = []
            seen: set[str] = set()
            for alias in aliases:
                normalized = alias.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                deduped.append(normalized)
            field_record.business_aliases = deduped

    @staticmethod
    def _build_field_business_terms(
        service_name: str,
        field_map: dict[tuple[str, str, str], FieldMetadata],
    ) -> list[BusinessTermAlias]:
        aliases: list[BusinessTermAlias] = []
        for field_record in field_map.values():
            for alias in field_record.business_aliases:
                aliases.append(
                    BusinessTermAlias(
                        term=alias,
                        intent_type="field_alias",
                        mapped_service=service_name,
                        mapped_entity_set=field_record.entity_set,
                        mapped_fields=[field_record.field_name],
                        synonyms=[item for item in field_record.business_aliases if item != alias],
                        confidence=0.8,
                        source="metadata_field_alias",
                    )
                )
        return aliases

    @staticmethod
    def _deduplicate_business_terms(aliases: list[BusinessTermAlias]) -> list[BusinessTermAlias]:
        deduped: dict[tuple[str, str, tuple[str, ...]], BusinessTermAlias] = {}
        for alias in aliases:
            key = (
                alias.term,
                alias.mapped_entity_set,
                tuple(sorted(alias.mapped_fields)),
            )
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = alias
                continue
            merged_synonyms = sorted(set(existing.synonyms + alias.synonyms))
            existing.synonyms = merged_synonyms
            existing.confidence = max(existing.confidence, alias.confidence)
            if existing.source != alias.source:
                existing.source = f"{existing.source},{alias.source}"
        return list(deduped.values())

    @staticmethod
    def _build_lookup_paths(
        service_name: str,
        entity_map: dict[tuple[str, str], EntityMetadata],
        field_map: dict[tuple[str, str, str], FieldMetadata],
    ) -> list[LookupPathMetadata]:
        entity_fields: dict[str, dict[str, FieldMetadata]] = {}
        for (svc_name, entity_set, field_name), field_record in field_map.items():
            if svc_name != service_name:
                continue
            entity_fields.setdefault(entity_set, {})[field_name] = field_record

        paths: list[LookupPathMetadata] = []
        seen: set[str] = set()

        def add_path(
            *,
            path_id: str,
            anchor_object: str,
            target_entity_set: str,
            target_field: str,
            path_kind: str,
            return_object: str,
            filter_fields: list[str],
            result_fields: list[str],
            description: str,
            business_aliases: list[str],
            steps: list[dict[str, str]],
            confidence: float,
        ) -> None:
            if path_id in seen:
                return
            seen.add(path_id)
            paths.append(
                LookupPathMetadata(
                    path_id=path_id,
                    service_name=service_name,
                    anchor_object=anchor_object,
                    target_entity_set=target_entity_set,
                    target_field=target_field,
                    path_kind=path_kind,
                    return_object=return_object,
                    filter_fields=filter_fields,
                    result_fields=result_fields,
                    description=description,
                    business_aliases=business_aliases,
                    steps=steps,
                    confidence=confidence,
                )
            )

        def address_entity_confidence_bias(entity_set: str) -> float:
            return 0.0

        def aliases_for(entity_set: str, field_name: str) -> list[str]:
            field_record = entity_fields.get(entity_set, {}).get(field_name)
            if field_record is None:
                return []
            aliases = [field_record.label, field_record.description, *field_record.business_aliases]
            deduped: list[str] = []
            seen: set[str] = set()
            for alias in aliases:
                normalized = str(alias or "").strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                deduped.append(normalized)
            return deduped

        def selectable_target_fields(fields: dict[str, FieldMetadata], *, exclude: set[str] | None = None) -> list[str]:
            excluded = exclude or set()
            return [
                field_name
                for field_name, field_record in fields.items()
                if field_name not in excluded and field_record.selectable
            ]

        for entity_set, fields in entity_fields.items():
            for target_field in selectable_target_fields(fields):
                aliases = aliases_for(entity_set, target_field)
                for anchor_field in ("Supplier", "Customer", "BusinessPartner"):
                    if anchor_field not in fields:
                        continue
                    add_path(
                        path_id=f"{anchor_field.lower()}_to_{target_field.lower()}_{entity_set.lower()}",
                        anchor_object=anchor_field,
                        target_entity_set=entity_set,
                        target_field=target_field,
                        path_kind="direct_lookup",
                        return_object=anchor_field,
                        filter_fields=[anchor_field],
                        result_fields=[anchor_field, target_field],
                        description=f"Resolve `{anchor_field}` directly on `{entity_set}` to answer `{target_field}`.",
                        business_aliases=aliases,
                        steps=[
                            {
                                "step_id": "fetch_target",
                                "entity_set": entity_set,
                                "filter_field": anchor_field,
                                "select_fields": [anchor_field, target_field],
                                "top": 20 if anchor_field == target_field else 5,
                            }
                        ],
                        confidence=0.72,
                    )

        if "A_BusinessPartner" in entity_fields:
            bp_fields = entity_fields["A_BusinessPartner"]
            address_entities = []
            for entity_set, fields in entity_fields.items():
                join_field = next(
                    (
                        candidate
                        for candidate in ("BusinessPartner", "BusinessPartnerCompany")
                        if candidate in fields
                    ),
                    "",
                )
                if not join_field:
                    continue
                if not any(field_record.selectable for field_name, field_record in fields.items() if field_name != join_field):
                    continue
                address_entities.append((entity_set, fields, join_field))

            for address_entity_set, address_fields, join_field in address_entities:
                shared_address_fields = [
                    field_name
                    for field_name, field_record in address_fields.items()
                    if field_record.selectable and field_name != join_field
                ]
                shared_address_fields = shared_address_fields[:8]

                for target_field in selectable_target_fields(address_fields, exclude={join_field}):
                    aliases = aliases_for(address_entity_set, target_field)
                    result_fields = [join_field, target_field, *[field for field in shared_address_fields if field != target_field]]
                    result_fields = list(dict.fromkeys(result_fields))[:10]
                    for anchor_field in ("Supplier", "Customer"):
                        if anchor_field not in bp_fields:
                            continue
                        lookup_confidence = (0.88 if join_field == "BusinessPartner" else 0.74) + address_entity_confidence_bias(address_entity_set)
                        add_path(
                            path_id=f"{anchor_field.lower()}_to_{target_field.lower()}_via_{address_entity_set.lower()}",
                            anchor_object=anchor_field,
                            target_entity_set=address_entity_set,
                            target_field=target_field,
                            path_kind="multi_step_lookup",
                            return_object=anchor_field,
                            filter_fields=[anchor_field, target_field],
                            result_fields=[anchor_field, *result_fields],
                            description=(
                                f"Resolve `{anchor_field}` to `{join_field}` first, then read `{target_field}` "
                                f"from `{address_entity_set}`."
                            ),
                            business_aliases=aliases,
                            steps=[
                                {
                                    "step_id": "resolve_anchor",
                                    "entity_set": "A_BusinessPartner",
                                    "filter_field": anchor_field,
                                    "select_fields": [join_field, anchor_field],
                                    "top": 1,
                                },
                                {
                                    "step_id": "fetch_target",
                                    "entity_set": address_entity_set,
                                    "filter_field": join_field,
                                    "select_fields": result_fields,
                                    "top": 5,
                                },
                            ],
                            confidence=lookup_confidence,
                        )
                    add_path(
                        path_id=f"businesspartner_to_{target_field.lower()}_via_{address_entity_set.lower()}",
                        anchor_object="BusinessPartner",
                        target_entity_set=address_entity_set,
                        target_field=target_field,
                        path_kind="lookup",
                        return_object="BusinessPartner",
                        filter_fields=["BusinessPartner", target_field],
                        result_fields=["BusinessPartner", *result_fields],
                        description=f"Read `{target_field}` directly from `{address_entity_set}`.",
                        business_aliases=aliases,
                        steps=[
                            {
                                "step_id": "fetch_target",
                                "entity_set": address_entity_set,
                                "filter_field": join_field,
                                "select_fields": result_fields,
                                "top": 5,
                            }
                        ],
                        confidence=(0.84 if join_field == "BusinessPartner" else 0.72) + address_entity_confidence_bias(address_entity_set),
                    )

                for filter_field, field_record in address_fields.items():
                    if filter_field == join_field or not field_record.filterable:
                        continue
                    aliases = aliases_for(address_entity_set, filter_field)
                    for anchor_field in ("Supplier", "Customer"):
                        if anchor_field not in bp_fields:
                            continue
                        filter_confidence = (0.96 if join_field == "BusinessPartner" else 0.74) + address_entity_confidence_bias(address_entity_set)
                        add_path(
                            path_id=f"{anchor_field.lower()}_list_by_{filter_field.lower()}_via_{address_entity_set.lower()}",
                            anchor_object=anchor_field,
                            target_entity_set="A_BusinessPartner",
                            target_field=filter_field,
                            path_kind="attribute_filter_list",
                            return_object=anchor_field,
                            filter_fields=[filter_field],
                            result_fields=[anchor_field, "BusinessPartner", "BusinessPartnerFullName"],
                            description=(
                                f"Filter `{anchor_field}` records by address attribute `{filter_field}` via `{address_entity_set}` "
                                "and return the matching object list."
                            ),
                            business_aliases=aliases,
                            steps=[
                                {
                                    "step_id": "filter_address",
                                    "entity_set": address_entity_set,
                                    "filter_field": filter_field,
                                    "select_fields": [join_field, *shared_address_fields],
                                    "top": 50,
                                },
                                {
                                    "step_id": "resolve_anchor_object",
                                    "entity_set": "A_BusinessPartner",
                                    "filter_field": "BusinessPartner",
                                    "select_fields": [
                                        "BusinessPartner",
                                        anchor_field,
                                        "BusinessPartnerFullName",
                                    ],
                                    "top": 50,
                                },
                            ],
                            confidence=max(0.72, filter_confidence - 0.08),
                        )

        return paths

    @staticmethod
    def _build_entity_graph(
        service_name: str,
        relations: list[NavigationMetadata],
        lookup_paths: list[LookupPathMetadata],
    ) -> list[EntityGraphEdge]:
        edges: list[EntityGraphEdge] = []
        seen: set[tuple[str, str, str, str, str, str]] = set()

        def add_edge(
            *,
            from_entity_set: str,
            to_entity_set: str,
            edge_type: str,
            from_field: str = "",
            to_field: str = "",
            via_path_id: str = "",
            description: str = "",
            confidence: float = 0.0,
        ) -> None:
            if not from_entity_set or not to_entity_set:
                return
            key = (from_entity_set, to_entity_set, edge_type, from_field, to_field, via_path_id)
            if key in seen:
                return
            seen.add(key)
            edges.append(
                EntityGraphEdge(
                    service_name=service_name,
                    from_entity_set=from_entity_set,
                    to_entity_set=to_entity_set,
                    edge_type=edge_type,
                    from_field=from_field,
                    to_field=to_field,
                    via_path_id=via_path_id,
                    description=description,
                    confidence=confidence,
                )
            )

        for relation in relations:
            add_edge(
                from_entity_set=relation.from_entity_set,
                to_entity_set=relation.to_entity_set,
                edge_type="navigation",
                via_path_id=relation.navigation_name,
                description=f"Navigation `{relation.navigation_name}` from `{relation.from_entity_set}` to `{relation.to_entity_set}`.",
                confidence=0.8,
            )

        for path in lookup_paths:
            steps = path.steps or []
            if len(steps) < 2:
                continue
            for previous, current in zip(steps, steps[1:]):
                add_edge(
                    from_entity_set=str(previous.get("entity_set", "")),
                    to_entity_set=str(current.get("entity_set", "")),
                    edge_type="lookup_path",
                    from_field=str(current.get("filter_field", "")),
                    to_field=str(current.get("filter_field", "")),
                    via_path_id=path.path_id,
                    description=path.description,
                    confidence=path.confidence,
                )

        return edges

    @staticmethod
    def _build_vector_documents(
        service_name: str,
        field_map: dict[tuple[str, str, str], FieldMetadata],
        lookup_paths: list[LookupPathMetadata],
    ) -> list[VectorDocument]:
        documents: list[VectorDocument] = []
        for field_record in field_map.values():
            if field_record.service_name != service_name:
                continue
            aliases = ", ".join(field_record.business_aliases)
            documents.append(
                VectorDocument(
                    doc_id=f"field::{field_record.entity_set}.{field_record.field_name}",
                    doc_type="field",
                    service_name=service_name,
                    entity_set=field_record.entity_set,
                    field_name=field_record.field_name,
                    keywords=[field_record.field_name, field_record.label, *field_record.business_aliases],
                    content=(
                        f"entity: {field_record.entity_set}\n"
                        f"field: {field_record.field_name}\n"
                        f"label: {field_record.label}\n"
                        f"description: {field_record.description}\n"
                        f"aliases: {aliases}"
                    ),
                    metadata={
                        "label": field_record.label,
                        "description": field_record.description,
                    },
                )
            )

        for path_record in lookup_paths:
            step_summary = " -> ".join(
                f"{step.get('entity_set', '')}.{step.get('filter_field', '')}" for step in path_record.steps
            )
            documents.append(
                VectorDocument(
                    doc_id=f"path::{path_record.path_id}",
                    doc_type="lookup_path",
                    service_name=service_name,
                    entity_set=path_record.target_entity_set,
                    field_name=path_record.target_field,
                    path_id=path_record.path_id,
                    keywords=[
                        path_record.anchor_object,
                        path_record.target_field,
                        path_record.target_entity_set,
                        path_record.return_object,
                        *path_record.filter_fields,
                        *path_record.result_fields,
                        *path_record.business_aliases,
                    ],
                    content=(
                        f"path: {path_record.path_id}\n"
                        f"path_kind: {path_record.path_kind}\n"
                        f"anchor: {path_record.anchor_object}\n"
                        f"return_object: {path_record.return_object}\n"
                        f"target_entity: {path_record.target_entity_set}\n"
                        f"target_field: {path_record.target_field}\n"
                        f"filter_fields: {', '.join(path_record.filter_fields)}\n"
                        f"result_fields: {', '.join(path_record.result_fields)}\n"
                        f"description: {path_record.description}\n"
                        f"aliases: {', '.join(path_record.business_aliases)}\n"
                        f"steps: {step_summary}"
                    ),
                    metadata={
                        "description": path_record.description,
                        "anchor_object": path_record.anchor_object,
                        "path_kind": path_record.path_kind,
                        "return_object": path_record.return_object,
                        "filter_fields": path_record.filter_fields,
                        "result_fields": path_record.result_fields,
                        "business_aliases": path_record.business_aliases,
                        "steps": path_record.steps,
                        "target_entity_set": path_record.target_entity_set,
                        "target_field": path_record.target_field,
                    },
                )
            )

        return documents

    def _write_bundle(
        self,
        bundle: IndexBundle,
        output_root: Path,
        service_name: str,
        openapi_json_path: Path,
    ) -> None:
        service_dir = output_root / service_name
        raw_dir = service_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        (raw_dir / f"{service_name}.metadata.xml").write_text(bundle.raw_metadata_xml, encoding="utf-8")
        (raw_dir / openapi_json_path.name).write_text(
            json.dumps(bundle.raw_openapi_spec, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._write_json(service_dir / "services.json", bundle.services)
        self._write_json(service_dir / "entities.json", bundle.entities)
        self._write_json(service_dir / "fields.json", bundle.fields)
        self._write_json(service_dir / "relations.json", bundle.relations)
        self._write_json(service_dir / "entity_graph.json", bundle.entity_graph)
        self._write_json(service_dir / "lookup_paths.json", bundle.lookup_paths)
        self._write_json(service_dir / "business_terms.json", bundle.business_terms)
        self._write_json(service_dir / "build_summary.json", bundle.summary)
        self._write_jsonl_generic(service_dir / "vector_documents.jsonl", bundle.vector_documents)
        self._write_jsonl(service_dir / "doc_chunks.jsonl", bundle.doc_chunks)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        if isinstance(payload, list):
            serialized = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in payload]
        elif hasattr(payload, "__dataclass_fields__"):
            serialized = asdict(payload)
        else:
            serialized = payload
        path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _write_jsonl(path: Path, rows: list[DocumentChunk]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")

    @staticmethod
    def _write_jsonl_generic(path: Path, rows: list[Any]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                payload = asdict(row) if hasattr(row, "__dataclass_fields__") else row
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
