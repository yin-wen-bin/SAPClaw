from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from sap_odata_agent.domain.models import QueryConstraints, RetrievedDocument
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner


class LlmSchemaReranker:
    """Broaden schema recall and let the LLM rank fields by business meaning."""

    def __init__(
        self,
        index_root: str = "data/index",
        service_name: str = "API_BUSINESS_PARTNER",
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
        llm_first: bool = True,
    ) -> None:
        self.loader = LocalIndexLoader(index_root=index_root)
        self.service_name = service_name
        self.llm_client = llm_client
        self.enabled = enabled
        self.llm_first = llm_first

    def rerank(
        self,
        query: str,
        constraints: QueryConstraints,
        retrieved_documents: list[RetrievedDocument],
        feedback_memories: list[dict[str, Any]] | None = None,
        top_k: int = 80,
        force_broad_schema: bool = False,
    ) -> dict[str, Any]:
        candidates = self._build_candidate_pool(query, constraints, retrieved_documents, top_k=top_k)
        llm_first_active = self.enabled and self.llm_client is not None and self.llm_first
        grounding_reason = (
            "critic_requested_broad_schema_grounding"
            if force_broad_schema
            else "llm_first_broad_schema_grounding"
            if llm_first_active
            else self._broad_grounding_reason(query, constraints, candidates)
        )
        if grounding_reason:
            broad_candidates = (
                self._build_llm_first_candidate_pool(query, constraints, retrieved_documents, top_k=max(top_k, 220))
                if llm_first_active
                else self._build_broad_candidate_pool(
                    query,
                    constraints,
                    retrieved_documents,
                    top_k=max(top_k, 180),
                )
            )
            candidates = (
                self._merge_candidate_pools(broad_candidates, candidates, top_k=max(top_k, 180))
                if llm_first_active
                else self._merge_candidate_pools(candidates, broad_candidates, top_k=max(top_k, 180))
            )
        if not self.enabled or self.llm_client is None or not candidates:
            return {
                "enabled": False,
                "accepted": False,
                "reason": "llm_unavailable",
                "ranked_fields": candidates[:24],
                "answer_fields": self._fallback_answer_fields(candidates, constraints),
                "filter_fields": self._fallback_filter_fields(candidates, constraints),
                "grounding_mode": "broad_schema" if grounding_reason else "local_candidates",
                "grounding_reason": grounding_reason,
            }

        try:
            raw = self.llm_client.complete_json(
                self._system_prompt(),
                self._user_prompt(query, constraints, candidates, feedback_memories),
                max_tokens=1200,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
        except Exception as exc:
            return {
                "enabled": True,
                "accepted": False,
                "reason": f"client_error:{exc}",
                "ranked_fields": candidates[:24],
                "answer_fields": list(constraints.target_field_concepts or []),
                "filter_fields": list(constraints.filter_concepts or []),
                "grounding_mode": "broad_schema" if grounding_reason else "local_candidates",
                "grounding_reason": grounding_reason,
            }

        ranked_fields = self._materialize_ranked_fields(parsed, candidates)
        return {
            "enabled": True,
            "accepted": True,
            "ranked_fields": ranked_fields or candidates[:24],
            "answer_fields": self._field_names(parsed.get("answer_fields", []), candidates),
            "filter_fields": self._field_names(parsed.get("filter_fields", []), candidates),
            "reason": parsed.get("reason", ""),
            "grounding_mode": "broad_schema" if grounding_reason else "local_candidates",
            "grounding_reason": grounding_reason,
        }

    def _build_candidate_pool(
        self,
        query: str,
        constraints: QueryConstraints,
        retrieved_documents: list[RetrievedDocument],
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            snapshot = self.loader.load(self.service_name)
        except FileNotFoundError:
            return self._candidate_fields_from_documents(retrieved_documents)

        document_bias: dict[tuple[str, str], float] = {}
        for document in retrieved_documents:
            meta = document.metadata or {}
            entity_set = str(meta.get("entity_set", "") or "")
            field_name = str(meta.get("field_name", "") or "")
            if entity_set and field_name:
                document_bias[(entity_set, field_name)] = max(document_bias.get((entity_set, field_name), 0.0), document.score)

        scored: list[tuple[float, dict[str, Any]]] = []
        for field in snapshot.fields:
            score = self._score_field(query, constraints, field)
            score += min(document_bias.get((field.get("entity_set", ""), field.get("field_name", "")), 0.0), 20.0) * 0.6
            if score <= 0:
                continue
            scored.append((score, self._field_payload(field, score)))

        for item in self._candidate_fields_from_documents(retrieved_documents):
            scored.append((float(item.get("score", 0.0)) + 5.0, item))

        scored.sort(key=lambda item: item[0], reverse=True)
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for _, item in scored:
            key = (str(item.get("entity_set", "")), str(item.get("field_name", "")))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= top_k:
                break
        return deduped

    def _build_broad_candidate_pool(
        self,
        query: str,
        constraints: QueryConstraints,
        retrieved_documents: list[RetrievedDocument],
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            snapshot = self.loader.load(self.service_name)
        except FileNotFoundError:
            return []

        relevant_entities = self._relevant_entity_sets(snapshot, constraints, retrieved_documents)
        scored: list[tuple[float, dict[str, Any]]] = []
        for field in snapshot.fields:
            entity_set = str(field.get("entity_set", "") or "")
            if entity_set not in relevant_entities:
                continue
            score = self._score_field(query, constraints, field)
            entity = self._entity_by_set(snapshot, entity_set)
            field_name = str(field.get("field_name", "") or "")
            if field_name in set(entity.get("key_fields", []) or []):
                score += 3.0
            if field_name in set(entity.get("default_select_fields", []) or []):
                score += 2.0
            if self._is_object_identity_field(field_name, constraints.target_object):
                score += 4.0
            if entity_set in self._entity_sets_from_documents(retrieved_documents):
                score += 2.5
            scored.append((score, self._field_payload(field, score)))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for _, item in scored:
            key = (str(item.get("entity_set", "")), str(item.get("field_name", "")))
            if key in seen:
                continue
            seen.add(key)
            results.append({**item, "source": "schema-broad-grounding"})
            if len(results) >= top_k:
                break
        return results

    def _build_llm_first_candidate_pool(
        self,
        query: str,
        constraints: QueryConstraints,
        retrieved_documents: list[RetrievedDocument],
        top_k: int,
    ) -> list[dict[str, Any]]:
        try:
            snapshot = self.loader.load(self.service_name)
        except FileNotFoundError:
            return []

        document_entities = self._entity_sets_from_documents(retrieved_documents)
        query_text = self._normalize(query)
        scored: list[tuple[float, dict[str, Any]]] = []
        for field in snapshot.fields:
            entity_set = str(field.get("entity_set", "") or "")
            field_name = str(field.get("field_name", "") or "")
            if not entity_set or not field_name:
                continue
            score = self._score_field(query, constraints, field)
            entity = self._entity_by_set(snapshot, entity_set)
            if field_name in set(entity.get("key_fields", []) or []):
                score += 2.0
            if field_name in set(entity.get("default_select_fields", []) or []):
                score += 1.0
            if entity_set in document_entities:
                score += 4.0
            if self._is_object_identity_field(field_name, constraints.target_object):
                score += 5.0
            if constraints.target_object and self._entity_matches_target_object(entity_set, field_name, constraints.target_object):
                score += 1.5
            if query_text and self._normalize(entity_set) in query_text:
                score += 2.0
            scored.append((score, {**self._field_payload(field, score), "source": "llm-first-schema-recall"}))

        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for _, item in scored:
            key = (str(item.get("entity_set", "")), str(item.get("field_name", "")))
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= top_k:
                break
        return results

    def _relevant_entity_sets(
        self,
        snapshot,
        constraints: QueryConstraints,
        retrieved_documents: list[RetrievedDocument],
    ) -> set[str]:
        document_entities = self._entity_sets_from_documents(retrieved_documents)
        object_field = self._object_field_name(constraints.target_object)
        target_object = constraints.target_object or ""
        relevant: set[str] = set(document_entities)
        for entity in snapshot.entities:
            entity_set = str(entity.get("entity_set", "") or "")
            if not entity_set:
                continue
            fields = {
                str(field.get("field_name", "") or "")
                for field in snapshot.fields
                if field.get("entity_set") == entity_set
            }
            if object_field and object_field in fields and not self._entity_has_competing_primary_marker(entity_set, target_object):
                relevant.add(entity_set)
            elif object_field and object_field in entity_set and not self._entity_has_competing_primary_marker(entity_set, target_object):
                relevant.add(entity_set)
        if relevant:
            return relevant
        return {str(entity.get("entity_set", "") or "") for entity in snapshot.entities if entity.get("entity_set")}

    @staticmethod
    def _entity_sets_from_documents(documents: list[RetrievedDocument]) -> set[str]:
        results: set[str] = set()
        for document in documents:
            meta = document.metadata or {}
            entity_set = str(meta.get("mapped_entity_set", "") or meta.get("entity_set", "") or "")
            if not entity_set and "." in document.title:
                entity_set = document.title.split(".", 1)[0]
            if entity_set:
                results.add(entity_set)
        return results

    @staticmethod
    def _entity_by_set(snapshot, entity_set: str) -> dict[str, Any]:
        return next((entity for entity in snapshot.entities if entity.get("entity_set") == entity_set), {})

    @classmethod
    def _is_object_identity_field(cls, field_name: str, target_object: str | None) -> bool:
        return bool(target_object and field_name == cls._object_field_name(target_object))

    @staticmethod
    def _object_field_name(target_object: str | None) -> str:
        return {
            "supplier": "Supplier",
            "customer": "Customer",
            "business_partner": "BusinessPartner",
        }.get(target_object or "", "")

    @staticmethod
    def _entity_has_competing_primary_marker(entity_set: str, target_object: str) -> bool:
        normalized = (entity_set or "").replace("_", "").lower()
        markers = {
            "supplier": {"target": ("supplier",), "competing": ("customer", "cust")},
            "customer": {"target": ("customer", "cust"), "competing": ("supplier",)},
            "business_partner": {"target": ("businesspartner", "bp"), "competing": ()},
        }.get(target_object)
        if not markers:
            return False
        if any(marker in normalized for marker in markers["target"]):
            return False
        return any(marker in normalized for marker in markers["competing"])

    @classmethod
    def _entity_matches_target_object(cls, entity_set: str, field_name: str, target_object: str) -> bool:
        object_field = cls._object_field_name(target_object)
        if not object_field:
            return False
        return field_name == object_field or (
            object_field in entity_set and not cls._entity_has_competing_primary_marker(entity_set, target_object)
        )

    @staticmethod
    def _merge_candidate_pools(
        primary: list[dict[str, Any]],
        secondary: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in [*primary, *secondary]:
            key = (str(item.get("entity_set", "")), str(item.get("field_name", "")))
            if not key[0] or not key[1] or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= top_k:
                break
        return merged

    def _broad_grounding_reason(
        self,
        query: str,
        constraints: QueryConstraints,
        candidates: list[dict[str, Any]],
    ) -> str:
        if not candidates:
            return "candidate_pool_empty"
        if (
            not constraints.target_field_concepts
            and constraints.target_object
            and constraints.filter_values
            and constraints.query_shape.value in {"single_fact", "list_query", "boolean_check"}
            and self._looks_like_attribute_question(query)
        ):
            return "target_field_missing_after_local_recall"
        non_identity = [
            item
            for item in candidates[:12]
            if not self._is_object_identity_field(str(item.get("field_name", "")), constraints.target_object)
        ]
        if (
            constraints.target_object
            and constraints.filter_values
            and len(non_identity) <= 2
            and self._looks_like_attribute_question(query)
        ):
            return "local_recall_identity_heavy"
        return ""

    @staticmethod
    def _looks_like_attribute_question(query: str) -> bool:
        text = str(query or "").lower()
        if any(marker in text for marker in ("\u7684", "what", "which", "where", "how", "?")):
            return True
        return any(marker in text for marker in ("\u54ea\u4e9b", "\u4ec0\u4e48", "\u591a\u5c11", "\u662f\u5426"))

    @staticmethod
    def _candidate_fields_from_documents(documents: list[RetrievedDocument]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for document in documents:
            meta = document.metadata or {}
            if not meta.get("entity_set") or not meta.get("field_name"):
                continue
            results.append(
                {
                    "entity_set": meta.get("entity_set", ""),
                    "field_name": meta.get("field_name", ""),
                    "label": meta.get("label", ""),
                    "description": meta.get("description", ""),
                    "business_aliases": meta.get("business_aliases", []),
                    "score": round(document.score, 3),
                    "source": document.source,
                }
            )
        return results

    @staticmethod
    def _field_payload(field: dict[str, Any], score: float) -> dict[str, Any]:
        return {
            "entity_set": field.get("entity_set", ""),
            "field_name": field.get("field_name", ""),
            "label": field.get("label", ""),
            "description": field.get("description", "") or field.get("label", ""),
            "business_aliases": field.get("business_aliases", [])[:8],
            "filterable": field.get("filterable", False),
            "score": round(score, 3),
            "source": "schema-broad-recall",
        }

    def _score_field(self, query: str, constraints: QueryConstraints, field: dict[str, Any]) -> float:
        normalized_query = self._normalize(query)
        query_tokens = set(self._tokens(normalized_query))
        field_name = str(field.get("field_name", "") or "")
        entity_set = str(field.get("entity_set", "") or "")
        aliases = [
            field_name,
            self._split_camel(field_name),
            entity_set,
            self._split_camel(entity_set),
            str(field.get("label", "") or ""),
            str(field.get("description", "") or ""),
            *[str(item or "") for item in field.get("business_aliases", []) or []],
        ]
        score = 0.0
        for alias in aliases:
            normalized_alias = self._normalize(alias)
            if not normalized_alias:
                continue
            compact_alias = normalized_alias.replace(" ", "")
            compact_query = normalized_query.replace(" ", "")
            if normalized_alias in normalized_query or compact_alias in compact_query:
                score += 20.0
            alias_tokens = set(self._tokens(normalized_alias))
            score += len(query_tokens & alias_tokens) * 4.0
            for token in query_tokens:
                best = max((SequenceMatcher(None, token, alias_token).ratio() for alias_token in alias_tokens), default=0.0)
                if best >= 0.84:
                    score += 2.5 * best

        object_field = self._object_field_name(constraints.target_object)
        if object_field and (object_field in entity_set or field_name == object_field):
            score += 2.5
        if field_name in set(constraints.target_field_concepts or []):
            score += 16.0
        if field_name in set(constraints.filter_concepts or []):
            score += 10.0
        return score

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You rank SAP OData metadata fields for a user question. "
            "Only choose from candidate_fields. Return JSON only."
        )

    @staticmethod
    def _user_prompt(
        query: str,
        constraints: QueryConstraints,
        candidates: list[dict[str, Any]],
        feedback_memories: list[dict[str, Any]] | None,
    ) -> str:
        example = {
            "answer_fields": [
                {"entity_set": "A_RelevantEntity", "field_name": "RequestedField", "confidence": 0.94}
            ],
            "filter_fields": [
                {"entity_set": "A_RelevantEntity", "field_name": "IdentifierOrFilterField", "confidence": 0.88}
            ],
            "ranked_fields": [
                {
                    "entity_set": "A_RelevantEntity",
                    "field_name": "RequestedField",
                    "role": "answer",
                    "confidence": 0.94,
                    "reason": "The field label and description match the user's requested business meaning.",
                }
            ],
            "reason": "Selected fields by business meaning.",
        }
        payload = {
            "query": query,
            "constraints": {
                "target_object": constraints.target_object,
                "target_field_concepts": constraints.target_field_concepts,
                "filter_concepts": constraints.filter_concepts,
                "filter_values": constraints.filter_values,
                "query_shape": constraints.query_shape.value,
                "cardinality": constraints.cardinality.value,
            },
            "candidate_fields": candidates,
            "feedback_memories": feedback_memories or [],
        }
        return (
            f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Rank fields by semantic fit. Treat current constraints as weak hints, not as ground truth. "
            "Prefer the user's wording and candidate metadata labels/descriptions when they disagree with local constraints. "
            "Use answer_fields for what the user wants returned. "
            "Use filter_fields for object identifiers or attribute filters. "
            "If terms are ambiguous, rank the best candidates but explain the ambiguity in reason. "
            "Return JSON with this shape:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _materialize_ranked_fields(parsed: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key = {
            (str(item.get("entity_set", "")), str(item.get("field_name", ""))): item
            for item in candidates
        }
        ranked: list[dict[str, Any]] = []
        for item in parsed.get("ranked_fields", []):
            if not isinstance(item, dict):
                continue
            key = (str(item.get("entity_set", "")), str(item.get("field_name", "")))
            base = by_key.get(key)
            if base is None:
                continue
            ranked.append(
                {
                    **base,
                    "llm_role": item.get("role", ""),
                    "llm_confidence": item.get("confidence", 0.0),
                    "llm_reason": item.get("reason", ""),
                }
            )
        return ranked

    @staticmethod
    def _field_names(items: Any, candidates: list[dict[str, Any]]) -> list[str]:
        known = {str(item.get("field_name", "")) for item in candidates}
        results: list[str] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("field_name", "")).strip()
            if field_name and field_name in known and field_name not in results:
                results.append(field_name)
        return results

    @staticmethod
    def _fallback_answer_fields(candidates: list[dict[str, Any]], constraints: QueryConstraints) -> list[str]:
        existing = [field for field in constraints.target_field_concepts if any(item.get("field_name") == field for item in candidates)]
        if existing:
            return existing
        return [str(item.get("field_name", "")) for item in candidates[:3] if item.get("field_name")]

    @staticmethod
    def _fallback_filter_fields(candidates: list[dict[str, Any]], constraints: QueryConstraints) -> list[str]:
        existing = [field for field in constraints.filter_concepts if any(item.get("field_name") == field for item in candidates)]
        return existing

    @staticmethod
    def _split_camel(text: str) -> str:
        return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))

    @staticmethod
    def _normalize(text: str) -> str:
        value = str(text or "").lower()
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value).strip()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", text or "")
