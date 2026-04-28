from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from sap_odata_agent.domain.models import AgentRequest, PresentationVerification, QueryPlan, ResultPresentation
from sap_odata_agent.infrastructure.sap.date_formatting import format_sap_json_date_for_display


class PresentationVerifier:
    COUNT_PATTERNS = (
        re.compile(r"查询结果总共\s*(\d+)\s*条"),
        re.compile(r"共(?:找到|有)?\s*(\d+)\s*(?:条|家|个|位|名)"),
        re.compile(r"共有\s*(\d+)\s*(?:条|家|个|位|名)"),
        re.compile(r"found\s+(\d+)\s+(?:rows|records|items)", re.IGNORECASE),
    )

    def verify_and_repair(
        self,
        request: AgentRequest,
        plan: QueryPlan,
        presentation: ResultPresentation | None,
        data: dict | None = None,
    ) -> tuple[ResultPresentation | None, PresentationVerification]:
        if presentation is None:
            return None, PresentationVerification(passed=True, issues=[])

        issues: list[str] = []
        repaired = presentation

        if presentation.kind == "table":
            actual_count = self._actual_record_count(data, request)
            row_count = len(presentation.rows or [])
            rows_have_no_values = self._rows_have_no_values(presentation.rows or [])
            if (actual_count is not None and row_count < min(actual_count, 50)) or rows_have_no_values:
                repaired_rows = self._rows_from_data(data, presentation.columns or [], request)[:50]
                if repaired_rows:
                    if rows_have_no_values:
                        issues.append("table_rows_empty_values")
                    else:
                        issues.append(f"table_rows_mismatch:{row_count}!={actual_count}")
                    repaired_columns = list(repaired_rows[0].keys()) if self._rows_have_no_values(repaired_rows) is False else repaired.columns
                    repaired = replace(repaired, columns=repaired_columns, rows=repaired_rows)
                    row_count = len(repaired.rows or [])

            stated_count = self._extract_stated_count(presentation.text)
            expected_count = actual_count if actual_count is not None else row_count
            if stated_count is not None and stated_count != expected_count:
                issues.append(f"table_count_mismatch:{stated_count}!={expected_count}")
                repaired = replace(
                    repaired,
                    text=self._rewrite_count_text(repaired.text, stated_count, expected_count),
                )

        required_fields = set((request.constraints.target_field_concepts if request.constraints else []) or [])
        if required_fields:
            covered_columns = set(repaired.columns or [])
            covered_columns.update(plan.response_summary_fields or [])
            if repaired.kind == "text":
                covered_columns.update(plan.select_fields or [])
            if not required_fields.intersection(covered_columns):
                issues.append("required_target_field_not_presented:" + ",".join(sorted(required_fields)))

        return repaired, PresentationVerification(passed=not issues, issues=issues)

    def _extract_stated_count(self, text: str) -> int | None:
        for pattern in self.COUNT_PATTERNS:
            match = pattern.search(text or "")
            if match:
                return int(match.group(1))
        return None

    def _rewrite_count_text(self, text: str, previous_count: int, actual_count: int) -> str:
        updated = text or ""
        for pattern in self.COUNT_PATTERNS:
            if pattern.search(updated):
                return pattern.sub(
                    lambda match: match.group(0).replace(str(previous_count), str(actual_count), 1),
                    updated,
                    count=1,
                )
        return f"共找到{actual_count}条记录。{updated}".strip()

    @staticmethod
    def _actual_record_count(data: dict | None, request: AgentRequest | None = None) -> int | None:
        if not data:
            return None
        try:
            return int(str(data.get("result_count")))
        except (TypeError, ValueError):
            pass
        records = PresentationVerifier._records_from_data(data, request)
        if records:
            return len(records)
        if isinstance(data.get("result"), dict):
            return 1
        return None

    @staticmethod
    def _rows_from_data(data: dict | None, columns: list[str], request: AgentRequest | None = None) -> list[dict[str, Any]]:
        clean_records = PresentationVerifier._records_from_data(data, request)
        if not clean_records:
            return []
        column_list = columns or list(clean_records[0].keys())[:8]
        rows = [{column: record.get(column, "") for column in column_list} for record in clean_records]
        if PresentationVerifier._rows_have_no_values(rows):
            column_list = list(clean_records[0].keys())[:8]
            rows = [{column: record.get(column, "") for column in column_list} for record in clean_records]
        return rows

    @staticmethod
    def _records_from_data(data: dict | None, request: AgentRequest | None = None) -> list[dict[str, Any]]:
        if not data:
            return []
        records = data.get("results") if isinstance(data.get("results"), list) else None
        if records is None and isinstance(data.get("result"), dict):
            records = [data["result"]]
        if not records:
            return []
        clean_records = [
            {
                key: PresentationVerifier._format_display_value(value)
                for key, value in record.items()
                if key != "__metadata"
            }
            for record in records
            if isinstance(record, dict)
        ]
        target_object = request.constraints.target_object if request and request.constraints else None
        object_field = {
            "supplier": "Supplier",
            "customer": "Customer",
            "business_partner": "BusinessPartner",
        }.get(target_object or "")
        if object_field:
            filtered = [
                record
                for record in clean_records
                if record.get(object_field) not in (None, "")
            ]
            if filtered:
                return filtered
        return clean_records

    @staticmethod
    def _rows_have_no_values(rows: list[dict[str, Any]]) -> bool:
        if not rows:
            return True
        return not any(
            value not in ("", None)
            for row in rows
            for value in row.values()
        )

    @staticmethod
    def _format_display_value(value: Any) -> Any:
        return format_sap_json_date_for_display(value)
