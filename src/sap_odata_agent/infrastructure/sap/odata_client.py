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
from itertools import product
from pathlib import Path

from sap_odata_agent.domain.models import (
    CompiledRequest,
    ExecutionAttempt,
    ExecutionStep,
    FilterCondition,
    FunctionParameter,
    QueryPlan,
    ValidationIssue,
)


CDS_VIEW_ONLY_SERVICES = frozenset({"I_PurchaseOrderHistoryAPI01", "I_ProductionVersion"})
AUTO_KEY_SELECT_EXCLUSIONS = {
    ("C_TRIALBALANCE_CDS", "C_TRIALBALANCEResults"): frozenset({"ID"}),
    ("API_GLACCOUNTLINEITEM", "GLAccountLineItem"): frozenset({"ID"}),
}


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
    def __init__(self, cds_view_only_services: frozenset[str] | set[str] | None = None) -> None:
        self.cds_view_only_services = set(cds_view_only_services or CDS_VIEW_ONLY_SERVICES)

    def validate(self, plan: QueryPlan) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if str(plan.service_name or "") in self.cds_view_only_services:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=(
                        f"{plan.service_name} is marked CDS_VIEW_ONLY. It is a CDS view/API view, "
                        "not a SAP Gateway OData service, so it cannot be executed through "
                        "/sap/opu/odata/sap/..."
                    ),
                    field="service_name",
                )
            )

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

        if plan.plan_kind == "function_import" and not plan.function_parameters:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message="Function import plan is missing function parameters.",
                    field="function_parameters",
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
    def __init__(
        self,
        base_url: str,
        cds_view_only_services: frozenset[str] | set[str] | None = None,
        index_root: str | Path | None = None,
        service_runtime_overrides: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cds_view_only_services = set(cds_view_only_services or CDS_VIEW_ONLY_SERVICES)
        self.index_root = Path(index_root) if index_root is not None else None
        self.service_runtime_overrides = dict(service_runtime_overrides or {})
        self._index_runtime_overrides: dict[str, str] | None = None
        self._entity_key_cache: dict[str, dict[str, list[str]]] = {}

    def compile(self, plan: QueryPlan) -> CompiledRequest:
        self._ensure_odata_runtime_service(plan.service_name)

        if plan.plan_kind == "function_import":
            return self._compile_function_import(plan)

        query_parts: list[str] = []

        if plan.select_fields:
            select_fields = self._select_fields_with_entity_keys(
                plan.service_name,
                plan.entity_set,
                [*plan.select_fields, *plan.order_by],
            )
            query_parts.append("$select=" + ",".join(select_fields))

        if plan.filters:
            filter_parts = [self._compile_filter_item(item) for item in plan.filters]
            query_parts.append("$filter=" + " and ".join(filter_parts))

        if plan.order_by:
            query_parts.append("$orderby=" + ",".join(plan.order_by))

        if plan.top is not None:
            query_parts.append(f"$top={plan.top}")

        query_string = "&".join(query_parts)
        path = f"/sap/opu/odata/sap/{self._runtime_service_name(plan.service_name)}/{plan.entity_set}"
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"

        return CompiledRequest(method=plan.http_method, url=url, payload=plan.payload)

    def _ensure_odata_runtime_service(self, service_name: str) -> None:
        if str(service_name or "") in self.cds_view_only_services:
            raise ValueError(
                f"{service_name} is marked CDS_VIEW_ONLY and cannot be compiled as "
                "a /sap/opu/odata/sap/... request."
            )

    def _select_fields_with_entity_keys(
        self,
        service_name: str,
        entity_set: str,
        select_fields: list[str],
    ) -> list[str]:
        excluded_key_fields = self._auto_key_select_exclusions(service_name, entity_set)
        fields: list[str] = []
        for field in select_fields:
            value = str(field)
            if not value.strip() or value in excluded_key_fields or value in fields:
                continue
            fields.append(value)
        existing = set(fields)
        for key_field in self._entity_key_fields(service_name, entity_set):
            if key_field in excluded_key_fields:
                continue
            if key_field and key_field not in existing:
                fields.append(key_field)
                existing.add(key_field)
        return fields

    @staticmethod
    def _auto_key_select_exclusions(service_name: str, entity_set: str) -> frozenset[str]:
        service_key = str(service_name)
        entity_key = str(entity_set)
        exact = AUTO_KEY_SELECT_EXCLUSIONS.get((service_key, entity_key))
        if exact is not None:
            return exact
        if service_key == "C_TRIALBALANCE_CDS" and entity_key.endswith("/Results"):
            return AUTO_KEY_SELECT_EXCLUSIONS.get((service_key, "C_TRIALBALANCEResults"), frozenset())
        return frozenset()

    def _entity_key_fields(self, service_name: str, entity_set: str) -> list[str]:
        if self.index_root is None or not service_name or not entity_set:
            return []
        service_key = str(service_name)
        if service_key not in self._entity_key_cache:
            self._entity_key_cache[service_key] = self._load_entity_key_fields(service_key)
        return list(self._entity_key_cache.get(service_key, {}).get(str(entity_set), []))

    def _load_entity_key_fields(self, service_name: str) -> dict[str, list[str]]:
        if self.index_root is None:
            return {}
        entities_path = self.index_root / service_name / "entities.json"
        if not entities_path.exists():
            return {}
        try:
            records = json.loads(entities_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(records, list):
            return {}
        key_fields_by_entity: dict[str, list[str]] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            entity = str(record.get("entity_set") or "")
            key_fields = [
                str(field)
                for field in (record.get("key_fields") or [])
                if str(field).strip()
            ]
            if entity and key_fields:
                key_fields_by_entity[entity] = key_fields
        return key_fields_by_entity

    def _compile_function_import(self, plan: QueryPlan) -> CompiledRequest:
        query_params = {
            parameter.name: self._compile_function_parameter(parameter)
            for parameter in plan.function_parameters
            if parameter.name
        }
        query_string = urllib.parse.urlencode(query_params, safe="$(),'/:")
        path = f"/sap/opu/odata/sap/{self._runtime_service_name(plan.service_name)}/{plan.entity_set}"
        url = f"{self.base_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"
        return CompiledRequest(method=plan.http_method, url=url, payload=plan.payload)

    def _runtime_service_name(self, service_name: str) -> str:
        normalized = str(service_name or "")
        if normalized in self.service_runtime_overrides:
            return self.service_runtime_overrides[normalized]

        index_overrides = self._load_index_runtime_overrides()
        if normalized in index_overrides:
            return index_overrides[normalized]

        match = re.fullmatch(r"(.+_SRV)_(\d{4})", str(service_name or ""))
        if match:
            return f"{match.group(1)};v={match.group(2)}"
        return service_name

    def _load_index_runtime_overrides(self) -> dict[str, str]:
        if self._index_runtime_overrides is not None:
            return self._index_runtime_overrides
        if self.index_root is None or not self.index_root.exists():
            self._index_runtime_overrides = {}
            return self._index_runtime_overrides

        overrides: dict[str, str] = {}
        for services_path in self.index_root.glob("*/services.json"):
            try:
                records = json.loads(services_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(records, list) or not records:
                continue
            record = records[0]
            if not isinstance(record, dict):
                continue
            index_service_name = str(record.get("service_name") or services_path.parent.name)
            runtime_service_name = self._runtime_service_name_from_index_record(record, index_service_name)
            if runtime_service_name and runtime_service_name != index_service_name:
                overrides[index_service_name] = runtime_service_name

        self._index_runtime_overrides = overrides
        return overrides

    @classmethod
    def _runtime_service_name_from_index_record(cls, record: dict, index_service_name: str) -> str:
        runtime_path_template = str(record.get("runtime_path_template") or "")
        if runtime_path_template:
            if "{service_name}" in runtime_path_template:
                return index_service_name
            runtime_service_name = cls._extract_runtime_service_name(runtime_path_template)
            if runtime_service_name:
                return runtime_service_name

        return cls._extract_runtime_service_name(
            str(record.get("source") or "") or str(record.get("base_path") or "")
        )

    @staticmethod
    def _extract_runtime_service_name(value: str) -> str:
        match = re.search(r"/sap/opu/odata/sap/([^/?#]+)", str(value or "").replace("\\", "/"))
        if not match:
            return ""
        return match.group(1)

    @staticmethod
    def _compile_function_parameter(parameter: FunctionParameter) -> str:
        return BasicODataCompiler._compile_literal(parameter.value, parameter.value_type)

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
                if raw_value is not None
            ]
            return f"({' or '.join(or_parts)})" if or_parts else f"{field} eq ''"
        if str(item.value_type or "").lower() in {"null", "edm.null", "null_keyword", "odata.null"} or str(value).strip().lower() == "null":
            return f"{field} {operator} null"
        escaped = value.replace("'", "''")
        if operator == "contains":
            return f"substringof('{escaped}',{field}) eq true"
        return f"{field} {operator} {BasicODataCompiler._compile_literal(value, item.value_type)}"

    @staticmethod
    def _compile_literal(value: str, value_type: str) -> str:
        normalized_type = str(value_type or "").lower()
        if normalized_type in {"null", "edm.null", "null_keyword", "odata.null"} or str(value).strip().lower() == "null":
            return "null"
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
        if normalized_type in {"decimal", "edm.decimal"}:
            normalized_value = str(value).strip()
            if re.fullmatch(r"-?\d+(\.\d+)?[mM]", normalized_value):
                return normalized_value
            if re.fullmatch(r"-?\d+(\.\d+)?", normalized_value):
                return f"{normalized_value}M"
            return normalized_value
        if normalized_type in {
            "number",
            "integer",
            "int",
            "edm.int16",
            "edm.int32",
            "edm.int64",
            "edm.double",
            "edm.single",
        }:
            return str(value).strip()
        raw_value = str(value).strip()
        if re.fullmatch(r"'([^']|'')*'", raw_value):
            return raw_value
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    @staticmethod
    def _compile_datetime_literal(value: str, literal_type: str) -> str:
        raw_value = str(value).strip()
        wrapper_match = re.fullmatch(r"(?i)(datetimeoffset|datetime)'(.+)'", raw_value)
        if wrapper_match:
            raw_value = wrapper_match.group(2).strip()

        normalized_value = BasicODataCompiler._normalize_datetime_value(raw_value)
        if literal_type == "datetimeoffset" and not re.search(r"(Z|[+-]\d{2}:\d{2})$", normalized_value):
            normalized_value = f"{normalized_value}Z"
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

        new_query = urllib.parse.urlencode(param_map, safe="$(),'/:")
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
                local_has_next = len(displayed_results) < len(results)
                sap_has_next = skip + len(results) < total_count
                next_skip = None
                if local_has_next:
                    next_skip = skip + len(displayed_results)
                elif sap_has_next:
                    next_skip = skip + page_size
                sap_next_skip = skip + len(results) if sap_has_next else None
                return {
                    "result_count": total_count,
                    "returned_count": len(results),
                    "displayed_count": len(displayed_results),
                    "results": displayed_results,
                    "_all_results": results,
                    "_result_window_start": skip,
                    "pagination": {
                        "page_size": page_size,
                        "display_limit": display_limit,
                        "skip": skip,
                        "page_number": (skip // display_limit) + 1 if display_limit > 0 else 1,
                        "has_next": next_skip is not None,
                        "next_skip": next_skip,
                        "local_has_next": local_has_next,
                        "sap_has_next": sap_has_next,
                        "sap_page_size": page_size,
                        "sap_skip": skip,
                        "sap_next_skip": sap_next_skip,
                    },
                }
            if isinstance(data, dict):
                payload_items = {
                    key: value
                    for key, value in data.items()
                    if key != "__metadata"
                }
                if len(payload_items) == 1:
                    name, value = next(iter(payload_items.items()))
                    if isinstance(value, dict):
                        return {"result": value, "function_import": name}
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
            fanout_bindings: list[tuple[str, list[object]]] = []
            for binding in step.filter_from_previous:
                previous_payload = step_results.get(binding.source_step_id)
                values = self._extract_values(previous_payload, binding.source_field)
                if not values:
                    if self._payload_has_no_rows(previous_payload):
                        empty_preview = self._empty_response_preview(step.top)
                        attempt = ExecutionAttempt(
                            attempt_number=attempt_number,
                            request=CompiledRequest(method=step.http_method, url=f"empty://{step.entity_set}"),
                            success=True,
                            step_id=step.step_id,
                            status_code=200,
                            response_preview=empty_preview,
                            extracted_values={},
                            error_message=None,
                        )
                        attempts.append(attempt)
                        step_results[step.step_id] = empty_preview
                        final_data = empty_preview
                        return attempts, self._build_merged_data(plan, attempts, final_data)
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
                if binding.fanout and len(values) > 1:
                    fanout_bindings.append((binding.field, values))
                    extracted_values[binding.field] = values
                    continue
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

            if fanout_bindings:
                fanout_attempts, fanout_data = self._execute_fanout_step(
                    plan=plan,
                    step=step,
                    base_filters=runtime_filters,
                    fanout_bindings=fanout_bindings,
                    starting_attempt_number=attempt_number,
                )
                for attempt in fanout_attempts:
                    attempt.step_id = step.step_id
                    attempt.extracted_values = {**extracted_values, **(attempt.extracted_values or {})}
                attempts.extend(fanout_attempts)
                if any(not attempt.success for attempt in fanout_attempts):
                    return attempts, None
                step_results[step.step_id] = fanout_data or {}
                final_data = fanout_data
                attempt_number += len(fanout_attempts)
                continue

            step_plan = QueryPlan(
                service_name=step.service_name or plan.service_name,
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

        return attempts, self._build_merged_data(plan, attempts, final_data)

    def _execute_fanout_step(
        self,
        *,
        plan: QueryPlan,
        step: ExecutionStep,
        base_filters: list[FilterCondition],
        fanout_bindings: list[tuple[str, list[object]]],
        starting_attempt_number: int,
    ) -> tuple[list[ExecutionAttempt], dict | None]:
        attempts: list[ExecutionAttempt] = []
        previews: list[dict] = []
        fields = [field for field, _values in fanout_bindings]
        value_sets = [[str(value) for value in values] for _field, values in fanout_bindings]
        for offset, values in enumerate(product(*value_sets)):
            fanout_filters = list(base_filters)
            extracted = dict(zip(fields, values, strict=True))
            for field, value in extracted.items():
                fanout_filters.append(FilterCondition(field=field, operator="eq", value=value))
            step_plan = QueryPlan(
                service_name=step.service_name or plan.service_name,
                entity_set=step.entity_set,
                http_method=step.http_method,
                select_fields=step.select_fields,
                response_summary_fields=step.response_summary_fields,
                filters=fanout_filters,
                order_by=step.order_by,
                top=step.top,
                plan_kind="direct",
            )
            compiled = self.compiler.compile(step_plan)
            attempt = self.executor.execute(compiled, starting_attempt_number + offset)
            attempt.extracted_values = extracted
            attempts.append(attempt)
            if not attempt.success:
                return attempts, None
            previews.append(attempt.response_preview or {})
        return attempts, self._merge_fanout_previews(previews, step.top)

    def _merge_fanout_previews(self, previews: list[dict], top: int | None) -> dict:
        all_results: list[dict] = []
        total_count = 0
        for preview in previews:
            results = preview.get("_all_results")
            if not isinstance(results, list):
                results = preview.get("results", [])
            if not isinstance(results, list):
                results = []
            all_results.extend(item for item in results if isinstance(item, dict))
            try:
                total_count += int(preview.get("result_count", len(results)) or 0)
            except (TypeError, ValueError):
                total_count += len(results)
        page_size = top or len(all_results) or 20
        display_limit = min(page_size, self.executor.MAX_PREVIEW_ROWS)
        displayed_results = all_results[:display_limit]
        has_next = len(displayed_results) < len(all_results)
        return {
            "result_count": total_count,
            "returned_count": len(all_results),
            "displayed_count": len(displayed_results),
            "results": displayed_results,
            "_all_results": all_results,
            "_result_window_start": 0,
            "pagination": {
                "page_size": page_size,
                "display_limit": display_limit,
                "skip": 0,
                "page_number": 1,
                "has_next": has_next,
                "next_skip": len(displayed_results) if has_next else None,
            },
        }

    def _build_merged_data(self, plan: QueryPlan, attempts: list[ExecutionAttempt], final_data: dict) -> dict:
        structured_step_results = self._build_step_results(plan, attempts)
        primary_step_id = self._choose_primary_step_id(plan, structured_step_results)
        primary_step = structured_step_results.get(primary_step_id, {}) if primary_step_id else {}
        primary_data = primary_step.get("data") if isinstance(primary_step.get("data"), dict) else final_data
        merged_data = dict(primary_data or final_data)
        merged_data["primary_step_id"] = primary_step_id
        merged_data["primary_entity_set"] = primary_step.get("entity_set") or ""
        merged_data["primary_results"] = merged_data.get("results", [])
        merged_data["final_step_id"] = attempts[-1].step_id if attempts else None
        merged_data["final_step_entity_set"] = next(
            (step.entity_set for step in plan.steps if step.step_id == (attempts[-1].step_id if attempts else None)),
            "",
        )
        merged_data["step_results"] = structured_step_results
        merged_data["result_count_by_step"] = {
            step_id: step_data.get("result_count")
            for step_id, step_data in structured_step_results.items()
        }
        merged_data["execution_trace"] = [
                {
                    "step_id": attempt.step_id,
                    "service_name": next(
                        (
                            step.service_name or plan.service_name
                            for step in plan.steps
                            if step.step_id == attempt.step_id
                        ),
                        plan.service_name,
                    ),
                    "entity_set": next((step.entity_set for step in plan.steps if step.step_id == attempt.step_id), ""),
                    "request_url": attempt.request.url,
                    "status_code": attempt.status_code,
                "success": attempt.success,
                "extracted_values": attempt.extracted_values,
            }
            for attempt in attempts
        ]
        merged_data["source_step_summaries"] = self._build_source_step_summaries(plan, attempts)
        merged_data["lookup_context"] = {
            "path_id": plan.path_id,
            "anchor_object": plan.anchor_object,
            "anchor_value": plan.anchor_value,
            "target_field": plan.target_field,
            "target_entity_set": plan.target_entity_set or plan.entity_set,
            "primary_step_id": primary_step_id,
            "primary_entity_set": primary_step.get("entity_set") or "",
            "final_step_id": attempts[-1].step_id if attempts else None,
            "final_step_entity_set": merged_data["final_step_entity_set"],
        }
        return merged_data

    @staticmethod
    def _payload_has_no_rows(data: dict | None) -> bool:
        if not data:
            return False
        for key in ("_all_results", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value) == 0
        try:
            return int(data.get("result_count", -1)) == 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _empty_response_preview(top: int | None = None) -> dict:
        page_size = int(top or 50)
        return {
            "result_count": 0,
            "returned_count": 0,
            "displayed_count": 0,
            "results": [],
            "_all_results": [],
            "_result_window_start": 0,
            "pagination": {
                "page_size": page_size,
                "display_limit": min(page_size, 50),
                "skip": 0,
                "page_number": 1,
                "has_next": False,
                "next_skip": None,
            },
        }

    @staticmethod
    def _extract_values(data: dict | None, field_name: str) -> list[object]:
        if not data:
            return []
        results = data.get("_all_results")
        if not isinstance(results, list) or not results:
            results = data.get("results")
        if isinstance(results, list) and results:
            values = [
                row.get(field_name)
                for row in results
                if isinstance(row, dict) and field_name in row and row.get(field_name) is not None
            ]
            return list(dict.fromkeys(values))
        result = data.get("result")
        if isinstance(result, dict):
            if field_name not in result:
                return []
            value = result.get(field_name)
            return [value] if value is not None else []
        return []

    @staticmethod
    def _build_source_step_summaries(plan: QueryPlan, attempts: list[ExecutionAttempt]) -> list[dict]:
        summaries: list[dict] = []
        step_by_id = {step.step_id: step for step in plan.steps}
        for attempt in attempts:
            step = step_by_id.get(attempt.step_id or "")
            preview = attempt.response_preview or {}
            summaries.append(
                {
                    "step_id": attempt.step_id,
                    "service_name": step.service_name or plan.service_name if step else plan.service_name,
                    "entity_set": step.entity_set if step else "",
                    "select_fields": list(step.select_fields) if step else [],
                    "filters": [
                        {
                            "field": item.field,
                            "operator": item.operator,
                            "value": item.value,
                            "value_type": item.value_type,
                        }
                        for item in (step.filters if step else [])
                    ],
                    "result_count": preview.get("result_count"),
                    "returned_count": preview.get("returned_count"),
                    "displayed_count": preview.get("displayed_count"),
                }
            )
        return summaries

    @staticmethod
    def _build_step_results(plan: QueryPlan, attempts: list[ExecutionAttempt]) -> dict[str, dict]:
        step_by_id = {step.step_id: step for step in plan.steps}
        results: dict[str, dict] = {}
        for attempt in attempts:
            if not attempt.step_id:
                continue
            step = step_by_id.get(attempt.step_id)
            preview = attempt.response_preview or {}
            results[attempt.step_id] = {
                "step_id": attempt.step_id,
                "service_name": step.service_name or plan.service_name if step else plan.service_name,
                "entity_set": step.entity_set if step else "",
                "select_fields": list(step.select_fields) if step else [],
                "result_count": preview.get("result_count"),
                "returned_count": preview.get("returned_count"),
                "displayed_count": preview.get("displayed_count"),
                "results": preview.get("results", []) if isinstance(preview.get("results"), list) else [],
                "pagination": preview.get("pagination", {}),
                "data": preview,
            }
        return results

    @staticmethod
    def _choose_primary_step_id(plan: QueryPlan, step_results: dict[str, dict]) -> str:
        target_entity = plan.target_entity_set or plan.entity_set
        if target_entity:
            for step in plan.steps:
                if step.entity_set == target_entity and step.step_id in step_results:
                    return step.step_id
        if plan.steps and plan.steps[-1].step_id in step_results:
            return plan.steps[-1].step_id
        return next(iter(step_results.keys()), "")


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
