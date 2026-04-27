from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from sap_odata_agent.domain.models import CompiledRequest, ExecutionAttempt, FilterCondition, QueryPlan, ValidationIssue


@dataclass(slots=True)
class SapRuntimeConfig:
    base_url: str
    username: str
    password: str
    client: str = ""
    verify_ssl: bool = True
    auth_type: str = "basic"
    timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_delay_seconds: float = 0.4


class BasicPlanValidator:
    def validate(self, plan: QueryPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if plan.service_name.startswith("UNKNOWN"):
            issues.append(
                ValidationIssue(
                    severity="error",
                    message="Planner did not resolve a valid SAP OData service.",
                    field="service_name",
                )
            )

        if plan.entity_set.startswith("UNKNOWN"):
            issues.append(
                ValidationIssue(
                    severity="error",
                    message="Planner did not resolve a valid entity set.",
                    field="entity_set",
                )
            )

        if plan.http_method != "GET":
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message="Only GET requests are enabled in the current MVP.",
                    field="http_method",
                )
            )

        if plan.requires_confirmation:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    message="This request should require human confirmation before execution.",
                )
            )

        if plan.plan_kind in {"lookup", "multi_step"}:
            if not plan.steps:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        message="Lookup or multi-step plan is missing execution steps.",
                        field="steps",
                    )
                )
            for step in plan.steps:
                if not step.entity_set:
                    issues.append(
                        ValidationIssue(
                            severity="error",
                            message="Execution step is missing an entity set.",
                            field="steps",
                        )
                    )

        return issues


class BasicODataCompiler:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def compile(self, plan: QueryPlan) -> CompiledRequest:
        query_parts: list[str] = []

        if plan.select_fields:
            query_parts.append("$select=" + ",".join(plan.select_fields))

        if plan.filters:
            filter_parts = [self._compile_filter_item(item) for item in plan.filters]
            query_parts.append("$filter=" + " and ".join(filter_parts))

        if plan.order_by:
            query_parts.append("$orderby=" + ",".join(plan.order_by))

        if plan.top is not None:
            query_parts.append(f"$top={plan.top}")

        query_string = "&".join(query_parts)
        path = f"/sap/opu/odata/sap/{plan.service_name}/{plan.entity_set}"
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"

        return CompiledRequest(method=plan.http_method, url=url, payload=plan.payload)

    @staticmethod
    def _compile_filter_item(item: FilterCondition) -> str:
        field = item.field
        operator = item.operator
        value = item.value
        if operator == "in":
            try:
                values = json.loads(value)
            except json.JSONDecodeError:
                values = [item.strip() for item in value.split("|") if item.strip()]
            or_parts = [
                f"{field} eq {BasicODataCompiler._compile_literal(str(raw_value), item.value_type)}"
                for raw_value in values
                if str(raw_value)
            ]
            return f"({' or '.join(or_parts)})" if or_parts else f"{field} eq ''"
        escaped = value.replace("'", "''")
        if operator == "contains":
            return f"substringof('{escaped}',{field}) eq true"
        return f"{field} {operator} {BasicODataCompiler._compile_literal(value, item.value_type)}"

    @staticmethod
    def _compile_literal(value: str, value_type: str) -> str:
        normalized_type = str(value_type or "").lower()
        if normalized_type in {"boolean", "bool", "edm.boolean"}:
            normalized_value = str(value).strip().lower()
            if normalized_value in {"true", "1", "yes"}:
                return "true"
            if normalized_value in {"false", "0", "no"}:
                return "false"
        if normalized_type in {"date", "datetime", "edm.date", "edm.datetime"}:
            return BasicODataCompiler._compile_datetime_literal(value, literal_type="datetime")
        if normalized_type in {"datetimeoffset", "edm.datetimeoffset"}:
            return BasicODataCompiler._compile_datetime_literal(value, literal_type="datetimeoffset")
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    @staticmethod
    def _compile_datetime_literal(value: str, literal_type: str) -> str:
        raw_value = str(value).strip()
        wrapper_match = re.fullmatch(r"(?i)(datetimeoffset|datetime)'(.+)'", raw_value)
        if wrapper_match:
            raw_value = wrapper_match.group(2).strip()

        normalized_value = BasicODataCompiler._normalize_datetime_value(raw_value)
        return f"{literal_type}'{normalized_value}'"

    @staticmethod
    def _normalize_datetime_value(value: str) -> str:
        raw_value = value.strip().strip("'")
        date_match = re.fullmatch(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw_value)
        if date_match:
            year, month, day = date_match.groups()
            return f"{year}-{int(month):02d}-{int(day):02d}T00:00:00"

        datetime_match = re.fullmatch(
            r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})[T ](\d{1,2}):(\d{1,2}):(\d{1,2})(\.\d+)?",
            raw_value,
        )
        if datetime_match:
            year, month, day, hour, minute, second, fraction = datetime_match.groups()
            suffix = fraction or ""
            return (
                f"{year}-{int(month):02d}-{int(day):02d}"
                f"T{int(hour):02d}:{int(minute):02d}:{int(second):02d}{suffix}"
            )

        return raw_value


