from __future__ import annotations

import json
from typing import Any

from sap_odata_agent.domain.models import AgentRequest, QueryPlan, ResultPresentation
from sap_odata_agent.infrastructure.llm.planner import AnthropicCompatibleMessagesClient, LlmStructuredIntentPlanner
from sap_odata_agent.infrastructure.llm.prompts import GLOBAL_SAP_ODATA_PROMPT, RESULT_PRESENTER_TASK_PROMPT
from sap_odata_agent.infrastructure.sap.date_formatting import format_sap_json_date_for_display


class LlmResultPresenter:
    def __init__(
        self,
        llm_client: AnthropicCompatibleMessagesClient | None = None,
        enabled: bool = True,
    ) -> None:
        self.llm_client = llm_client
        self.enabled = enabled

    def present(self, request: AgentRequest, plan: QueryPlan, data: dict[str, Any] | None) -> ResultPresentation:
        raw_records = self._extract_records(data)
        records = self._filter_records_for_target_object(request, raw_records)
        fallback = self._build_fallback_presentation(request, plan, records, data)
        if not self.enabled or self.llm_client is None or not data:
            return fallback

        try:
            raw = self.llm_client.complete_json(
                self._build_system_prompt(),
                self._build_user_prompt(request, plan, data, records, raw_records),
                max_tokens=900,
            )
            parsed = LlmStructuredIntentPlanner._parse_json_object(raw)
            return self._materialize_presentation(parsed, records, fallback)
        except Exception:
            return fallback

    @staticmethod
    def _build_system_prompt() -> str:
        return f"{GLOBAL_SAP_ODATA_PROMPT}\n\n{RESULT_PRESENTER_TASK_PROMPT}"

    def _build_user_prompt(
        self,
        request: AgentRequest,
        plan: QueryPlan,
        data: dict[str, Any],
        records: list[dict[str, Any]],
        raw_records: list[dict[str, Any]],
    ) -> str:
        example = {
            "kind": "text",
            "title": "查询结果",
            "text": "根据返回数据，目标对象在指定条件下的请求字段值为示例值。",
            "columns": [],
            "rows": [],
        }
        table_example = {
            "kind": "table",
            "title": "查询结果",
            "text": "以下是满足查询条件的结果列表。",
            "columns": ["ObjectId", "ObjectName", "RequestedField"],
            "rows": [
                {"ObjectId": "100001", "ObjectName": "Example A", "RequestedField": "Value 1"},
                {"ObjectId": "100002", "ObjectName": "Example B", "RequestedField": "Value 2"},
            ],
        }
        payload = {
            "latest_user_input": request.user_input,
            "resolved_user_input": request.resolved_user_input or request.user_input,
            "plan_kind": plan.plan_kind,
            "path_id": plan.path_id,
            "entity_set": plan.entity_set,
            "target_field": plan.target_field,
            "target_entity_set": plan.target_entity_set,
            "response_summary_fields": plan.response_summary_fields,
            "function_parameters": [
                {"name": item.name, "value": item.value, "value_type": item.value_type}
                for item in getattr(plan, "function_parameters", [])
            ],
            "result_transform": (
                {
                    "type": plan.result_transform.type,
                    "group_by": plan.result_transform.group_by,
                    "sum_fields": plan.result_transform.sum_fields,
                }
                if plan.result_transform is not None
                else None
            ),
            "response_directive": plan.response_directive,
            "result_count": self._total_count(data, records),
            "displayed_count": len(records),
            "raw_result_count": self._total_count(data, raw_records),
            "records": records[:50],
            "lookup_context": (data or {}).get("lookup_context"),
            "execution_trace": (data or {}).get("execution_trace"),
            "source_step_summaries": (data or {}).get("source_step_summaries", []),
            "step_results": self._summarize_step_results((data or {}).get("step_results")),
            "raw_data_summary": {
                "sap_raw_result_count": (data or {}).get("result_count"),
                "sap_displayed_count": (data or {}).get("displayed_count"),
                "primary_entity_set": (data or {}).get("primary_entity_set"),
                "final_step_entity_set": (data or {}).get("final_step_entity_set"),
                "result_transform": (data or {}).get("result_transform"),
                "has_results": bool(raw_records),
            },
        }
        return (
            "Render the query result for this SAP user request:\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Choose the best presentation format:\n"
            "- Use text when the user asked for a single fact or short answer.\n"
            "- Use table when the user asked for a list, comparison, ranking, or multiple rows.\n"
            "- Keep answers in the same natural language as latest_user_input. If latest_user_input is Chinese, answer in Chinese.\n"
            "- Prefer concise business wording instead of raw field names when you can do so faithfully.\n\n"
            "- Do not invent values that are not returned by SAP.\n"
            "- Preserve SAP codes exactly as returned.\n\n"
            "- For multi_step plans, inspect step_results and source_step_summaries. Do not present only the final step unless the plan explicitly makes that final step the answer.\n"
            "- If the user asked for history and step_results only contains detail data such as pricing, notes, or account assignments, state that limitation rather than titling it as history.\n\n"
            f"Text example:\n{json.dumps(example, ensure_ascii=False, indent=2)}\n\n"
            f"Table example:\n{json.dumps(table_example, ensure_ascii=False, indent=2)}"
        )

    def _materialize_presentation(
        self,
        parsed: dict[str, Any],
        records: list[dict[str, Any]],
        fallback: ResultPresentation,
    ) -> ResultPresentation:
        kind = str(parsed.get("kind", fallback.kind)).lower()
        if kind not in {"text", "table"}:
            kind = fallback.kind

        title = parsed.get("title")
        if not isinstance(title, str) or not title.strip():
            title = fallback.title

        text = parsed.get("text")
        if not isinstance(text, str) or not text.strip():
            text = fallback.text

        columns = [value for value in parsed.get("columns", []) if isinstance(value, str) and value.strip()]
        rows = []
        for row in parsed.get("rows", []):
            if not isinstance(row, dict):
                continue
            clean_row = {str(key): self._format_display_value(row[key]) for key in row.keys() if isinstance(key, str)}
            if clean_row:
                rows.append(clean_row)

        if kind == "table":
            text = fallback.text
            if not columns and rows:
                columns = [column for column in rows[0].keys()]
            if not rows or self._rows_have_no_values(rows):
                fallback_columns = fallback.columns or (list(fallback.rows[0].keys()) if fallback.rows else [])
                fallback_rows = self._build_table_rows(records, fallback_columns)
                if fallback_rows:
                    rows = fallback_rows
                    columns = fallback_columns
                    text = fallback.text
            if rows and len(rows) < min(len(records), 50):
                fallback_columns = fallback.columns or columns
                fallback_rows = self._build_table_rows(records, fallback_columns)
                if len(fallback_rows) > len(rows):
                    rows = fallback_rows
                    columns = fallback_columns
                    text = fallback.text
            if not columns and rows:
                columns = list(rows[0].keys())
            if not rows or not columns:
                return fallback

        return ResultPresentation(
            kind=kind,
            title=title,
            text=text,
            columns=columns,
            rows=rows[:50],
        )

    def _build_fallback_presentation(
        self,
        request: AgentRequest,
        plan: QueryPlan,
        records: list[dict[str, Any]],
        data: dict[str, Any] | None = None,
    ) -> ResultPresentation:
        if not records:
            return ResultPresentation(
                kind="text",
                title="查询结果",
                text=f"查询已执行，但没有找到与“{request.user_input}”匹配的数据。",
            )

        summary_fields = plan.response_summary_fields or plan.select_fields
        if len(records) == 1:
            record = records[0]
            boolean_answer = self._build_boolean_answer(request, plan, record, summary_fields)
            if boolean_answer:
                return ResultPresentation(
                    kind="text",
                    title="查询结果",
                    text=boolean_answer,
                )
            fragments = []
            for field_name in summary_fields[:4]:
                if field_name in record:
                    fragments.append(f"{field_name}为{record[field_name]}")
            if not fragments:
                for key, value in list(record.items())[:3]:
                    fragments.append(f"{key}为{value}")
            return ResultPresentation(
                kind="text",
                title="查询结果",
                text=f"针对“{request.user_input}”，当前查询结果显示：{'，'.join(fragments)}。",
            )

        columns = [field for field in summary_fields if any(field in record for record in records)]
        if not columns:
            columns = list(records[0].keys())[:5]
        rows = self._build_table_rows(records, columns)
        return ResultPresentation(
            kind="table",
            title="查询结果",
            text=self._build_table_summary_text(
                request,
                self._total_count(data, records),
                len(rows),
                self._pagination_skip(data),
            ),
            columns=columns,
            rows=rows[:50],
        )

    @staticmethod
    def _build_boolean_answer(
        request: AgentRequest,
        plan: QueryPlan,
        record: dict[str, Any],
        summary_fields: list[str],
    ) -> str | None:
        if not any(term in request.user_input for term in ("吗", "是否", "是不是", "有无", "对吗")):
            return None
        boolean_fields = [
            field_name
            for field_name in [*summary_fields, *plan.select_fields]
            if field_name in record and isinstance(record.get(field_name), (bool, str, int))
        ]
        for field_name in boolean_fields:
            normalized = LlmResultPresenter._normalize_boolean(record.get(field_name))
            if normalized is None:
                continue
            identifier_label = "对象"
            identifier_value = ""
            for candidate in [*summary_fields, *plan.select_fields]:
                value = record.get(candidate)
                if candidate != field_name and value not in ("", None):
                    identifier_label = candidate
                    identifier_value = value
                    break

            context_parts = []
            for candidate in [*summary_fields, *plan.select_fields]:
                value = record.get(candidate)
                if candidate in {field_name, identifier_label} or value in ("", None):
                    continue
                context_parts.append(f"{candidate}={value}")
            context = f"（{', '.join(context_parts[:2])}）" if context_parts else ""

            if normalized:
                return f"{identifier_label}{identifier_value}{context}：是。"
            return f"{identifier_label}{identifier_value}{context}：否。"
        return None

    @staticmethod
    def _build_table_summary_text(
        request: AgentRequest,
        total_count: int,
        displayed_count: int,
        skip: int = 0,
    ) -> str:
        if skip <= 0:
            return f"查询结果总共{total_count}条，当前显示前{displayed_count}条"
        start = skip + 1
        end = skip + displayed_count
        return f"查询结果总共{total_count}条，当前显示第{start}-{end}条"

    @staticmethod
    def _normalize_boolean(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value in {0, 1}:
                return bool(value)
            return None
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "x", "yes", "y", "1"}:
                return True
            if lowered in {"false", "", "no", "n", "0"}:
                return False
        return None

    @staticmethod
    def _extract_records(data: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not data:
            return []
        if isinstance(data.get("results"), list):
            return [
                {
                    key: LlmResultPresenter._format_display_value(value)
                    for key, value in row.items()
                    if key != "__metadata"
                }
                for row in data["results"]
                if isinstance(row, dict)
            ]
        result = data.get("result")
        if isinstance(result, dict):
            return [
                {
                    key: LlmResultPresenter._format_display_value(value)
                    for key, value in result.items()
                    if key != "__metadata"
                }
            ]
        return []

    @staticmethod
    def _format_display_value(value: Any) -> Any:
        return format_sap_json_date_for_display(value)

    @staticmethod
    def _summarize_step_results(step_results: Any) -> dict[str, Any]:
        if not isinstance(step_results, dict):
            return {}
        summary: dict[str, Any] = {}
        for step_id, value in step_results.items():
            if not isinstance(value, dict):
                continue
            raw_rows = value.get("results", []) if isinstance(value.get("results"), list) else []
            rows = []
            for row in raw_rows[:10]:
                if not isinstance(row, dict):
                    continue
                rows.append(
                    {
                        key: LlmResultPresenter._format_display_value(field_value)
                        for key, field_value in row.items()
                        if key != "__metadata"
                    }
                )
            summary[str(step_id)] = {
                "entity_set": value.get("entity_set"),
                "result_count": value.get("result_count"),
                "displayed_count": value.get("displayed_count"),
                "results": rows,
            }
        return summary

    @staticmethod
    def _total_count(data: dict[str, Any] | None, records: list[dict[str, Any]]) -> int:
        if not data:
            return len(records)
        raw_results = data.get("results") if isinstance(data.get("results"), list) else None
        if raw_results is not None and len(records) != len(raw_results):
            return len(records)
        try:
            return int(str(data.get("result_count")))
        except (TypeError, ValueError):
            return len(records)

    @staticmethod
    def _pagination_skip(data: dict[str, Any] | None) -> int:
        pagination = data.get("pagination") if data else None
        if not isinstance(pagination, dict):
            return 0
        try:
            return max(0, int(str(pagination.get("skip") or 0)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _filter_records_for_target_object(
        request: AgentRequest,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        target_object = request.constraints.target_object if request.constraints else None
        object_field = {
            "supplier": "Supplier",
            "customer": "Customer",
            "business_partner": "BusinessPartner",
        }.get(target_object or "")
        if not object_field:
            return records
        filtered = [
            record
            for record in records
            if record.get(object_field) not in (None, "")
        ]
        return filtered or records

    @staticmethod
    def _build_table_rows(records: list[dict[str, Any]], columns: list[str] | Any) -> list[dict[str, Any]]:
        column_list = [str(column) for column in columns]
        rows: list[dict[str, Any]] = []
        for record in records[:50]:
            row = {column: record.get(column, "") for column in column_list}
            if any(value not in ("", None) for value in row.values()):
                rows.append(row)
        return rows

    @staticmethod
    def _rows_have_no_values(rows: list[dict[str, Any]]) -> bool:
        if not rows:
            return True
        return not any(
            value not in ("", None)
            for row in rows
            for value in row.values()
        )
