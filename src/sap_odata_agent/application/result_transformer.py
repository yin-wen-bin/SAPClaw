from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sap_odata_agent.domain.models import AggregateMetric, QueryPlan, ResultTransform


class ResultTransformError(ValueError):
    def __init__(self, code: str, message: str, diagnostics: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or {}


class ResultTransformer:
    """Apply deterministic post-query result transforms requested by the plan."""

    def apply(self, plan: QueryPlan, data: dict[str, Any] | None) -> dict[str, Any] | None:
        if not data or plan.result_transform is None:
            return data
        transform = plan.result_transform
        if transform.type != "aggregate":
            return data
        return self._aggregate(data, transform)

    def _aggregate(self, data: dict[str, Any], transform: ResultTransform) -> dict[str, Any]:
        source_rows = self._source_rows(data)
        source_result_count = self._safe_int(data.get("result_count"), len(source_rows))
        source_truncated = bool(data.get("source_truncated", False))
        source_complete = bool(data.get("source_complete", len(source_rows) >= source_result_count))
        if source_truncated or not source_complete:
            raise ResultTransformError(
                "aggregate_source_incomplete",
                "Aggregate source is incomplete; no aggregate result was produced.",
                {
                    "source_row_count": source_result_count,
                    "fetched_row_count": len(source_rows),
                    "source_complete": source_complete,
                    "source_truncated": source_truncated,
                },
            )

        deduped_rows, duplicate_count = self._deduplicate_rows(source_rows, transform.deduplicate_by)
        metrics = self._metrics(transform)
        groups: dict[tuple[Any, ...], dict[str, Any]] = {}
        if not deduped_rows and not transform.group_by:
            groups[()] = self._new_group({}, metrics)

        currency_groups: dict[str, set[str]] = {}
        for row_index, row in enumerate(deduped_rows):
            key = tuple(row.get(field) for field in transform.group_by)
            if key not in groups:
                groups[key] = self._new_group(
                    {field: row.get(field, "") for field in transform.group_by}, metrics
                )
            state = groups[key]
            state["row_count"] += 1
            for metric in metrics:
                if metric.operation == "count":
                    continue
                if metric.operation == "count_distinct":
                    distinct_key = tuple(
                        self._required_value(row, field, "distinct key", row_index)
                        for field in metric.distinct_fields
                    )
                    state["distinct"][metric.output_field].add(distinct_key)
                    continue
                value = self._decimal_value(row.get(str(metric.field)), str(metric.field), row_index)
                if metric.operation == "sum_abs":
                    value = abs(value)
                state["totals"][metric.output_field] += value
                if metric.currency_field:
                    currency = str(
                        self._required_value(row, metric.currency_field, "currency", row_index)
                    )
                    state["currencies"][metric.output_field].add(currency)
                    currency_groups.setdefault(metric.currency_field, set()).add(currency)

        aggregated_rows: list[dict[str, Any]] = []
        for state in groups.values():
            row = dict(state["base"])
            for metric in metrics:
                if metric.operation == "count":
                    row[metric.output_field] = state["row_count"]
                elif metric.operation == "count_distinct":
                    row[metric.output_field] = len(state["distinct"][metric.output_field])
                else:
                    currencies = state["currencies"].get(metric.output_field, set())
                    if metric.currency_field and len(currencies) != 1:
                        raise ResultTransformError(
                            "aggregate_currency_unresolved",
                            f"Aggregate metric `{metric.output_field}` does not resolve to exactly one currency.",
                            {
                                "metric": metric.output_field,
                                "currency_field": metric.currency_field,
                                "currencies": sorted(currencies),
                            },
                        )
                    row[metric.output_field] = self._format_decimal(state["totals"][metric.output_field])
            aggregated_rows.append(row)

        display_limit = 50
        displayed_rows = aggregated_rows[:display_limit]
        pagination = dict(data.get("pagination") or {}) if isinstance(data.get("pagination"), dict) else {}
        has_next = len(displayed_rows) < len(aggregated_rows)
        pagination.update(
            {
                "page_size": display_limit,
                "display_limit": display_limit,
                "skip": 0,
                "page_number": 1,
                "has_next": has_next,
                "next_skip": display_limit if has_next else None,
                "local_has_next": has_next,
                "sap_has_next": False,
                "sap_next_skip": None,
            }
        )
        transformed = dict(data)
        transformed.update(
            {
                "result_count": len(aggregated_rows),
                "returned_count": len(aggregated_rows),
                "displayed_count": len(displayed_rows),
                "results": displayed_rows,
                "_all_results": aggregated_rows,
                "pagination": pagination,
                "result_transform": {
                    "type": transform.type,
                    "group_by": list(transform.group_by),
                    "sum_fields": list(transform.sum_fields),
                    "metrics": [self._metric_payload(metric) for metric in metrics],
                    "deduplicate_by": list(transform.deduplicate_by),
                    "source_result_count": source_result_count,
                    "source_row_count": source_result_count,
                    "source_returned_count": len(source_rows),
                    "fetched_row_count": len(source_rows),
                    "deduplicated_row_count": len(deduped_rows),
                    "duplicate_row_count": duplicate_count,
                    "source_complete": source_complete,
                    "source_truncated": source_truncated,
                    "stable_order_fields": list(data.get("source_stable_order_fields") or []),
                    "currency_groups": {
                        field: sorted(values) for field, values in sorted(currency_groups.items())
                    },
                    "invalid_numeric_values": 0,
                },
            }
        )
        return transformed

    @staticmethod
    def _metrics(transform: ResultTransform) -> list[AggregateMetric]:
        metrics = list(transform.metrics)
        output_fields = {metric.output_field for metric in metrics}
        metrics.extend(
            AggregateMetric(operation="sum", output_field=field, field=field)
            for field in transform.sum_fields
            if field not in output_fields
        )
        return metrics

    @staticmethod
    def _new_group(base: dict[str, Any], metrics: list[AggregateMetric]) -> dict[str, Any]:
        return {
            "base": base,
            "row_count": 0,
            "totals": {
                metric.output_field: Decimal("0")
                for metric in metrics
                if metric.operation in {"sum", "sum_abs"}
            },
            "distinct": {
                metric.output_field: set()
                for metric in metrics
                if metric.operation == "count_distinct"
            },
            "currencies": {
                metric.output_field: set()
                for metric in metrics
                if metric.currency_field
            },
        }

    @classmethod
    def _deduplicate_rows(
        cls, rows: list[dict[str, Any]], fields: list[str]
    ) -> tuple[list[dict[str, Any]], int]:
        if not fields:
            return rows, 0
        seen: set[tuple[Any, ...]] = set()
        deduplicated: list[dict[str, Any]] = []
        for row_index, row in enumerate(rows):
            key = tuple(cls._required_value(row, field, "deduplication key", row_index) for field in fields)
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(row)
        return deduplicated, len(rows) - len(deduplicated)

    @staticmethod
    def _required_value(row: dict[str, Any], field: str, role: str, row_index: int) -> Any:
        value = row.get(field)
        if value in (None, ""):
            raise ResultTransformError(
                "aggregate_required_value_missing",
                f"Aggregate {role} `{field}` is missing at source row {row_index}.",
                {"field": field, "role": role, "row_index": row_index},
            )
        return value

    @staticmethod
    def _source_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = data.get("_all_results")
        if not isinstance(rows, list) or not rows:
            rows = data.get("results")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _decimal_value(value: Any, field: str, row_index: int) -> Decimal:
        if value in (None, ""):
            raise ResultTransformError(
                "aggregate_invalid_numeric_value",
                f"Aggregate numeric field `{field}` is empty at source row {row_index}.",
                {"field": field, "row_index": row_index, "value": value},
            )
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ResultTransformError(
                "aggregate_invalid_numeric_value",
                f"Aggregate numeric field `{field}` is invalid at source row {row_index}.",
                {"field": field, "row_index": row_index, "value": str(value)},
            ) from None
        if not parsed.is_finite():
            raise ResultTransformError(
                "aggregate_invalid_numeric_value",
                f"Aggregate numeric field `{field}` is not finite at source row {row_index}.",
                {"field": field, "row_index": row_index, "value": str(value)},
            )
        return parsed

    @staticmethod
    def _metric_payload(metric: AggregateMetric) -> dict[str, Any]:
        return {
            "operation": metric.operation,
            "output_field": metric.output_field,
            "field": metric.field,
            "distinct_fields": list(metric.distinct_fields),
            "currency_field": metric.currency_field,
        }

    @staticmethod
    def _safe_int(value: Any, fallback: int) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        text = format(value, "f")
        if "." not in text:
            return text
        return text.rstrip("0").rstrip(".") or "0"