class SapODataExecutor:
    """Runtime SAP executor for read-only GET requests."""

    MAX_PREVIEW_ROWS = 50

    def __init__(self, config: SapRuntimeConfig) -> None:
        self.config = config

    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        if not compiled_request.url.startswith("http"):
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=False,
                status_code=None,
                response_preview=None,
                error_message="SAP base URL is not configured.",
            )

        if self.config.auth_type.lower() != "basic":
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=False,
                status_code=None,
                response_preview=None,
                error_message=f"Unsupported SAP auth type: {self.config.auth_type}",
            )

        if compiled_request.method != "GET":
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=False,
                status_code=None,
                response_preview=None,
                error_message="Only GET requests are enabled in the current MVP executor.",
            )

        runtime_url = self._prepare_runtime_url(compiled_request.url)
        runtime_request = CompiledRequest(
            method=compiled_request.method,
            url=runtime_url,
            payload=compiled_request.payload,
        )

        try:
            response = self._perform_request_with_retries(runtime_request)
            parsed_payload = self._parse_response_body(response["body"], response["content_type"])
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=runtime_request,
                success=True,
                status_code=response["status_code"],
                response_preview=self._build_preview(parsed_payload, runtime_request.url),
                error_message=None,
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            error_message = self._extract_error_message(body, exc.headers.get("Content-Type", ""))
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=runtime_request,
                success=False,
                status_code=exc.code,
                response_preview=None,
                error_message=error_message,
            )
        except urllib.error.URLError as exc:
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=runtime_request,
                success=False,
                status_code=None,
                response_preview=None,
                error_message=f"SAP request failed: {exc.reason}",
            )
        except Exception as exc:  # pragma: no cover - defensive catch for runtime safety
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=runtime_request,
                success=False,
                status_code=None,
                response_preview=None,
                error_message=f"Unexpected SAP execution error: {exc}",
            )

    def _perform_request_with_retries(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
        attempts = max(1, self.config.retry_attempts)
        delay = max(0.0, self.config.retry_delay_seconds)
        last_error: urllib.error.URLError | None = None
        for index in range(attempts):
            try:
                return self._perform_request(compiled_request)
            except urllib.error.URLError as exc:
                last_error = exc
                if index >= attempts - 1:
                    break
                time.sleep(delay * (index + 1))
        if last_error is not None:
            raise last_error
        raise urllib.error.URLError("SAP request failed before any attempt was executed.")

    def _prepare_runtime_url(self, url: str) -> str:
        split = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        param_map: dict[str, str] = {}
        for key, value in params:
            param_map[key] = value

        if self.config.client and "sap-client" not in param_map:
            param_map["sap-client"] = self.config.client
        if "$format" not in param_map:
            param_map["$format"] = "json"
        if "$top" in param_map and "$inlinecount" not in param_map:
            param_map["$inlinecount"] = "allpages"

        new_query = urllib.parse.urlencode(param_map, safe="$(),'/")
        return urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, new_query, split.fragment))

    def _perform_request(self, compiled_request: CompiledRequest) -> dict[str, str | int]:
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        base_origin = f"{urllib.parse.urlsplit(self.config.base_url).scheme}://{urllib.parse.urlsplit(self.config.base_url).netloc}"
        password_mgr.add_password(None, base_origin, self.config.username, self.config.password)
        auth_handler = urllib.request.HTTPBasicAuthHandler(password_mgr)

        handlers: list[urllib.request.BaseHandler] = [auth_handler]
        if compiled_request.url.lower().startswith("https://") and not self.config.verify_ssl:
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))

        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(
            compiled_request.url,
            headers={
                "Accept": "application/json",
                "DataServiceVersion": "2.0",
                "MaxDataServiceVersion": "2.0",
            },
            method=compiled_request.method,
        )
        with opener.open(request, timeout=self.config.timeout_seconds) as response:
            return {
                "status_code": response.getcode(),
                "content_type": response.headers.get("Content-Type", ""),
                "body": response.read().decode("utf-8", errors="ignore"),
            }

    @staticmethod
    def _parse_response_body(body: str, content_type: str) -> dict:
        if "json" in content_type.lower():
            return json.loads(body)
        return {"raw_body": body}

    def _build_preview(self, payload: dict, url: str = "") -> dict:
        if "d" in payload:
            data = payload["d"]
            if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
                results = data["results"]
                page_size = self._requested_page_size(url)
                skip = self._requested_skip(url)
                display_limit = min(page_size, self.MAX_PREVIEW_ROWS)
                displayed_results = results[:display_limit]
                total_count = self._parse_total_count(data.get("__count"), len(results))
                return {
                    "result_count": total_count,
                    "returned_count": len(results),
                    "displayed_count": len(displayed_results),
                    "results": displayed_results,
                    "pagination": {
                        "page_size": page_size,
                        "display_limit": display_limit,
                        "skip": skip,
                        "page_number": (skip // page_size) + 1 if page_size > 0 else 1,
                        "has_next": skip + len(results) < total_count,
                        "next_skip": skip + page_size if skip + len(results) < total_count else None,
                    },
                }
            return {"result": data}
        return payload

    @staticmethod
    def _requested_page_size(url: str) -> int:
        split = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(split.query, keep_blank_values=True))
        try:
            value = int(params.get("$top", "") or 0)
        except ValueError:
            value = 0
        return value if value > 0 else SapODataExecutor.MAX_PREVIEW_ROWS

    @staticmethod
    def _requested_skip(url: str) -> int:
        split = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(split.query, keep_blank_values=True))
        try:
            value = int(params.get("$skip", "") or 0)
        except ValueError:
            value = 0
        return max(0, value)

    @staticmethod
    def _parse_total_count(raw_count: object, fallback: int) -> int:
        try:
            return int(str(raw_count))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _extract_error_message(body: str, content_type: str) -> str:
        lowered_type = content_type.lower()
        if "json" in lowered_type:
            try:
                payload = json.loads(body)
                return (
                    payload.get("error", {})
                    .get("message", {})
                    .get("value")
                    or payload.get("error", {}).get("message")
                    or body
                )
            except json.JSONDecodeError:
                return body

        if "xml" in lowered_type:
            try:
                root = ET.fromstring(body)
                namespace = {"m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"}
                message = root.find(".//m:message", namespace)
                if message is not None and message.text:
                    return message.text
            except ET.ParseError:
                pass

        return body or "SAP request failed with an empty error body."


