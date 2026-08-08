from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from sap_odata_agent.agent_tools.client import DEFAULT_BASE_URL, DEFAULT_TIMEOUT_SECONDS


JsonPayload = dict[str, Any]
RuntimeTransport = Callable[
    [str, str, JsonPayload | None, float, dict[str, str]],
    tuple[int, dict[str, str], bytes],
]


@dataclass(slots=True)
class RuntimeClientError(Exception):
    message: str
    error_type: str = "client_error"
    status_code: int | None = None
    detail: Any = None
    method: str = ""
    url: str = ""

    def __str__(self) -> str:
        return self.message

    def to_payload(self) -> JsonPayload:
        payload: JsonPayload = {"type": self.error_type, "message": self.message}
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.detail not in (None, ""):
            payload["detail"] = self.detail
        if self.method:
            payload["method"] = self.method
        if self.url:
            payload["url"] = self.url
        return payload


class SapClawRuntimeClient:
    """HTTP client for the local, read-only Thin Runtime endpoints."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        api_key: str | None = None,
        transport: RuntimeTransport | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_seconds = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)
        self.api_key = api_key if api_key is not None else os.getenv("SAPCLAW_API_KEY", "")
        self._transport = transport or _urllib_runtime_transport

    def health(self) -> JsonPayload:
        return self._request_json("GET", "/api/v1/runtime/health")

    def catalog(self, query: str = "", skip: int = 0, limit: int = 20) -> JsonPayload:
        return self._request_json(
            "POST",
            "/api/v1/runtime/catalog",
            {"query": query, "skip": skip, "limit": limit},
        )

    def schema(
        self,
        service_name: str,
        entity_sets: list[str] | None = None,
        query: str = "",
        include_fields: bool = True,
        max_fields: int = 500,
    ) -> JsonPayload:
        return self._request_json(
            "POST",
            "/api/v1/runtime/schema",
            {
                "service_name": service_name,
                "entity_sets": entity_sets or [],
                "query": query,
                "include_fields": include_fields,
                "max_fields": max_fields,
            },
        )

    def guidance(
        self,
        user_input: str,
        service_names: list[str] | None = None,
        max_feedback_memories: int = 5,
    ) -> JsonPayload:
        return self._request_json(
            "POST",
            "/api/v1/runtime/guidance",
            {
                "user_input": user_input,
                "service_names": service_names or [],
                "max_feedback_memories": max_feedback_memories,
            },
        )

    def validate_plan(self, plan: JsonPayload, user_input: str = "") -> JsonPayload:
        return self._request_json(
            "POST",
            "/api/v1/runtime/validate-plan",
            {"plan": plan, "user_input": user_input},
        )

    def execute_plan(
        self,
        plan: JsonPayload,
        user_input: str = "",
        conversation_id: str | None = None,
    ) -> JsonPayload:
        payload: JsonPayload = {"plan": plan, "user_input": user_input}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return self._request_json("POST", "/api/v1/runtime/execute-plan", payload)

    def execute_get(
        self,
        service_name: str,
        resource_path: str,
        query_options: dict[str, str] | None = None,
        function_parameters: dict[str, str] | None = None,
        output_contract: JsonPayload | None = None,
        user_input: str = "",
        conversation_id: str | None = None,
    ) -> JsonPayload:
        payload: JsonPayload = {
            "service_name": service_name,
            "resource_path": resource_path,
            "query_options": query_options or {},
            "function_parameters": function_parameters or {},
            "user_input": user_input,
        }
        if output_contract is not None:
            payload["output_contract"] = output_contract
        if conversation_id:
            payload["conversation_id"] = conversation_id
        return self._request_json("POST", "/api/v1/runtime/execute-get", payload)

    def page(self, case_id: str, skip: int = 0) -> JsonPayload:
        return self._request_json("POST", "/api/v1/runtime/page", {"case_id": case_id, "skip": skip})

    def case_snapshot(self, case_id: str) -> JsonPayload:
        encoded_case_id = urllib.parse.quote(str(case_id or ""), safe="")
        return self._request_json("GET", f"/api/v1/agent/cases/{encoded_case_id}")

    def feedback(
        self,
        case_id: str,
        status: str,
        comment: str = "",
        expected_result: str = "",
    ) -> JsonPayload:
        return self._request_json(
            "POST",
            "/api/v1/runtime/feedback",
            {
                "case_id": case_id,
                "status": status,
                "comment": comment,
                "expected_result": expected_result,
            },
        )

    def _request_json(self, method: str, path: str, payload: JsonPayload | None = None) -> JsonPayload:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        try:
            status_code, _response_headers, body = self._transport(
                method,
                url,
                payload,
                self.timeout_seconds,
                headers,
            )
        except TimeoutError as exc:
            raise RuntimeClientError(
                "SAPClaw Thin Runtime request timed out.",
                error_type="timeout",
                method=method,
                url=url,
            ) from exc
        except (OSError, urllib.error.URLError, socket.timeout) as exc:
            raise RuntimeClientError(
                "SAPClaw Thin Runtime is not reachable. Start the local FastAPI service first.",
                error_type="connection_error",
                detail=str(exc),
                method=method,
                url=url,
            ) from exc

        decoded = _decode_json(body)
        if status_code >= 400:
            raise RuntimeClientError(
                f"SAPClaw Thin Runtime returned HTTP {status_code}.",
                error_type="http_error",
                status_code=status_code,
                detail=decoded if decoded is not None else body.decode("utf-8", errors="replace"),
                method=method,
                url=url,
            )
        if not isinstance(decoded, dict):
            raise RuntimeClientError(
                "SAPClaw Thin Runtime returned an invalid JSON object.",
                error_type="invalid_response",
                detail=decoded,
                method=method,
                url=url,
            )
        return decoded


def _urllib_runtime_transport(
    method: str,
    url: str,
    payload: JsonPayload | None,
    timeout_seconds: float,
    headers: dict[str, str],
) -> tuple[int, dict[str, str], bytes]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    opener = (
        urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if _is_loopback_url(url)
        else urllib.request.build_opener()
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _decode_json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _is_loopback_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host in {"localhost", "127.0.0.1", "::1"}
