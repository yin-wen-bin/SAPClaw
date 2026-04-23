from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from sap_odata_agent.domain.models import CardinalityPolicy, QueryConstraints, QueryShape


class QueryConstraintExtractor:
    ANCHORED_IDENTIFIER_PATTERN = r"([A-Za-z0-9][A-Za-z0-9_-]{1,})"
    OBJECT_FIELD_MAP = {
        "supplier": "Supplier",
        "customer": "Customer",
        "business_partner": "BusinessPartner",
    }
    QUESTION_PLACEHOLDERS = {
        "\u54ea",
        "\u54ea\u91cc",
        "\u662f\u54ea",
        "\u662f\u54ea\u91cc",
        "\u662f\u4ec0\u4e48",
        "\u662f\u591a\u5c11",
        "\u4ec0\u4e48",
        "\u591a\u5c11",
        "\u591a\u4e45",
        "\u51e0",
        "what",
        "which",
        "where",
    }
    OBJECT_ALIASES = {
        "supplier": {"\u4f9b\u5e94\u5546", "supplier", "vendor"},
        "customer": {"\u5ba2\u6237", "customer"},
        "business_partner": {"\u4e1a\u52a1\u4f19\u4f34", "business partner", "bp"},
    }
    CONCEPT_ALIASES: dict[str, set[str]] = {}

    def extract(
        self,
        query: str,
        query_shape: QueryShape,
        cardinality: CardinalityPolicy,
        candidate_fields: Iterable[dict] | None = None,
    ) -> QueryConstraints:
        lowered = (query or "").lower()
        target_object = self._detect_target_object(query, lowered)
        concept_aliases = self._merge_concept_aliases(candidate_fields)
        matched_concepts = self._detect_filter_concepts(lowered, concept_aliases)
        matched_concepts = self._remove_shadowed_concepts(lowered, matched_concepts, concept_aliases)
        matched_concepts = self._remove_anchor_object_concepts(query, lowered, matched_concepts, concept_aliases, target_object)
        matched_concepts = self._remove_identity_concepts(matched_concepts, target_object)
        filter_values, explicit_filter_concepts = self._extract_filter_values(query, matched_concepts, concept_aliases, target_object)
        if not filter_values:
            filter_values = self._extract_generic_filter_values(query, target_object)
        filter_concepts = [concept for concept in matched_concepts if concept in explicit_filter_concepts]
        name_match_mode = self._resolve_match_mode(query_shape, filter_concepts)
        target_field_concepts = self._resolve_target_field_concepts(
            query_shape,
            matched_concepts,
            filter_concepts,
            filter_values,
            target_object,
        )
        target_field_concepts = self._remove_unrequested_composite_targets(
            query,
            target_field_concepts,
        )
        if query_shape == QueryShape.NAME_CONTAINS_SEARCH:
            name_candidates = self._name_candidates(candidate_fields)
            target_field_concepts = name_candidates
            filter_concepts = name_candidates
        return QueryConstraints(
            query_shape=query_shape,
            cardinality=cardinality,
            target_object=target_object,
            target_field_concepts=target_field_concepts,
            filter_concepts=filter_concepts,
            filter_values=filter_values,
            requested_operation="read",
            name_match_mode=name_match_mode,
            boolean_intent=query_shape == QueryShape.BOOLEAN_CHECK,
        )

    def _detect_target_object(self, query: str, lowered: str) -> str | None:
        for object_name, aliases in self.OBJECT_ALIASES.items():
            for alias in sorted(aliases, key=len, reverse=True):
                if self._find_anchored_identifier(query, alias):
                    return object_name
        matches: list[tuple[int, int, str]] = []
        for object_name, aliases in self.OBJECT_ALIASES.items():
            for alias in aliases:
                index = lowered.find(alias.lower())
                if index >= 0:
                    matches.append((index, -len(alias), object_name))
        if matches:
            return sorted(matches)[0][2]
        return None

    @classmethod
    def _detect_filter_concepts(cls, lowered: str, concept_aliases: dict[str, set[str]]) -> list[str]:
        return [
            concept
            for concept, aliases in concept_aliases.items()
            if any(alias and cls._alias_matches_query(alias, lowered) for alias in aliases)
        ]

    @staticmethod
    def _alias_matches_query(alias: str, lowered: str) -> bool:
        normalized_alias = QueryConstraintExtractor._normalize_query_text(alias)
        normalized_query = QueryConstraintExtractor._normalize_query_text(lowered)
        compact_alias = normalized_alias.replace(" ", "")
        compact_query = normalized_query.replace(" ", "")
        if not compact_alias:
            return False
        if normalized_alias in normalized_query or compact_alias in compact_query:
            return True
        if len(compact_alias) < 2:
            return False
        if re.fullmatch(r"[a-z0-9_]+", compact_alias):
            query_tokens = set(re.findall(r"[a-z0-9_]+", normalized_query))
            return any(SequenceMatcher(None, compact_alias, token).ratio() >= 0.88 for token in query_tokens)
        window_size = len(compact_alias)
        for start in range(0, max(0, len(compact_query) - window_size) + 1):
            window = compact_query[start : start + window_size]
            if SequenceMatcher(None, compact_alias, window).ratio() >= 0.78:
                return True
        return False

    @staticmethod
    def _remove_shadowed_concepts(
        lowered: str,
        matched_concepts: list[str],
        concept_aliases: dict[str, set[str]],
    ) -> list[str]:
        matched_aliases = {
            concept: [
                alias.lower()
                for alias in concept_aliases.get(concept, set())
                if alias and alias.lower() in lowered
            ]
            for concept in matched_concepts
        }
        kept: list[str] = []
        for concept in matched_concepts:
            aliases = matched_aliases.get(concept, [])
            if aliases and all(
                any(
                    other != concept
                    and alias != other_alias
                    and alias in other_alias
                    and other_alias in lowered
                    for other, other_aliases in matched_aliases.items()
                    for other_alias in other_aliases
                )
                for alias in aliases
            ):
                continue
            kept.append(concept)
        return kept

    @staticmethod
    def _resolve_match_mode(query_shape: QueryShape, filter_concepts: list[str]) -> str | None:
        if query_shape == QueryShape.NAME_CONTAINS_SEARCH:
            return "contains"
        if filter_concepts:
            return "eq"
        return None

    @staticmethod
    def _resolve_target_field_concepts(
        query_shape: QueryShape,
        matched_concepts: list[str],
        filter_concepts: list[str],
        filter_values: list[str],
        target_object: str | None,
    ) -> list[str]:
        if query_shape == QueryShape.NAME_CONTAINS_SEARCH:
            return ["BusinessPartnerFullName"]
        if query_shape == QueryShape.BOOLEAN_CHECK:
            return [concept for concept in matched_concepts if concept not in filter_concepts] or list(filter_concepts)
        if query_shape in {QueryShape.SEARCH_BY_ATTRIBUTE, QueryShape.LIST_QUERY} and target_object and filter_concepts:
            return []
        explicit_targets = [concept for concept in matched_concepts if concept not in filter_concepts]
        if explicit_targets:
            return explicit_targets
        return list(filter_concepts)

    def _merge_concept_aliases(self, candidate_fields: Iterable[dict] | None) -> dict[str, set[str]]:
        merged = {concept: set(aliases) for concept, aliases in self.CONCEPT_ALIASES.items()}
        for field in candidate_fields or []:
            field_name = str(field.get("field_name", "")).strip()
            if not field_name:
                continue
            aliases = merged.setdefault(field_name, set())
            aliases.update(self._extract_field_aliases(field))
        return merged

    def _extract_filter_values(
        self,
        query: str,
        matched_concepts: list[str],
        concept_aliases: dict[str, set[str]],
        target_object: str | None = None,
    ) -> tuple[list[str], set[str]]:
        values: list[str] = []
        explicit_filter_concepts: set[str] = set()
        anchored_identifiers = self._extract_anchored_identifiers(query, target_object)
        values.extend(value for value, _ in anchored_identifiers.values())
        anchored_spans = [span for _, span in anchored_identifiers.values()]
        raw_query = query or ""
        for match in re.finditer(r"\d{2,}", raw_query):
            if any(start <= match.start() and match.end() <= end for start, end in anchored_spans):
                continue
            if self._is_numeric_inside_structured_literal(raw_query, match.start(), match.end()):
                continue
            values.append(match.group(0))
        quoted = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', query or "")
        values.extend(item.strip() for item in quoted if item.strip())

        for concept in matched_concepts:
            aliases = sorted(concept_aliases.get(concept, set()), key=len, reverse=True)
            for alias in aliases:
                explicit_match = re.search(
                    rf"{re.escape(alias)}(?:\u4e3a|\u662f|:|=)\s*([A-Za-z0-9@.\u4e00-\u9fff\s\-_]+?)(?:\u7684|\u4e2d|\?|？|$)",
                    query or "",
                    flags=re.IGNORECASE,
                )
                if explicit_match:
                    candidate = explicit_match.group(1).strip()
                    if candidate and not self._looks_like_question_placeholder(candidate):
                        values.append(candidate)
                        explicit_filter_concepts.add(concept)
                        break

                adjacent_match = re.search(
                    rf"{re.escape(alias)}\s*([A-Za-z0-9@.\u4e00-\u9fff\-_]+?)(?:\u7684|\u4e2d|\?|？|$)",
                    query or "",
                    flags=re.IGNORECASE,
                )
                if adjacent_match:
                    candidate = adjacent_match.group(1).strip()
                    if (
                        candidate
                        and candidate.lower() != alias.lower()
                        and not self._looks_like_question_placeholder(candidate)
                    ):
                        values.append(candidate)
                        explicit_filter_concepts.add(concept)
                        break

        return list(dict.fromkeys(value for value in values if value)), explicit_filter_concepts

    def _extract_generic_filter_values(self, query: str, target_object: str | None = None) -> list[str]:
        values: list[str] = []
        anchored_identifiers = self._extract_anchored_identifiers(query, target_object)
        values.extend(value for value, _ in anchored_identifiers.values())
        anchored_spans = [span for _, span in anchored_identifiers.values()]
        raw_query = query or ""
        for match in re.finditer(
            r"(?:\u4e3a|\u662f|=|:)\s*([A-Za-z0-9@.\u4e00-\u9fff][A-Za-z0-9@.\u4e00-\u9fff\s\-_]{0,80}?)(?:\u7684|\u4e2d|\?|$)",
            raw_query,
            flags=re.IGNORECASE,
        ):
            candidate = match.group(1).strip()
            if candidate and not self._looks_like_question_placeholder(candidate):
                values.append(candidate)
        for match in re.finditer(r"\d{2,}", raw_query):
            if any(start <= match.start() and match.end() <= end for start, end in anchored_spans):
                continue
            if self._is_numeric_inside_structured_literal(raw_query, match.start(), match.end()):
                continue
            values.append(match.group(0))
        quoted = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', raw_query)
        values.extend(item.strip() for item in quoted if item.strip())
        return list(dict.fromkeys(value for value in values if value))

    @staticmethod
    def _extract_field_aliases(field: dict) -> set[str]:
        aliases: set[str] = set()
        for key in ("field_name", "label", "description", "matched_query_phrase"):
            value = str(field.get(key, "")).strip()
            if not value:
                continue
            aliases.add(value.lower())
        for alias in field.get("business_aliases", []) or []:
            normalized = str(alias).strip().lower()
            if normalized:
                aliases.add(normalized)
        field_name = str(field.get("field_name", "")).strip()
        if field_name:
            aliases.update(QueryConstraintExtractor._camel_case_aliases(field_name))
        return aliases

    @staticmethod
    def _name_candidates(candidate_fields: Iterable[dict] | None) -> list[str]:
        candidates: list[str] = []
        for field in candidate_fields or []:
            field_name = str(field.get("field_name", "")).strip()
            if not field_name:
                continue
            searchable = " ".join(
                [
                    field_name,
                    str(field.get("label", "") or ""),
                    str(field.get("description", "") or ""),
                    " ".join(str(alias or "") for alias in field.get("business_aliases", []) or []),
                ]
            ).lower()
            if "name" in searchable or "\u540d" in searchable:
                candidates.append(field_name)
        return list(dict.fromkeys(candidates))[:3]

    def _remove_identity_concepts(self, matched_concepts: list[str], target_object: str | None) -> list[str]:
        identity_concept = self.OBJECT_FIELD_MAP.get(target_object or "")
        if not identity_concept:
            return matched_concepts
        return [concept for concept in matched_concepts if concept != identity_concept]

    def _remove_unrequested_composite_targets(self, query: str, target_field_concepts: list[str]) -> list[str]:
        if len(target_field_concepts) < 2:
            return target_field_concepts
        normalized_query = self._normalize_query_text(query)
        concepts = list(dict.fromkeys(target_field_concepts))
        kept: list[str] = []
        for concept in concepts:
            if self._is_unrequested_composite(concept, concepts, normalized_query):
                continue
            kept.append(concept)
        return kept or target_field_concepts

    def _is_unrequested_composite(
        self,
        concept: str,
        concepts: list[str],
        normalized_query: str,
    ) -> bool:
        for base in concepts:
            if base == concept or not concept.startswith(base):
                continue
            suffix = concept[len(base) :]
            if not suffix:
                continue
            suffix_terms = self._suffix_terms(suffix)
            if suffix_terms and not any(term in normalized_query for term in suffix_terms):
                return True
        return False

    @staticmethod
    def _suffix_terms(suffix: str) -> set[str]:
        words = re.findall(r"[A-Z][a-z0-9]*|[A-Z]+(?=[A-Z]|$)", suffix)
        terms = {word.lower() for word in words if word}
        compact = "".join(words).lower()
        if compact:
            terms.add(compact)
        translations = {
            "company": {"公司"},
            "person": {"个人", "人员"},
            "address": {"地址"},
            "name": {"名称", "姓名"},
            "fullname": {"全名", "完整名称"},
            "code": {"代码"},
            "group": {"组"},
            "type": {"类型"},
            "number": {"编号", "号码"},
        }
        for term in list(terms):
            terms.update(translations.get(term, set()))
        return terms

    @staticmethod
    def _normalize_query_text(query: str) -> str:
        value = (query or "").lower()
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value)

    def _remove_anchor_object_concepts(
        self,
        query: str,
        lowered: str,
        matched_concepts: list[str],
        concept_aliases: dict[str, set[str]],
        target_object: str | None,
    ) -> list[str]:
        object_aliases = {alias.lower() for alias in self.OBJECT_ALIASES.get(target_object or "", set())}
        if not object_aliases:
            return matched_concepts
        answer_text = self._answer_text_after_anchor(query, lowered, target_object)
        kept: list[str] = []
        for concept in matched_concepts:
            aliases = {alias.lower() for alias in concept_aliases.get(concept, set()) if alias}
            anchor_aliases = [
                alias
                for alias in aliases.intersection(object_aliases)
                if self._find_anchored_identifier(query, alias)
            ]
            if anchor_aliases and not any(alias in answer_text for alias in anchor_aliases):
                continue
            kept.append(concept)
        return kept

    @staticmethod
    def _answer_text(lowered: str) -> str:
        marker = "\u7684"
        if marker not in lowered:
            return lowered
        return lowered.split(marker, 1)[1]

    def _answer_text_after_anchor(self, query: str, lowered: str, target_object: str | None) -> str:
        marker = "\u7684"
        if marker in lowered:
            return lowered.split(marker, 1)[1]
        for alias in sorted(self.OBJECT_ALIASES.get(target_object or "", set()), key=len, reverse=True):
            match = self._find_anchored_identifier(query, alias)
            if match:
                return (query or "")[match.end() :].lower()
        return lowered

    def _extract_anchored_identifiers(self, query: str, target_object: str | None) -> dict[str, tuple[str, tuple[int, int]]]:
        identifiers: dict[str, tuple[str, tuple[int, int]]] = {}
        alias_groups = (
            {target_object: self.OBJECT_ALIASES.get(target_object or "", set())}
            if target_object
            else self.OBJECT_ALIASES
        )
        for aliases in alias_groups.values():
            for alias in sorted(aliases, key=len, reverse=True):
                match = self._find_anchored_identifier(query, alias)
                if match:
                    identifiers[alias] = (match.group(1), match.span(1))
                    break
        return identifiers

    def _find_anchored_identifier(self, query: str, alias: str):
        return re.search(
            rf"{re.escape(alias)}\s*{self.ANCHORED_IDENTIFIER_PATTERN}",
            query or "",
            flags=re.IGNORECASE,
        )

    def _looks_like_question_placeholder(self, candidate: str) -> bool:
        normalized = candidate.strip().lower()
        if not normalized:
            return True
        if normalized in self.QUESTION_PLACEHOLDERS:
            return True
        return any(normalized.startswith(prefix) or prefix in normalized for prefix in self.QUESTION_PLACEHOLDERS)

    @staticmethod
    def _is_numeric_inside_structured_literal(text: str, start: int, end: int) -> bool:
        left = start
        right = end
        while left > 0 and re.match(r"[A-Za-z0-9@._-]", text[left - 1]):
            left -= 1
        while right < len(text) and re.match(r"[A-Za-z0-9@._-]", text[right]):
            right += 1
        token = text[left:right]
        return bool(set("@.").intersection(token) and token != text[start:end])

    @staticmethod
    def _camel_case_aliases(field_name: str) -> set[str]:
        spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", field_name).strip().lower()
        compact = spaced.replace(" ", "")
        return {spaced, compact} if spaced else set()