class MultiStepSapExecutor:
    def __init__(self, compiler: BasicODataCompiler, executor: SapODataExecutor) -> None:
        self.compiler = compiler
        self.executor = executor

    def execute_plan(self, plan: QueryPlan, starting_attempt_number: int = 1) -> tuple[list[ExecutionAttempt], dict | None]:
        attempts: list[ExecutionAttempt] = []
        if not plan.steps:
            return attempts, None

        step_results: dict[str, dict] = {}
        final_data: dict | None = None
        attempt_number = starting_attempt_number

        for step in plan.steps:
            runtime_filters = list(step.filters)
            extracted_values: dict[str, object] = {}
            for binding in step.filter_from_previous:
                previous_payload = step_results.get(binding.source_step_id)
                values = self._extract_values(previous_payload, binding.source_field)
                if not values:
                    attempt = ExecutionAttempt(
                        attempt_number=attempt_number,
                        request=CompiledRequest(method=step.http_method, url=f"unresolved://{step.entity_set}"),
                        success=False,
                        step_id=step.step_id,
                        status_code=None,
                        response_preview=None,
                        extracted_values={},
                        error_message=(
                            f"Step `{step.step_id}` could not resolve `{binding.field}` from "
                            f"`{binding.source_step_id}.{binding.source_field}`."
                        ),
                    )
                    attempts.append(attempt)
                    return attempts, None
                if len(values) == 1:
                    runtime_filters.append(
                        FilterCondition(
                            field=binding.field,
                            operator="eq",
                            value=str(values[0]),
                        )
                    )
                    extracted_values[binding.field] = values[0]
                else:
                    runtime_filters.append(
                        FilterCondition(
                            field=binding.field,
                            operator="in",
                            value=json.dumps([str(value) for value in values], ensure_ascii=False),
                        )
                    )
                    extracted_values[binding.field] = values

            step_plan = QueryPlan(
                service_name=plan.service_name,
                entity_set=step.entity_set,
                http_method=step.http_method,
                select_fields=step.select_fields,
                response_summary_fields=step.response_summary_fields,
                filters=runtime_filters,
                order_by=step.order_by,
                top=step.top,
                plan_kind="direct",
            )
            compiled = self.compiler.compile(step_plan)
            attempt = self.executor.execute(compiled, attempt_number)
            attempt.step_id = step.step_id
            attempt.extracted_values = extracted_values
            attempts.append(attempt)
            if not attempt.success:
                return attempts, None
            step_results[step.step_id] = attempt.response_preview or {}
            final_data = attempt.response_preview
            attempt_number += 1

        if final_data is None:
            return attempts, None

        merged_data = dict(final_data)
        merged_data["execution_trace"] = [
            {
                "step_id": attempt.step_id,
                "entity_set": next((step.entity_set for step in plan.steps if step.step_id == attempt.step_id), ""),
                "request_url": attempt.request.url,
                "status_code": attempt.status_code,
                "success": attempt.success,
                "extracted_values": attempt.extracted_values,
            }
            for attempt in attempts
        ]
        merged_data["lookup_context"] = {
            "path_id": plan.path_id,
            "anchor_object": plan.anchor_object,
            "anchor_value": plan.anchor_value,
            "target_field": plan.target_field,
            "target_entity_set": plan.target_entity_set or plan.entity_set,
        }
        return attempts, merged_data

    @staticmethod
    def _extract_values(data: dict | None, field_name: str) -> list[object]:
        if not data:
            return []
        results = data.get("results")
        if isinstance(results, list) and results:
            values = [row.get(field_name) for row in results if isinstance(row, dict) and row.get(field_name) not in (None, "")]
            return list(dict.fromkeys(values))
        result = data.get("result")
        if isinstance(result, dict):
            value = result.get(field_name)
            return [value] if value not in (None, "") else []
        return []


class SapExecutorStub:
    """Stub executor retained for isolated tests or local scaffolding."""

    def execute(self, compiled_request: CompiledRequest, attempt_number: int) -> ExecutionAttempt:
        if not compiled_request.url.startswith("http"):
            return ExecutionAttempt(
                attempt_number=attempt_number,
                request=compiled_request,
                success=False,
                status_code=None,
                response_preview=None,
                error_message="SAP base URL is not configured.",
            )

        return ExecutionAttempt(
            attempt_number=attempt_number,
            request=compiled_request,
            success=True,
            status_code=200,
            response_preview={
                "message": "Stub execution succeeded.",
                "compiled_url": compiled_request.url,
            },
            error_message=None,
        )
