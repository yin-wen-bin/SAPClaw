from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sap_odata_agent.domain.models import ApiRouteDecision, RetrievedDocument
from sap_odata_agent.infrastructure.indexing.function_imports import function_imports_from_snapshot
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader


class SchemaContextProvider:
    """Provide API-specific schema context after routing.

    This component trims metadata for prompt size, but it does not decide the
    final business intent. The LLM planner remains responsible for choosing
    fields/entities/paths.
    """

    def __init__(
        self,
        index_root: str | Path = "data/index",
        max_candidate_fields: int = 220,
        max_candidate_entities: int = 32,
    ) -> None:
        self.loader = LocalIndexLoader(index_root=index_root)
        self.max_candidate_fields = max_candidate_fields
        self.max_candidate_entities = max_candidate_entities

    def build(
        self,
        service_name: str,
        query: str,
        route_decision: ApiRouteDecision | None = None,
        retrieved_documents: list[RetrievedDocument] | None = None,
        feedback_memories: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        service_names = self._route_service_names(service_name, route_decision)
        if len(service_names) > 1:
            contexts = [
                self.build(
                    name,
                    query,
                    route_decision=None,
                    retrieved_documents=retrieved_documents,
                    feedback_memories=feedback_memories,
                )
                for name in service_names
            ]
            return self._merge_contexts(contexts, route_decision)

        snapshot = self.loader.load(service_name)
        function_imports = function_imports_from_snapshot(snapshot)
        function_import_map = {str(item.get("name", "")): item for item in function_imports}
        doc_entities = self._entity_sets_from_documents(retrieved_documents or [])
        doc_fields = self._field_refs_from_documents(retrieved_documents or [])
        feedback_field_matches = self._feedback_field_matches(snapshot, feedback_memories or [], route_decision)
        feedback_field_scores = {
            (str(match["entity_set"]), str(match["field_name"])): float(match["score"])
            for match in feedback_field_matches
        }
        scored_fields: list[tuple[float, dict[str, Any]]] = []
        for field in snapshot.fields:
            score = self._score_field(query, field)
            key = (str(field.get("entity_set", "")), str(field.get("field_name", "")))
            if key in doc_fields:
                score += min(doc_fields[key], 20.0) * 0.8
            if key in feedback_field_scores:
                score += feedback_field_scores[key]
            scored_fields.append((score, field))
        scored_fields.sort(key=lambda item: item[0], reverse=True)

        candidate_fields = []
        seen_fields: set[tuple[str, str]] = set()
        for score, field in scored_fields:
            entity_set = str(field.get("entity_set", ""))
            field_name = str(field.get("field_name", ""))
            if not entity_set or not field_name:
                continue
            if score <= 0 and entity_set not in doc_entities:
                continue
            key = (entity_set, field_name)
            if key in seen_fields:
                continue
            seen_fields.add(key)
            candidate_fields.append(self._field_payload(field, score))
            if len(candidate_fields) >= self.max_candidate_fields:
                break

        candidate_entities = self._expand_candidate_entities(snapshot, candidate_fields, doc_entities)
        entities = [
            self._entity_payload(snapshot, entity_set, candidate_fields, function_import_map)
            for entity_set in candidate_entities[: self.max_candidate_entities]
        ]
        entities = [item for item in entities if item]
        entity_set_scope = {item["entity_set"] for item in entities}

        return {
            "service_name": service_name,
            "service": self._service_payload(snapshot),
            "service_names": [service_name],
            "services": [self._service_payload(snapshot)],
            "query": query,
            "route_decision": self._route_payload(route_decision),
            "entities": entities,
            "function_imports": function_imports,
            "candidate_fields": candidate_fields,
            "join_hints": self._build_join_hints(snapshot, entity_set_scope),
            "relations": self._build_relation_hints(snapshot, entity_set_scope),
            "retrieved_documents": self._document_payload(retrieved_documents or []),
            "feedback_memories": feedback_memories or [],
            "feedback_field_matches": [
                {key: value for key, value in match.items() if key != "score"}
                for match in feedback_field_matches
            ],
        }

    @staticmethod
    def _route_service_names(service_name: str, route_decision: ApiRouteDecision | None) -> list[str]:
        names = [str(service_name or "").strip()] if str(service_name or "").strip() else []
        if route_decision is not None and route_decision.requires_multi_api:
            names.extend(
                str(item.service_name or "").strip()
                for item in route_decision.selected_apis
                if str(item.service_name or "").strip()
            )
        return list(dict.fromkeys(names))

    def _merge_contexts(
        self,
        contexts: list[dict[str, Any]],
        route_decision: ApiRouteDecision | None,
    ) -> dict[str, Any]:
        contexts = [context for context in contexts if context]
        if not contexts:
            return {}

        primary = contexts[0]
        service_names = [
            str(context.get("service_name") or "").strip()
            for context in contexts
            if str(context.get("service_name") or "").strip()
        ]
        service_names = list(dict.fromkeys(service_names))

        entities: list[dict[str, Any]] = []
        seen_entities: set[tuple[str, str]] = set()
        candidate_fields: list[dict[str, Any]] = []
        seen_fields: set[tuple[str, str, str]] = set()
        function_imports: list[dict[str, Any]] = []
        join_hints: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        services: list[dict[str, Any]] = []

        for context in contexts:
            context_service = str(context.get("service_name") or "")
            service_payload = dict(context.get("service") or {})
            if service_payload:
                service_payload.setdefault("service_name", context_service)
                services.append(service_payload)

            for entity in context.get("entities", []):
                if not isinstance(entity, dict):
                    continue
                entity_service = str(entity.get("service_name") or context_service)
                key = (entity_service, str(entity.get("entity_set") or ""))
                if not key[0] or not key[1] or key in seen_entities:
                    continue
                seen_entities.add(key)
                entities.append({**entity, "service_name": entity_service})

            for field in context.get("candidate_fields", []):
                if not isinstance(field, dict):
                    continue
                field_service = str(field.get("service_name") or context_service)
                key = (
                    field_service,
                    str(field.get("entity_set") or ""),
                    str(field.get("field_name") or ""),
                )
                if not key[0] or not key[1] or not key[2] or key in seen_fields:
                    continue
                seen_fields.add(key)
                candidate_fields.append({**field, "service_name": field_service})

            for item in context.get("function_imports", []):
                if isinstance(item, dict):
                    function_imports.append({**item, "service_name": item.get("service_name") or context_service})
            for item in context.get("join_hints", []):
                if isinstance(item, dict):
                    join_hints.append({**item, "service_name": item.get("service_name") or context_service})
            for item in context.get("relations", []):
                if isinstance(item, dict):
                    relations.append({**item, "service_name": item.get("service_name") or context_service})

        join_hints = [*join_hints, *self._build_cross_service_join_hints(entities)]

        return {
            **primary,
            "service_name": service_names[0] if service_names else primary.get("service_name", ""),
            "service_names": service_names,
            "services": services,
            "service": services[0] if services else primary.get("service", {}),
            "route_decision": self._route_payload(route_decision),
            "entities": entities,
            "function_imports": function_imports,
            "candidate_fields": candidate_fields[: self.max_candidate_fields * max(1, len(service_names))],
            "join_hints": join_hints,
            "relations": relations,
            "multi_api": len(service_names) > 1,
        }

    @staticmethod
    def _build_cross_service_join_hints(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_field: dict[str, list[dict[str, str]]] = {}
        for entity in entities:
            service_name = str(entity.get("service_name") or "")
            entity_set = str(entity.get("entity_set") or "")
            if not service_name or not entity_set:
                continue
            for field in entity.get("fields", []):
                if not isinstance(field, dict):
                    continue
                field_name = str(field.get("field_name") or "")
                if not field_name:
                    continue
                by_field.setdefault(field_name, []).append(
                    {"service_name": service_name, "entity_set": entity_set}
                )

        hints: list[dict[str, Any]] = []
        for field_name, refs in by_field.items():
            unique_refs = [dict(item) for item in {tuple(ref.items()) for ref in refs}]
            service_count = len({ref["service_name"] for ref in unique_refs})
            entity_sets = list(dict.fromkeys(ref["entity_set"] for ref in unique_refs))
            if service_count < 2 or len(entity_sets) < 2:
                continue
            hints.append(
                {
                    "field_name": field_name,
                    "entity_sets": entity_sets[:12],
                    "entities": sorted(unique_refs, key=lambda item: (item["service_name"], item["entity_set"]))[:12],
                    "cross_service": True,
                }
            )
        hints.sort(key=lambda item: (-len(item["entity_sets"]), item["field_name"]))
        return hints[:80]

    def enrich_with_api_skill(self, schema_context: dict[str, Any], api_skill: dict[str, Any] | None) -> dict[str, Any]:
        if not api_skill:
            return schema_context
        service_name = str(schema_context.get("service_name") or api_skill.get("service_name") or "")
        if not service_name:
            return schema_context
        if schema_context.get("multi_api"):
            return {
                **schema_context,
                "skill_field_matches": schema_context.get("skill_field_matches", []),
            }

        snapshot = self.loader.load(service_name)
        function_imports = schema_context.get("function_imports") or function_imports_from_snapshot(snapshot)
        function_import_map = {str(item.get("name", "")): item for item in function_imports}
        skill_field_matches = self._skill_field_matches(snapshot, api_skill)
        if not skill_field_matches:
            return {
                **schema_context,
                "function_imports": function_imports,
                "skill_field_matches": [],
            }

        field_by_key = {
            (str(field.get("entity_set", "")), str(field.get("field_name", ""))): field
            for field in snapshot.fields
        }
        enriched_fields: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for match in skill_field_matches:
            key = (str(match["entity_set"]), str(match["field_name"]))
            field = field_by_key.get(key)
            if field is None or key in seen:
                continue
            seen.add(key)
            enriched_fields.append(self._field_payload(field, float(match["score"])))

        for field in schema_context.get("candidate_fields", []):
            key = (str(field.get("entity_set", "")), str(field.get("field_name", "")))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            enriched_fields.append(field)
            if len(enriched_fields) >= self.max_candidate_fields:
                break

        candidate_entity_order: list[str] = []

        def add_entity(entity_set: str) -> None:
            if entity_set and entity_set not in candidate_entity_order:
                candidate_entity_order.append(entity_set)

        for field in enriched_fields:
            add_entity(str(field.get("entity_set", "")))
        for entity in schema_context.get("entities", []):
            add_entity(str(entity.get("entity_set", "")))

        entities = [
            self._entity_payload(snapshot, entity_set, enriched_fields, function_import_map)
            for entity_set in candidate_entity_order[: self.max_candidate_entities]
        ]
        entities = [item for item in entities if item]
        entity_set_scope = {item["entity_set"] for item in entities}

        return {
            **schema_context,
            "candidate_fields": enriched_fields[: self.max_candidate_fields],
            "entities": entities,
            "function_imports": function_imports,
            "join_hints": self._build_join_hints(snapshot, entity_set_scope),
            "relations": self._build_relation_hints(snapshot, entity_set_scope),
            "skill_field_matches": [
                {key: value for key, value in match.items() if key != "score"}
                for match in skill_field_matches
            ],
        }

    @staticmethod
    def summarize(schema_context: dict[str, Any]) -> dict[str, Any]:
        available_fields = []
        seen_available_fields: set[tuple[str, str]] = set()

        def add_available_field(field: dict[str, Any], entity_set_override: str = "") -> None:
            if not isinstance(field, dict):
                return
            entity_set = str(entity_set_override or field.get("entity_set", "") or "")
            field_name = str(field.get("field_name", "") or "")
            if not entity_set or not field_name:
                return
            key = (entity_set, field_name)
            if key in seen_available_fields:
                return
            seen_available_fields.add(key)
            available_fields.append(
                {
                    "entity_set": entity_set,
                    "field_name": field_name,
                    "label": field.get("label", ""),
                    "data_type": field.get("data_type", ""),
                    "filterable": field.get("filterable", False),
                }
            )

        for field in schema_context.get("candidate_fields", []):
            add_available_field(field)
            if len(available_fields) >= 120:
                break
        for entity in schema_context.get("entities", []):
            if len(available_fields) >= 160:
                break
            if not isinstance(entity, dict):
                continue
            entity_set = str(entity.get("entity_set", "") or "")
            for field in entity.get("fields", []):
                add_available_field(field, entity_set_override=entity_set)
                if len(available_fields) >= 160:
                    break
        return {
            "service_name": schema_context.get("service_name", ""),
            "service_names": schema_context.get("service_names", [schema_context.get("service_name", "")]),
            "services": schema_context.get("services", []),
            "service": schema_context.get("service", {}),
            "entity_count": len(schema_context.get("entities", [])),
            "candidate_field_count": len(schema_context.get("candidate_fields", [])),
            "join_hint_count": len(schema_context.get("join_hints", [])),
            "relation_count": len(schema_context.get("relations", [])),
            "function_imports": schema_context.get("function_imports", [])[:20],
            "api_skill": {
                "service_name": (schema_context.get("api_skill") or {}).get("service_name", ""),
                "summary": (schema_context.get("api_skill") or {}).get("summary", ""),
                "path": (schema_context.get("api_skill") or {}).get("path", ""),
            }
            if schema_context.get("api_skill")
            else {},
            "api_skills": [
                {
                    "service_name": item.get("service_name", ""),
                    "path": item.get("path", ""),
                }
                for item in schema_context.get("api_skills", [])
                if isinstance(item, dict)
            ],
            "top_entities": [item.get("entity_set") for item in schema_context.get("entities", [])[:8]],
            "top_fields": [
                f"{item.get('entity_set')}.{item.get('field_name')}"
                for item in schema_context.get("candidate_fields", [])[:16]
            ],
            "available_fields": available_fields,
            "feedback_field_matches": schema_context.get("feedback_field_matches", []),
            "skill_field_matches": schema_context.get("skill_field_matches", []),
        }

    @staticmethod
    def _service_payload(snapshot) -> dict[str, Any]:
        service = snapshot.services[0] if snapshot.services else {}
        service_kind = str(service.get("service_kind") or "ODATA")
        runtime_available = service.get("runtime_available", True)
        odata_runtime_available = service.get(
            "odata_runtime_available",
            runtime_available is not False and service_kind != "CDS_VIEW_ONLY",
        )
        return {
            "service_name": snapshot.service_name,
            "service_kind": service_kind,
            "base_path": service.get("base_path", ""),
            "runtime_path_template": service.get("runtime_path_template", ""),
            "runtime_available": runtime_available,
            "odata_runtime_available": odata_runtime_available,
            "runtime_notes": service.get("runtime_notes", ""),
        }

    @staticmethod
    def _route_payload(route_decision: ApiRouteDecision | None) -> dict[str, Any]:
        if route_decision is None:
            return {}
        return {
            "resolved_user_input": route_decision.resolved_user_input,
            "intent_summary": route_decision.intent_summary,
            "business_domain": route_decision.business_domain,
            "business_object": route_decision.business_object,
            "selected_apis": [
                {"service_name": item.service_name, "confidence": item.confidence, "reason": item.reason}
                for item in route_decision.selected_apis
            ],
        }

    def _expand_candidate_entities(
        self,
        snapshot,
        candidate_fields: list[dict[str, Any]],
        document_entities: set[str],
    ) -> list[str]:
        ordered: list[str] = []

        def add(entity_set: str) -> None:
            if entity_set and entity_set not in ordered:
                ordered.append(entity_set)

        for entity_set in document_entities:
            add(entity_set)
        for field in candidate_fields:
            add(str(field.get("entity_set", "")))

        fields_by_entity: dict[str, set[str]] = {}
        for field in snapshot.fields:
            fields_by_entity.setdefault(str(field.get("entity_set", "")), set()).add(str(field.get("field_name", "")))

        for entity_set in list(ordered):
            entity = self._lookup_entity(snapshot, entity_set)
            if not entity:
                continue
            bridge_fields = set(entity.get("key_fields", []) or [])
            bridge_fields.update(entity.get("default_select_fields", []) or [])
            bridge_fields.update(fields_by_entity.get(entity_set, set()) & {"AddressID", "BusinessPartner"})
            for other_entity, other_fields in fields_by_entity.items():
                if other_entity in ordered:
                    continue
                if bridge_fields & other_fields:
                    add(other_entity)
                if len(ordered) >= self.max_candidate_entities:
                    break
            if len(ordered) >= self.max_candidate_entities:
                break
        return ordered or [str(entity.get("entity_set", "")) for entity in snapshot.entities[: self.max_candidate_entities]]

    def _entity_payload(
        self,
        snapshot,
        entity_set: str,
        candidate_fields: list[dict[str, Any]],
        function_import_map: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        entity = self._lookup_entity(snapshot, entity_set)
        if not entity:
            return {}
        function_import = (function_import_map or {}).get(entity_set)
        candidate_field_names = {
            str(field.get("field_name", ""))
            for field in candidate_fields
            if field.get("entity_set") == entity_set
        }
        fields = []
        for field in self._get_entity_fields(snapshot, entity_set):
            field_name = str(field.get("field_name", ""))
            if (
                field_name in candidate_field_names
                or field_name in set(entity.get("key_fields", []) or [])
                or field_name in set(entity.get("default_select_fields", []) or [])
                or self._is_business_status_field(field)
            ):
                fields.append(self._field_payload(field, 0.0))
            if len(fields) >= 64:
                break
        return {
            "service_name": entity.get("service_name", snapshot.service_name),
            "entity_set": entity_set,
            "kind": "function_import" if function_import else "entity_set",
            "description": entity.get("description", ""),
            "entity_type": entity.get("entity_type", ""),
            "key_fields": entity.get("key_fields", []),
            "default_select_fields": entity.get("default_select_fields", []),
            "supports_filter": False if function_import else entity.get("supports_filter", True),
            "supports_top": False if function_import else entity.get("supports_top", True),
            "supported_methods": entity.get("supported_methods", ["GET"]),
            "fields": fields,
            "function_parameters": (function_import or {}).get("parameters", []),
            "function_return_type": (function_import or {}).get("return_type", ""),
            "function_return_fields": (function_import or {}).get("return_fields", []),
        }

    @staticmethod
    def _build_join_hints(snapshot, entity_set_scope: set[str]) -> list[dict[str, Any]]:
        by_field: dict[str, list[str]] = {}
        for field in snapshot.fields:
            entity_set = str(field.get("entity_set", ""))
            field_name = str(field.get("field_name", ""))
            if not entity_set or not field_name:
                continue
            if entity_set_scope and entity_set not in entity_set_scope:
                continue
            by_field.setdefault(field_name, []).append(entity_set)
        hints = []
        for field_name, entities in by_field.items():
            unique_entities = list(dict.fromkeys(entities))
            if len(unique_entities) >= 2:
                hints.append({"field_name": field_name, "entity_sets": unique_entities[:12]})
        hints.sort(key=lambda item: (-len(item["entity_sets"]), item["field_name"]))
        return hints[:100]

    @staticmethod
    def _build_relation_hints(snapshot, entity_set_scope: set[str]) -> list[dict[str, Any]]:
        hints = []
        for relation in [*(snapshot.entity_graph or []), *(snapshot.relations or [])]:
            from_entity = str(relation.get("from_entity_set", ""))
            to_entity = str(relation.get("to_entity_set", ""))
            if entity_set_scope and from_entity not in entity_set_scope and to_entity not in entity_set_scope:
                continue
            hints.append(
                {
                    "from_entity_set": from_entity,
                    "to_entity_set": to_entity,
                    "from_field": relation.get("from_field", ""),
                    "to_field": relation.get("to_field", ""),
                    "navigation_name": relation.get("navigation_name", ""),
                    "description": relation.get("description", ""),
                    "confidence": relation.get("confidence", ""),
                }
            )
        return hints[:100]

    @staticmethod
    def _score_field(query: str, field: dict[str, Any]) -> float:
        normalized_query = SchemaContextProvider._normalize(query)
        query_tokens = set(SchemaContextProvider._tokens(normalized_query))
        field_name = str(field.get("field_name", "") or "")
        aliases = [
            field_name,
            SchemaContextProvider._split_camel(field_name),
            str(field.get("entity_set", "") or ""),
            str(field.get("label", "") or ""),
            str(field.get("description", "") or ""),
            *[str(item or "") for item in field.get("business_aliases", []) or []],
        ]
        score = 0.0
        for alias in aliases:
            normalized_alias = SchemaContextProvider._normalize(alias)
            if not normalized_alias:
                continue
            compact_alias = normalized_alias.replace(" ", "")
            compact_query = normalized_query.replace(" ", "")
            if normalized_alias in normalized_query or compact_alias in compact_query:
                score += 24.0
            alias_tokens = set(SchemaContextProvider._tokens(normalized_alias))
            score += len(query_tokens & alias_tokens) * 5.0
            for token in query_tokens:
                best = max((SequenceMatcher(None, token, alias_token).ratio() for alias_token in alias_tokens), default=0.0)
                if best >= 0.82:
                    score += best * 3.0
        return score

    @staticmethod
    def _field_payload(field: dict[str, Any], score: float) -> dict[str, Any]:
        return {
            "service_name": field.get("service_name", ""),
            "entity_set": field.get("entity_set", ""),
            "field_name": field.get("field_name", ""),
            "label": field.get("label", ""),
            "description": field.get("description", "") or field.get("quickinfo", ""),
            "business_aliases": field.get("business_aliases", [])[:8],
            "data_type": field.get("data_type", ""),
            "filterable": field.get("filterable", False),
            "score": round(score, 3),
        }

    @staticmethod
    def _feedback_field_matches(
        snapshot,
        feedback_memories: list[dict[str, Any]],
        route_decision: ApiRouteDecision | None = None,
    ) -> list[dict[str, Any]]:
        if not feedback_memories:
            return []

        by_qualified: dict[tuple[str, str], dict[str, Any]] = {}
        fields = list(snapshot.fields or [])
        route_text = " ".join(
            [
                str((route_decision.business_object if route_decision else "") or ""),
                str((route_decision.intent_summary if route_decision else "") or ""),
                str((route_decision.business_domain if route_decision else "") or ""),
            ]
        )
        normalized_route_text = SchemaContextProvider._normalize(route_text)

        for memory in feedback_memories:
            preferred_fields = [
                str(item or "").strip()
                for item in memory.get("preferred_fields", []) or []
                if str(item or "").strip()
            ]
            if not preferred_fields:
                continue
            preferred_entities = [
                str(item or "").strip()
                for item in memory.get("preferred_entities", []) or []
                if str(item or "").strip()
            ]
            for preferred_field in preferred_fields:
                for field in fields:
                    entity_set = str(field.get("entity_set", "") or "")
                    field_name = str(field.get("field_name", "") or "")
                    if not entity_set or not field_name:
                        continue
                    if not SchemaContextProvider._preferred_field_matches(preferred_field, entity_set, field_name):
                        continue
                    score = 80.0 + SchemaContextProvider._feedback_entity_affinity(
                        entity_set,
                        preferred_entities,
                        normalized_route_text,
                    )
                    key = (entity_set, field_name)
                    existing = by_qualified.get(key)
                    if existing is not None and float(existing.get("score", 0.0)) >= score:
                        continue
                    by_qualified[key] = {
                        "memory_case_id": memory.get("case_id", ""),
                        "memory_type": memory.get("memory_type", ""),
                        "preferred_field": preferred_field,
                        "matched_field": f"{entity_set}.{field_name}",
                        "entity_set": entity_set,
                        "field_name": field_name,
                        "reason": "preferred field from feedback memory matched current API schema",
                        "score": score,
                    }

        return sorted(
            by_qualified.values(),
            key=lambda item: (-float(item.get("score", 0.0)), str(item.get("matched_field", ""))),
        )

    @staticmethod
    def _preferred_field_matches(preferred_field: str, entity_set: str, field_name: str) -> bool:
        normalized_preferred = SchemaContextProvider._normalize(preferred_field).replace(" ", "")
        normalized_field = SchemaContextProvider._normalize(field_name).replace(" ", "")
        normalized_qualified = SchemaContextProvider._normalize(f"{entity_set}.{field_name}").replace(" ", "")
        return normalized_preferred in {normalized_field, normalized_qualified}

    @staticmethod
    def _feedback_entity_affinity(
        entity_set: str,
        preferred_entities: list[str],
        normalized_route_text: str,
    ) -> float:
        normalized_entity = SchemaContextProvider._normalize(entity_set).replace(" ", "")
        score = 0.0
        for preferred_entity in preferred_entities:
            normalized_preferred = SchemaContextProvider._normalize(preferred_entity).replace(" ", "")
            if normalized_preferred and normalized_preferred in normalized_entity:
                score += 15.0
        if normalized_route_text:
            for token in SchemaContextProvider._tokens(normalized_route_text):
                normalized_token = SchemaContextProvider._normalize(token).replace(" ", "")
                if normalized_token and normalized_token in normalized_entity:
                    score += 5.0
        return score

    @staticmethod
    def _skill_field_matches(snapshot, api_skill: dict[str, Any]) -> list[dict[str, Any]]:
        content = "\n".join(
            [
                str(api_skill.get("summary") or ""),
                str(api_skill.get("content") or ""),
            ]
        )
        if not content.strip():
            return []

        available = {
            (str(field.get("entity_set", "")), str(field.get("field_name", "")))
            for field in snapshot.fields or []
        }
        by_qualified: dict[tuple[str, str], dict[str, Any]] = {}
        field_ref_pattern = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z][A-Za-z0-9_]*)\b")
        for line_number, line in enumerate(content.splitlines(), start=1):
            for entity_set, field_name in field_ref_pattern.findall(line):
                key = (entity_set, field_name)
                if key not in available:
                    continue
                existing = by_qualified.get(key)
                if existing is not None:
                    continue
                by_qualified[key] = {
                    "matched_field": f"{entity_set}.{field_name}",
                    "entity_set": entity_set,
                    "field_name": field_name,
                    "line_number": line_number,
                    "reason": "field referenced by API skill matched current API schema",
                    "score": 55.0,
                }

        return sorted(
            by_qualified.values(),
            key=lambda item: (-float(item.get("score", 0.0)), str(item.get("matched_field", ""))),
        )

    @staticmethod
    def _is_business_status_field(field: dict[str, Any]) -> bool:
        text = " ".join(
            [
                str(field.get("field_name", "") or ""),
                str(field.get("label", "") or ""),
                str(field.get("description", "") or ""),
                " ".join(str(item or "") for item in field.get("business_aliases", []) or []),
            ]
        ).lower()
        positive_markers = {
            "iscompletelydelivered",
            "completely delivered",
            "goodsreceipt",
            "goods receipt",
            "receivedquantity",
            "received quantity",
            "openquantity",
            "open quantity",
            "completion",
            "completed",
            "交货已完成",
            "收货",
        }
        negative_markers = {
            "deliveryaddress",
            "delivery address",
            "deliverydate",
            "delivery date",
            "deliverytime",
            "delivery time",
            "deliveryservice",
            "planned delivery",
            "postal",
            "address",
        }
        return any(marker in text for marker in positive_markers) and not any(
            marker in text for marker in negative_markers
        )

    @staticmethod
    def _document_payload(documents: list[RetrievedDocument]) -> list[dict[str, Any]]:
        return [
            {
                "source": document.source,
                "title": document.title,
                "score": document.score,
                "metadata": {
                    "entity_set": (document.metadata or {}).get("entity_set", ""),
                    "field_name": (document.metadata or {}).get("field_name", ""),
                    "path_id": (document.metadata or {}).get("path_id", ""),
                },
            }
            for document in documents[:16]
        ]

    @staticmethod
    def _entity_sets_from_documents(documents: list[RetrievedDocument]) -> set[str]:
        results: set[str] = set()
        for document in documents:
            metadata = document.metadata or {}
            entity_set = str(metadata.get("mapped_entity_set") or metadata.get("entity_set") or "")
            if not entity_set and "." in document.title:
                entity_set = document.title.split(".", 1)[0]
            if entity_set:
                results.add(entity_set)
        return results

    @staticmethod
    def _field_refs_from_documents(documents: list[RetrievedDocument]) -> dict[tuple[str, str], float]:
        results: dict[tuple[str, str], float] = {}
        for document in documents:
            metadata = document.metadata or {}
            entity_set = str(metadata.get("entity_set") or "")
            field_name = str(metadata.get("field_name") or "")
            if entity_set and field_name:
                results[(entity_set, field_name)] = max(results.get((entity_set, field_name), 0.0), float(document.score or 0.0))
        return results

    @staticmethod
    def _lookup_entity(snapshot, entity_set: str) -> dict[str, Any] | None:
        return next((entity for entity in snapshot.entities if entity.get("entity_set") == entity_set), None)

    @staticmethod
    def _get_entity_fields(snapshot, entity_set: str) -> list[dict[str, Any]]:
        return [field for field in snapshot.fields if field.get("entity_set") == entity_set]

    @staticmethod
    def _split_camel(text: str) -> str:
        return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))

    @staticmethod
    def _normalize(text: str) -> str:
        value = str(text or "").lower()
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        return re.sub(r"[^a-z0-9@\.\-\u4e00-\u9fff]+", " ", value).strip()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9_@.\-]+|[\u4e00-\u9fff]{1,}", text or "")
