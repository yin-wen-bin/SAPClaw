from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from sap_odata_agent.domain.models import RetrievedContext, RetrievedDocument
from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader


class LocalDocRetriever:
    """Hybrid local retriever backed by merged runtime metadata and OpenAPI indexes."""

    OBJECT_ALIASES = {
        "Supplier": ["supplier", "vendor", "供应商"],
        "Customer": ["customer", "客户"],
        "BusinessPartner": ["business partner", "bp", "业务伙伴"],
    }
    STOP_TERMS = {
        "查询",
        "信息",
        "基本",
        "数据",
        "查看",
        "获取",
        "显示",
        "一下",
        "帮我",
        "帮忙",
        "内容",
        "详情",
        "列表",
        "的",
    }

    def __init__(self, index_root: str = "data/index", service_name: str = "API_BUSINESS_PARTNER") -> None:
        self.index_root = Path(index_root)
        self.service_name = service_name
        self.loader = LocalIndexLoader(index_root=index_root)
        self._vector_cache: dict[str, tuple[Counter[str], float]] = {}

    def retrieve(self, query: str, top_k: int = 5) -> RetrievedContext:
        try:
            snapshot = self.loader.load(self.service_name)
        except FileNotFoundError as exc:
            return RetrievedContext(
                documents=[
                RetrievedDocument(
                    source="local-index",
                    title="index-missing",
                    content=str(exc),
                    score=0.0,
                    metadata={},
                )
            ],
            examples=[],
            )

        search_terms = self._build_search_terms(query)
        query_vector = self._build_sparse_vector(query)
        candidates: list[RetrievedDocument] = []
        service_docs = self._search_service(snapshot.services, search_terms)
        business_term_docs = self._search_business_terms(snapshot.business_terms, search_terms)
        entity_docs = self._search_entities(snapshot.entities, search_terms)
        field_docs = self._search_fields(snapshot.fields, search_terms)
        field_exact_docs = self._search_exact_field_aliases(snapshot.fields, query)
        field_fuzzy_docs = self._search_fuzzy_field_aliases(snapshot.fields, query)
        lookup_path_docs = self._search_lookup_paths(snapshot.lookup_paths, search_terms)
        vector_docs = self._search_vector_documents(snapshot.vector_documents, query_vector)
        chunk_docs = self._search_doc_chunks(snapshot.doc_chunks, search_terms)
        entity_hint_docs = self._build_entity_hints(
            snapshot.entities,
            entity_docs,
            field_exact_docs + field_fuzzy_docs + field_docs + vector_docs,
            business_term_docs,
            lookup_path_docs,
        )

        candidates.extend(entity_hint_docs)
        candidates.extend(service_docs)
        candidates.extend(business_term_docs)
        candidates.extend(lookup_path_docs)
        candidates.extend(entity_docs)
        candidates.extend(field_exact_docs)
        candidates.extend(field_fuzzy_docs)
        candidates.extend(field_docs)
        candidates.extend(vector_docs)
        candidates.extend(chunk_docs)

        ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
        deduped: list[RetrievedDocument] = []
        seen: set[tuple[str, str]] = set()
        for item in ranked:
            key = (item.source, item.title)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        deduped = self._ensure_priority_sources(deduped, top_k)
        deduped = deduped[:top_k]

        if not deduped:
            deduped.append(
                RetrievedDocument(
                    source="local-index",
                    title="no-match",
                    content=f"No local index match found for query: {query}",
                    score=0.0,
                    metadata={},
                )
            )

        return RetrievedContext(documents=deduped, examples=[])

    @staticmethod
    def _ensure_priority_sources(documents: list[RetrievedDocument], top_k: int) -> list[RetrievedDocument]:
        if len(documents) <= top_k:
            return documents
        priority_limits = {
            "field-exact": min(top_k, max(6, top_k - 1)),
            "field-fuzzy": min(top_k, max(4, top_k // 2)),
            "lookup-path": 3,
            "lookup-path-vector": 3,
            "field-vector": 3,
        }
        selected: list[RetrievedDocument] = []
        selected_keys: set[tuple[str, str]] = set()

        for source, limit in priority_limits.items():
            candidates = [doc for doc in documents if doc.source == source][:limit]
            for candidate in candidates:
                key = (candidate.source, candidate.title)
                if key in selected_keys:
                    continue
                selected.append(candidate)
                selected_keys.add(key)

        for doc in documents:
            key = (doc.source, doc.title)
            if key in selected_keys:
                continue
            selected.append(doc)
            selected_keys.add(key)
            if len(selected) >= top_k:
                break

        return sorted(selected, key=lambda item: item.score, reverse=True)

    def _search_service(self, services: list[dict], search_terms: list[str]) -> list[RetrievedDocument]:
        results: list[RetrievedDocument] = []
        for service in services:
            text = " ".join(
                [
                    service.get("service_name", ""),
                    service.get("description", ""),
                    " ".join(service.get("entity_sets", [])),
                ]
            )
            score = self._score_text(text, search_terms, base_weight=2.0)
            if score <= 0:
                continue
            results.append(
                RetrievedDocument(
                    source="service",
                    title=service.get("service_name", "unknown-service"),
                    content=service.get("description", ""),
                    score=score,
                    metadata=service,
                )
            )
        return results

    def _search_business_terms(self, business_terms: list[dict], search_terms: list[str]) -> list[RetrievedDocument]:
        results: list[RetrievedDocument] = []
        for alias in business_terms:
            tokens = [alias.get("term", ""), *alias.get("synonyms", []), *alias.get("mapped_fields", [])]
            text = " ".join(tokens + [alias.get("mapped_entity_set", ""), alias.get("mapped_service", "")])
            score = self._score_text(text, search_terms, base_weight=4.0)
            if score <= 0:
                continue
            mapped_fields = ", ".join(alias.get("mapped_fields", []))
            content = (
                f"Business term `{alias.get('term', '')}` maps to entity "
                f"`{alias.get('mapped_entity_set', '')}` in service `{alias.get('mapped_service', '')}`. "
                f"Mapped fields: {mapped_fields or 'n/a'}."
            )
            results.append(
                RetrievedDocument(
                    source="business-term",
                    title=f"{alias.get('term', '')}->{alias.get('mapped_entity_set', '')}",
                    content=content,
                    score=score,
                    metadata=alias,
                )
            )
        return results

    def _search_entities(self, entities: list[dict], search_terms: list[str]) -> list[RetrievedDocument]:
        results: list[RetrievedDocument] = []
        for entity in entities:
            text = " ".join(
                [
                    entity.get("entity_set", ""),
                    entity.get("entity_type", ""),
                    entity.get("description", ""),
                    " ".join(entity.get("key_fields", [])),
                    " ".join(entity.get("default_select_fields", [])),
                ]
            )
            score = self._score_text(text, search_terms, base_weight=3.0)
            if score <= 0:
                continue
            content = (
                f"Entity `{entity.get('entity_set', '')}` in service `{entity.get('service_name', '')}`. "
                f"Keys: {', '.join(entity.get('key_fields', [])) or 'n/a'}. "
                f"Methods: {', '.join(entity.get('supported_methods', [])) or 'GET'}. "
                f"Description: {entity.get('description', '') or 'n/a'}."
            )
            results.append(
                RetrievedDocument(
                    source="entity",
                    title=entity.get("entity_set", "unknown-entity"),
                    content=content,
                    score=score,
                    metadata=entity,
                )
            )
        return results

    def _search_fields(self, fields: list[dict], search_terms: list[str]) -> list[RetrievedDocument]:
        results: list[RetrievedDocument] = []
        for field in fields:
            text = " ".join(
                [
                    field.get("entity_set", ""),
                    field.get("field_name", ""),
                    field.get("label", ""),
                    field.get("description", ""),
                    " ".join(field.get("business_aliases", [])),
                ]
            )
            score = self._score_text(text, search_terms, base_weight=2.5)
            if score <= 0:
                continue
            content = (
                f"Field `{field.get('field_name', '')}` on `{field.get('entity_set', '')}`. "
                f"Type: {field.get('data_type', '') or 'n/a'}. "
                f"Filterable: {field.get('filterable', False)}. "
                f"Sortable: {field.get('sortable', False)}. "
                f"Description: {field.get('description', '') or field.get('label', '') or 'n/a'}."
            )
            results.append(
                RetrievedDocument(
                    source="field",
                    title=f"{field.get('entity_set', '')}.{field.get('field_name', '')}",
                    content=content,
                    score=score,
                    metadata=field,
                )
            )
        return results

    def _search_exact_field_aliases(self, fields: list[dict], query: str) -> list[RetrievedDocument]:
        normalized_query = self._normalize_alias_phrase(query)
        compact_query = normalized_query.replace(" ", "")
        by_alias: dict[str, list[RetrievedDocument]] = {}
        for field in fields:
            for alias, source, base_score in self._field_alias_specs(field):
                normalized_alias = self._normalize_alias_phrase(alias)
                if len(normalized_alias) < 2:
                    continue
                compact_alias = normalized_alias.replace(" ", "")
                if not compact_alias:
                    continue
                if normalized_alias not in normalized_query and compact_alias not in compact_query:
                    continue
                score = base_score + min(len(compact_alias) * 0.25, 3.0)
                content = (
                    f"Exact metadata field match `{field.get('field_name', '')}` on `{field.get('entity_set', '')}`. "
                    f"Matched {source}: {alias}. "
                    f"Description: {field.get('description', '') or field.get('label', '') or 'n/a'}."
                )
                doc = RetrievedDocument(
                    source="field-exact",
                    title=f"{field.get('entity_set', '')}.{field.get('field_name', '')}",
                    content=content,
                    score=round(score, 3),
                    metadata={**field, "matched_alias": alias, "matched_alias_source": source},
                )
                by_alias.setdefault(normalized_alias, []).append(doc)

        results: list[RetrievedDocument] = []
        for docs in by_alias.values():
            docs.sort(key=lambda item: item.score, reverse=True)
            results.extend(docs[:3])
        return sorted(results, key=lambda item: item.score, reverse=True)

    def _search_fuzzy_field_aliases(self, fields: list[dict], query: str) -> list[RetrievedDocument]:
        normalized_query = self._normalize_alias_phrase(query)
        query_phrases = self._query_alias_phrases(normalized_query)
        if not query_phrases:
            return []

        results: list[RetrievedDocument] = []
        for field in fields:
            best_match: tuple[float, str, str, str, float] | None = None
            for alias, source, base_score in self._field_alias_specs(field):
                normalized_alias = self._normalize_alias_phrase(alias)
                compact_alias = normalized_alias.replace(" ", "")
                if len(compact_alias) < 4:
                    continue
                for phrase in query_phrases:
                    compact_phrase = phrase.replace(" ", "")
                    if len(compact_phrase) < 4:
                        continue
                    ratio = SequenceMatcher(None, compact_phrase, compact_alias).ratio()
                    if ratio < 0.82:
                        continue
                    if compact_alias in normalized_query.replace(" ", ""):
                        continue
                    candidate = (ratio, alias, phrase, source, base_score)
                    if best_match is None or candidate[0] > best_match[0]:
                        best_match = candidate
            if best_match is None:
                continue
            ratio, alias, phrase, source, base_score = best_match
            score = round((base_score * 0.72) + (ratio * 18.0), 3)
            content = (
                f"Fuzzy metadata field match `{field.get('field_name', '')}` on `{field.get('entity_set', '')}`. "
                f"Matched query phrase `{phrase}` to {source}: {alias}. "
                f"Description: {field.get('description', '') or field.get('label', '') or 'n/a'}."
            )
            results.append(
                RetrievedDocument(
                    source="field-fuzzy",
                    title=f"{field.get('entity_set', '')}.{field.get('field_name', '')}",
                    content=content,
                    score=score,
                    metadata={
                        **field,
                        "matched_alias": alias,
                        "matched_query_phrase": phrase,
                        "matched_alias_source": f"fuzzy_{source}",
                        "matched_alias_similarity": round(ratio, 4),
                    },
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)

    def _search_lookup_paths(self, lookup_paths: list[dict], search_terms: list[str]) -> list[RetrievedDocument]:
        results: list[RetrievedDocument] = []
        for path in lookup_paths:
            return_object = str(path.get("return_object", ""))
            object_terms = self.OBJECT_ALIASES.get(return_object, [])
            text = " ".join(
                [
                    path.get("path_id", ""),
                    path.get("anchor_object", ""),
                    return_object,
                    path.get("target_entity_set", ""),
                    path.get("target_field", ""),
                    " ".join(path.get("filter_fields", [])),
                    " ".join(path.get("result_fields", [])),
                    path.get("description", ""),
                    " ".join(object_terms),
                    " ".join(path.get("business_aliases", [])),
                ]
            )
            score = self._score_text(text, search_terms, base_weight=3.8)
            anchor_term = str(path.get("anchor_object", "")).lower()
            if anchor_term and any(anchor_term == term or anchor_term in term for term in search_terms):
                score += 5.0
            if object_terms and any(term in search_terms for term in object_terms):
                score += 6.0
            if (path.get("steps") or []) and len(path.get("steps") or []) > 1:
                score += 1.25
            score += float(path.get("confidence", 0.0)) * 2.0
            if score <= 0:
                continue
            content = (
                f"Lookup path `{path.get('path_id', '')}` reaches `{path.get('target_entity_set', '')}.{path.get('target_field', '')}` "
                f"from anchor `{path.get('anchor_object', '')}`. Steps: {path.get('steps', [])}."
            )
            metadata = {
                **path,
                "entity_set": path.get("target_entity_set", ""),
                "field_name": path.get("target_field", ""),
            }
            results.append(
                RetrievedDocument(
                    source="lookup-path",
                    title=path.get("path_id", "lookup-path"),
                    content=content,
                    score=score,
                    metadata=metadata,
                )
            )
        return results

    def _search_vector_documents(self, vector_documents: list[dict], query_vector: Counter[str]) -> list[RetrievedDocument]:
        if not query_vector:
            return []
        query_norm = self._vector_norm(query_vector)
        if query_norm <= 0:
            return []
        scored: list[RetrievedDocument] = []
        for doc in vector_documents:
            doc_id = doc.get("doc_id", "")
            doc_vector, doc_norm = self._get_document_vector(doc_id, doc.get("content", ""))
            similarity = self._cosine_similarity(query_vector, query_norm, doc_vector, doc_norm)
            if similarity < 0.08:
                continue
            metadata = {
                **(doc.get("metadata") or {}),
                "entity_set": doc.get("entity_set", ""),
                "field_name": doc.get("field_name", ""),
                "path_id": doc.get("path_id", ""),
                "target_entity_set": doc.get("entity_set", ""),
                "target_field": doc.get("field_name", ""),
            }
            source = "field-vector" if doc.get("doc_type") == "field" else "lookup-path-vector"
            title = (
                f"{doc.get('entity_set', '')}.{doc.get('field_name', '')}"
                if doc.get("doc_type") == "field"
                else doc.get("path_id", doc_id)
            )
            scored.append(
                RetrievedDocument(
                    source=source,
                    title=title,
                    content=doc.get("content", ""),
                    score=round(similarity * 40.0, 4),
                    metadata=metadata,
                )
            )
        return scored

    def _search_doc_chunks(self, doc_chunks: list[dict], search_terms: list[str]) -> list[RetrievedDocument]:
        results: list[RetrievedDocument] = []
        for chunk in doc_chunks:
            text = " ".join(
                [
                    chunk.get("service_name", ""),
                    chunk.get("entity_set", ""),
                    chunk.get("content", ""),
                    " ".join(chunk.get("field_names", [])),
                    " ".join(chunk.get("keywords", [])),
                ]
            )
            score = self._score_text(text, search_terms, base_weight=1.0)
            if score <= 0:
                continue
            results.append(
                RetrievedDocument(
                    source=chunk.get("source_type", "doc-chunk"),
                    title=chunk.get("chunk_id", "chunk"),
                    content=chunk.get("content", ""),
                    score=score,
                    metadata=chunk,
                )
            )
        return results

    def _build_entity_hints(
        self,
        entities: list[dict],
        entity_docs: list[RetrievedDocument],
        field_docs: list[RetrievedDocument],
        business_term_docs: list[RetrievedDocument],
        lookup_path_docs: list[RetrievedDocument],
    ) -> list[RetrievedDocument]:
        entity_meta = {entity.get("entity_set", ""): entity for entity in entities}
        entity_scores: dict[str, float] = {}

        for doc in entity_docs:
            entity_scores[doc.title] = entity_scores.get(doc.title, 0.0) + (doc.score * 1.5)

        for doc in field_docs:
            entity_set = doc.title.split(".", 1)[0]
            entity_scores[entity_set] = entity_scores.get(entity_set, 0.0) + (doc.score * 0.8)

        for doc in business_term_docs:
            entity_set = doc.title.split("->", 1)[-1]
            if entity_set:
                entity_scores[entity_set] = entity_scores.get(entity_set, 0.0) + (doc.score * 1.8)

        for doc in lookup_path_docs:
            entity_set = (doc.metadata or {}).get("entity_set", "")
            if entity_set:
                entity_scores[entity_set] = entity_scores.get(entity_set, 0.0) + (doc.score * 1.1)

        results: list[RetrievedDocument] = []
        for entity_set, score in entity_scores.items():
            meta = entity_meta.get(entity_set)
            if meta is None or score <= 0:
                continue
            content = (
                f"Likely entity candidate `{entity_set}` in service `{meta.get('service_name', '')}`. "
                f"Keys: {', '.join(meta.get('key_fields', [])) or 'n/a'}. "
                f"Default fields: {', '.join(meta.get('default_select_fields', [])) or 'n/a'}. "
                f"Methods: {', '.join(meta.get('supported_methods', [])) or 'GET'}. "
                f"Description: {meta.get('description', '') or 'n/a'}."
            )
            results.append(
                RetrievedDocument(
                    source="entity-hint",
                    title=entity_set,
                    content=content,
                    score=score,
                    metadata=meta,
                )
            )

        return results

    @staticmethod
    def _field_alias_specs(field: dict) -> list[tuple[str, str, float]]:
        specs: list[tuple[str, str, float]] = []
        field_name = str(field.get("field_name", "") or "")
        if field_name:
            specs.append((field_name, "field_name", 42.0))
            split_name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field_name)
            if split_name != field_name:
                specs.append((split_name, "field_name_words", 40.0))
        label = str(field.get("label", "") or "")
        if label:
            specs.append((label, "label", 64.0))
        description = str(field.get("description", "") or "")
        if description:
            specs.append((description, "description", 34.0))
        for alias in field.get("business_aliases", []) or []:
            value = str(alias or "")
            if value:
                specs.append((value, "business_alias", 66.0))
        deduped: list[tuple[str, str, float]] = []
        seen: set[tuple[str, str]] = set()
        for alias, source, score in specs:
            key = (alias.strip().lower(), source)
            if not key[0] or key in seen:
                continue
            seen.add(key)
            deduped.append((alias, source, score))
        return deduped

    @staticmethod
    def _normalize_alias_phrase(text: str) -> str:
        value = str(text or "").lower()
        value = value.replace("\u7edf\u5fa1\u79d1\u76ee", "\u7edf\u9a6d\u79d1\u76ee")
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value).strip()

    @staticmethod
    def _query_alias_phrases(normalized_query: str) -> list[str]:
        phrases: list[str] = []
        phrases.extend(re.findall(r"[a-z][a-z0-9_ ]{3,}", normalized_query))
        for segment in re.findall(r"[\u4e00-\u9fff]{4,}", normalized_query):
            max_width = min(10, len(segment))
            for width in range(4, max_width + 1):
                for start in range(0, len(segment) - width + 1):
                    phrases.append(segment[start : start + width])
        deduped: list[str] = []
        seen: set[str] = set()
        for phrase in phrases:
            normalized = phrase.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _build_search_terms(query: str) -> list[str]:
        lowered = query.lower()
        regex_tokens = re.findall(r"[a-z0-9_]+", lowered)
        chinese_segments = re.findall(r"[\u4e00-\u9fff]+", query)
        chinese_ngrams: list[str] = []
        for segment in chinese_segments:
            chinese_ngrams.append(segment)
            if len(segment) <= 2:
                continue
            for width in (2, 3):
                if len(segment) < width:
                    continue
                for start in range(0, len(segment) - width + 1):
                    chinese_ngrams.append(segment[start : start + width])

        terms = [lowered, *regex_tokens, *chinese_segments, *chinese_ngrams]
        unique_terms: list[str] = []
        seen: set[str] = set()
        for term in terms:
            normalized = term.strip().lower()
            if len(normalized) < 2:
                continue
            if normalized in LocalDocRetriever.STOP_TERMS:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_terms.append(normalized)
        return unique_terms

    @classmethod
    def _build_sparse_vector(cls, text: str) -> Counter[str]:
        normalized = text.lower()
        english_tokens = re.findall(r"[a-z][a-z0-9_]+", normalized)
        number_tokens = re.findall(r"\d{2,}", normalized)
        chinese_segments = re.findall(r"[\u4e00-\u9fff]{2,}", text)
        features: Counter[str] = Counter()
        for token in [*english_tokens, *number_tokens]:
            features[f"tok:{token}"] += 1.0
        for segment in chinese_segments:
            features[f"zh:{segment}"] += 1.6
            for width in (2, 3):
                if len(segment) < width:
                    continue
                for start in range(0, len(segment) - width + 1):
                    features[f"zhg:{segment[start:start + width]}"] += 1.0
        compact = re.sub(r"\s+", "", normalized)
        for width in (3, 4):
            if len(compact) < width:
                continue
            for start in range(0, len(compact) - width + 1):
                features[f"cg:{compact[start:start + width]}"] += 0.4
        return features

    def _get_document_vector(self, doc_id: str, content: str) -> tuple[Counter[str], float]:
        cached = self._vector_cache.get(doc_id)
        if cached is not None:
            return cached
        vector = self._build_sparse_vector(content)
        norm = self._vector_norm(vector)
        self._vector_cache[doc_id] = (vector, norm)
        return vector, norm

    @staticmethod
    def _vector_norm(vector: Counter[str]) -> float:
        return math.sqrt(sum(weight * weight for weight in vector.values()))

    @staticmethod
    def _cosine_similarity(
        query_vector: Counter[str],
        query_norm: float,
        doc_vector: Counter[str],
        doc_norm: float,
    ) -> float:
        if query_norm <= 0 or doc_norm <= 0:
            return 0.0
        overlap_keys = set(query_vector) & set(doc_vector)
        if not overlap_keys:
            return 0.0
        dot = sum(query_vector[key] * doc_vector[key] for key in overlap_keys)
        return dot / (query_norm * doc_norm)

    @staticmethod
    def _score_text(text: str, search_terms: list[str], base_weight: float) -> float:
        lowered = text.lower()
        score = 0.0
        for term in search_terms:
            if term in lowered:
                score += base_weight + min(len(term) * 0.05, 1.5)
        return score
