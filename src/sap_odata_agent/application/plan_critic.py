from __future__ import annotations

import re

from sap_odata_agent.domain.models import AgentRequest, CardinalityPolicy, CriticFinding, QueryPlan


class PlanCritic:
    def review(self, request: AgentRequest, plan: QueryPlan) -> list[CriticFinding]:
        constraints = request.constraints
        findings: list[CriticFinding] = []
        selected_fields = set(plan.select_fields or [])
        filter_fields = {item.field for item in plan.filters}
        for step in plan.steps or []:
            selected_fields.update(step.select_fields or [])
            filter_fields.update(item.field for item in step.filters or [])

        if self._looks_like_field_list_without_filter_intent(request):
            output_fields_filtered = sorted(
                item.field
                for item in plan.filters or []
                if item.field in selected_fields and not self._filter_value_is_mentioned(request, item.value)
            )
            for step in plan.steps or []:
                step_selected_fields = set(step.select_fields or [])
                output_fields_filtered.extend(
                    item.field
                    for item in step.filters or []
                    if item.field in step_selected_fields and not self._filter_value_is_mentioned(request, item.value)
                )
            output_fields_filtered = sorted(set(output_fields_filtered))
            if output_fields_filtered:
                findings.append(
                    CriticFinding(
                        code="output_field_used_as_filter",
                        message=(
                            "The user asked to display field-list attributes, but the plan also uses those "
                            "output fields as filters without explicit filter intent: "
                            + ", ".join(output_fields_filtered)
                        ),
                        severity="error",
                        blocking=True,
                    )
                )

        if constraints is None:
            return findings

        required_fields = set(constraints.target_field_concepts or [])
        missing_required = sorted(required_fields - selected_fields)
        if missing_required:
            findings.append(
                CriticFinding(
                    code="required_target_field_missing",
                    message="The final select list does not include the requested target field(s): "
                    + ", ".join(missing_required),
                    severity="error",
                    blocking=True,
                )
            )

        required_filter_fields = set(constraints.filter_concepts or [])
        if required_filter_fields and not required_filter_fields.intersection(filter_fields):
            findings.append(
                CriticFinding(
                    code="filter_concept_missing",
                    message="The plan does not apply any filter for the requested filter concept(s): "
                    + ", ".join(sorted(required_filter_fields)),
                    severity="error",
                    blocking=True,
                )
            )

        if constraints.cardinality == CardinalityPolicy.MANY and plan.top == 1:
            findings.append(
                CriticFinding(
                    code="list_query_top_too_small",
                    message="The query shape expects multiple rows, but the plan is limited to top=1.",
                    severity="error",
                    blocking=True,
                )
            )

        if constraints.name_match_mode == "contains" and plan.filters:
            if not any(item.operator == "contains" for item in plan.filters):
                findings.append(
                    CriticFinding(
                        code="contains_query_built_as_eq",
                        message="The query asks for a contains-style match, but the plan uses exact-match filters only.",
                        severity="error",
                        blocking=True,
                    )
                )

        return findings

    @staticmethod
    def _looks_like_field_list_without_filter_intent(request: AgentRequest) -> bool:
        text = f" {request.user_input or request.resolved_user_input or ''} ".lower()
        field_list_markers = (
            " with ",
            " include ",
            " includes ",
            " including ",
            " display ",
            " show ",
            " list ",
        )
        if not any(marker in text for marker in field_list_markers):
            return False
        if PlanCritic._has_explicit_identifier_filter_phrase(text):
            return False
        explicit_filter_markers = (
            " only ",
            " where ",
            " equal ",
            " equals ",
            " greater than ",
            " less than ",
            " at least ",
            " at most ",
            " nonzero ",
            " non-zero ",
            " true ",
            " false ",
            " open ",
            " closed ",
            " completed ",
            " incomplete ",
            " unreceived ",
            " undelivered ",
            " pending ",
            " overdue ",
            " not yet ",
            "\u4ec5",
            "\u53ea",
            "\u5927\u4e8e",
            "\u5c0f\u4e8e",
            "\u7b49\u4e8e",
            "\u4e3a",
            "\u662f",
            "\u5426",
            "\u672a",
            "\u5df2",
        )
        if any(marker in text for marker in explicit_filter_markers):
            return False
        constraints = request.constraints
        if constraints is None:
            return True
        return not (constraints.filter_concepts or constraints.filter_values or constraints.boolean_intent)

    @staticmethod
    def _has_explicit_identifier_filter_phrase(text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text.lower())
        english_patterns = (
            r"\bcompany\s+code\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bledger\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bsupplier\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bvendor\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bcustomer\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bmaterial\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bproduct\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bplant\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bpurchase\s+order\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bsales\s+order\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bg/?l\s+account\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bcost\s+center\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
            r"\bprofit\s+center\s+(?P<value>[a-z0-9][a-z0-9._-]*)\b",
        )
        if any(
            PlanCritic._looks_like_identifier_token(match.group("value"))
            for pattern in english_patterns
            for match in re.finditer(pattern, normalized)
        ):
            return True
        chinese_patterns = (
            r"(?:公司代码|分类账|供应商|客户|物料|产品|工厂|采购订单|销售订单|总账科目|成本中心|利润中心)\s*[a-z0-9][a-z0-9._-]*",
        )
        return any(re.search(pattern, normalized) for pattern in chinese_patterns)

    @staticmethod
    def _looks_like_identifier_token(value: str) -> bool:
        token = str(value or "").strip().lower()
        if not token:
            return False
        generic_object_words = {
            "record",
            "records",
            "list",
            "lists",
            "item",
            "items",
            "header",
            "headers",
            "detail",
            "details",
            "data",
            "master",
            "main",
            "basic",
            "summary",
            "summaries",
            "all",
            "open",
            "closed",
            "with",
            "for",
            "by",
            "of",
        }
        if token in generic_object_words:
            return False
        return bool(re.search(r"\d|[._/-]", token))

    @staticmethod
    def _filter_value_is_mentioned(request: AgentRequest, value: object) -> bool:
        literal = str(value or "").strip().strip("'\"").lower()
        if not literal:
            return False
        text = f"{request.resolved_user_input or ''} {request.user_input or ''}".lower()
        if literal in {"true", "false", "x"}:
            return literal in text.split()
        return literal in text
