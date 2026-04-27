from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from sap_odata_agent.domain.models import ApiRouteDecision, RetrievedDocument
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
        snapshot = self.loader.load(service_name)
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
            self._entity_payload(snapshot, entity_set, candidate_fields)
            for entity_set in candidate_entities[: self.max_candidate_entities]
        ]
        entities = [item for item in entities if item]
        entity_set_scope = {item["entity_set"] for item in entities}

        return {
            "service_name": service_name,
            "route_decision": self._route_payload(route_decision),
            "entities": entities,
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
            "entity_count": len(schema_context.get("entities", [])),
            "candidate_field_count": len(schema_context.get("candidate_fields", [])),
            "join_hint_count": len(schema_context.get("join_hints", [])),
            "relation_count": len(schema_context.get("relations", [])),
            "top_entities": [item.get("entity_set") for item in schema_context.get("entities", [])[:8]],
            "top_fields": [
                f"{item.get('entity_set')}.{item.get('field_name')}"
                for item in schema_context.get("candidate_fields", [])[:16]
            ],
            "available_fields": available_fields,
            "feedback_field_matches": schema_context.get("feedback_field_matches", []),
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

    def _entity_payload(self, snapshot, entity_set: str, candidate_fields: list[dict[str, Any]]) -> dict[str, Any]:
        entity = self._lookup_entity(snapshot, entity_set)
        if not entity:
            return {}
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
            "entity_set": entity_set,
            "description": entity.get("description", ""),
            "entity_type": entity.get("entity_type", ""),
            "key_fields": entity.get("key_fields", []),
            "default_select_fields": entity.get("default_select_fields", []),
            "supports_filter": entity.get("supports_filter", True),
            "supported_methods": entity.get("supported_methods", ["GET"]),
            "fields": fields,
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
