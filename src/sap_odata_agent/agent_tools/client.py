from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0
_SOURCE_ROOT = Path(__file__).resolve().parents[2]
START_COMMAND = "python -m uvicorn sap_odata_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000"
if _SOURCE_ROOT.name == "src":
    START_COMMAND = f'$env:PYTHONPATH="{_SOURCE_ROOT}"; {START_COMMAND}'

JsonPayload = dict[str, Any]
Transport = Callable[[str, str, JsonPayload | None, float], tuple[int, dict[str, str], bytes]]


@dataclass(slots=True)
class SapClawClientError(Exception):
    message: str
    error_type: str = "client_error"
    status_code: int | None = None
    detail: Any = None
    method: str = ""
    url: str = ""

    def __str__(self) -> str:
        return self.message

    def to_payload(self) -> JsonPayload:
        payload: JsonPayload = {
            "type": self.error_type,
            "message": self.message,
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        if self.detail not in (None, ""):
            payload["detail"] = self.detail
        if self.method:
            payload["method"] = self.method
        if self.url:
            payload["url"] = self.url
        return payload


class SapClawClient:
    """Small HTTP client for the local SAPClaw FastAPI service."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_seconds = float(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)
        self._transport = transport or _urllib_transport

    def health(self) -> JsonPayload:
        return self._request_json("GET", "/health")

    def query(
        self,
        user_input: str,
        conversation_id: str | None = None,
        mode: str = "read_only",
        llm_profile_id: str | None = None,
    ) -> JsonPayload:
        payload: JsonPayload = {
            "user_input": user_input,
            "mode": mode,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if llm_profile_id:
            payload["llm_profile_id"] = llm_profile_id
        return self._request_json("POST", "/api/v1/agent/query", payload)

    def page(self, case_id: str, skip: int = 0) -> JsonPayload:
        return self._request_json("POST", "/api/v1/agent/page", {"case_id": case_id, "skip": skip})

    def feedback(
        self,
        case_id: str,
        status: str,
        comment: str = "",
        expected_result: str = "",
    ) -> JsonPayload:
        return self._request_json(
            "POST",
            "/api/v1/agent/feedback",
            {
                "case_id": case_id,
                "status": status,
                "comment": comment,
                "expected_result": expected_result,
            },
        )

    def model_profiles(self) -> JsonPayload:
        return self._request_json("GET", "/api/v1/agent/model-profiles")

    def _request_json(self, method: str, path: str, payload: JsonPayload | None = None) -> JsonPayload:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{normalized_path}"
        try:
            status_code, _headers, body = self._transport(method, url, payload, self.timeout_seconds)
        except TimeoutError as exc:
            raise SapClawClientError(
                "SAPClaw service request timed out.",
                error_type="timeout",
                method=method,
                url=url,
            ) from exc
        except (OSError, urllib.error.URLError, socket.timeout) as exc:
            raise SapClawClientError(
                "SAPClaw service is not reachable. Start the local service before calling the agent tool.",
                error_type="connection_error",
                detail=str(exc),
                method=method,
                url=url,
            ) from exc

        decoded = _decode_json(body)
        if status_code >= 400:
            detail = decoded if decoded is not None else body.decode("utf-8", errors="replace")
            raise SapClawClientError(
                f"SAPClaw service returned HTTP {status_code}.",
                error_type="http_error",
                status_code=status_code,
                detail=detail,
                method=method,
                url=url,
            )
        if decoded is None:
            raise SapClawClientError(
                "SAPClaw service returned a non-JSON response.",
                error_type="invalid_response",
                detail=body.decode("utf-8", errors="replace"),
                method=method,
                url=url,
            )
        if not isinstance(decoded, dict):
            raise SapClawClientError(
                "SAPClaw service returned a JSON value that is not an object.",
                error_type="invalid_response",
                detail=decoded,
                method=method,
                url=url,
            )
        return decoded


def _urllib_transport(
    method: str,
    url: str,
    payload: JsonPayload | None,
    timeout_seconds: float,
) -> tuple[int, dict[str, str], bytes]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _decode_json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
