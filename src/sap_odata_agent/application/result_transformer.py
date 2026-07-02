from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sap_odata_agent.domain.models import QueryPlan, ResultTransform


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
        if not source_rows:
            return data

        groups: dict[tuple[Any, ...], dict[str, Any]] = {}
        totals: dict[tuple[Any, ...], dict[str, Decimal]] = {}
        for row in source_rows:
            key = tuple(row.get(field) for field in transform.group_by)
            if key not in groups:
                groups[key] = {field: row.get(field, "") for field in transform.group_by}
                totals[key] = {field: Decimal("0") for field in transform.sum_fields}
            for field in transform.sum_fields:
                totals[key][field] += self._decimal_value(row.get(field))

        aggregated_rows: list[dict[str, Any]] = []
        for key, base_row in groups.items():
            row = dict(base_row)
            for field in transform.sum_fields:
                row[field] = self._format_decimal(totals[key][field])
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
                    "source_result_count": data.get("result_count", len(source_rows)),
                    "source_returned_count": len(source_rows),
                    "source_complete": bool(data.get("source_complete", True)),
                    "source_truncated": bool(data.get("source_truncated", False)),
                },
            }
        )
        return transformed

    @staticmethod
    def _source_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
        rows = data.get("_all_results")
        if not isinstance(rows, list) or not rows:
            rows = data.get("results")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _decimal_value(value: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        text = format(value, "f")
        if "." not in text:
            return text
        return text.rstrip("0").rstrip(".") or "0"
