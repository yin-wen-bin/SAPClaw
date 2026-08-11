from __future__ import annotations

import argparse
import urllib.parse
import webbrowser
from typing import Any, Callable, Literal

from sap_odata_agent.agent_tools.runtime_client import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    START_COMMAND,
    RuntimeClientError,
    SapClawRuntimeClient,
)
from sap_odata_agent.application.runtime_models import RuntimeOutputContract


class SapClawRuntimeToolset:
    def __init__(
        self,
        client: SapClawRuntimeClient,
        browser_opener: Callable[[str], bool] | None = None,
    ) -> None:
        self.client = client
        self._browser_opener = browser_opener or (lambda url: webbrowser.open(url, new=2))

    def call(self, operation: str, callback) -> dict[str, Any]:
        try:
            return callback()
        except RuntimeClientError as exc:
            return {
                "schema_version": "1.0",
                "ok": False,
                "status": "client_error",
                "case_id": None,
                "data": {},
                "pagination": {
                    "page_size": 50,
                    "skip": 0,
                    "total_count": 0,
                    "has_next": False,
                    "next_skip": None,
                },
                "viewer_url": None,
                "validation_issues": [],
                "executed_requests": [],
                "error": exc.to_payload(),
                "metadata": {
                    "origin": "sapclaw_mcp",
                    "read_only": True,
                    "operation": operation,
                    "start_command": START_COMMAND,
                },
            }

    def open_viewer(self, case_id: str, page: int = 1) -> dict[str, Any]:
        normalized_case_id = str(case_id or "").strip()
        if not normalized_case_id:
            return self._viewer_error(None, "case_id is required.")
        if page < 1:
            return self._viewer_error(normalized_case_id, "page must be greater than or equal to 1.")

        try:
            viewer_url = _local_viewer_url(self.client.base_url, normalized_case_id, page)
            health = self.client.health()
            if not bool((health.get("data") or {}).get("viewer_enabled")):
                return self._viewer_error(normalized_case_id, "The local result viewer is disabled.")
            case_snapshot = self.client.case_snapshot(normalized_case_id)
            should_open, reason = _viewer_opening_decision(case_snapshot)
            if not should_open:
                return self._viewer_not_required(normalized_case_id, page, reason)
            if not self._browser_opener(viewer_url):
                return self._viewer_error(normalized_case_id, "The system browser did not accept the viewer request.")
        except RuntimeClientError as exc:
            return self.call("open_viewer", lambda: (_ for _ in ()).throw(exc))
        except (OSError, webbrowser.Error) as exc:
            return self._viewer_error(normalized_case_id, f"The system browser could not be opened: {exc}")
        except ValueError as exc:
            return self._viewer_error(normalized_case_id, str(exc))

        return {
            "schema_version": "1.0",
            "ok": True,
            "status": "success",
            "case_id": normalized_case_id,
            "data": {"opened": True, "page": page},
            "pagination": {
                "page_size": 50,
                "skip": 0,
                "total_count": 0,
                "has_next": False,
                "next_skip": None,
            },
            "viewer_url": None,
            "validation_issues": [],
            "executed_requests": [],
            "error": None,
            "metadata": {
                "origin": "sapclaw_mcp",
                "read_only": True,
                "opened_in_system_browser": True,
            },
        }

    @staticmethod
    def _viewer_error(case_id: str | None, message: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "ok": False,
            "status": "viewer_unavailable",
            "case_id": case_id,
            "data": {},
            "pagination": {
                "page_size": 50,
                "skip": 0,
                "total_count": 0,
                "has_next": False,
                "next_skip": None,
            },
            "viewer_url": None,
            "validation_issues": [],
            "executed_requests": [],
            "error": {"type": "viewer_unavailable", "message": message},
            "metadata": {"origin": "sapclaw_mcp", "read_only": True},
        }

    @staticmethod
    def _viewer_not_required(case_id: str, page: int, reason: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "ok": True,
            "status": "not_required",
            "case_id": case_id,
            "data": {"opened": False, "page": page, "reason": reason},
            "pagination": {
                "page_size": 50,
                "skip": 0,
                "total_count": 0,
                "has_next": False,
                "next_skip": None,
            },
            "viewer_url": None,
            "validation_issues": [],
            "executed_requests": [],
            "error": None,
            "metadata": {
                "origin": "sapclaw_mcp",
                "read_only": True,
                "opened_in_system_browser": False,
                "viewer_reason": reason,
            },
        }


def _local_viewer_url(base_url: str, case_id: str, page: int) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("The local result viewer is available only for a loopback SAPClaw Runtime URL.")
    query = urllib.parse.urlencode({"case_id": case_id, "page": str(page)})
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/", query, ""))


def _viewer_opening_decision(case_snapshot: dict[str, Any]) -> tuple[bool, str]:
    snapshot = case_snapshot.get("result_snapshot")
    if not isinstance(snapshot, dict):
        return True, "unknown_result_shape"
    if not snapshot.get("success") or snapshot.get("needs_clarification"):
        return False, "no_displayable_result"

    data = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else {}
    rows = [row for row in data.get("results") or [] if isinstance(row, dict)]
    pagination = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
    total_count = _safe_nonnegative_int(data.get("result_count"), len(rows))
    if total_count == 0:
        return False, "empty_result"
    if total_count > 1 or bool(pagination.get("has_next")):
        return True, "multiple_rows"

    presentation = snapshot.get("presentation") if isinstance(snapshot.get("presentation"), dict) else {}
    columns = [column for column in presentation.get("columns") or [] if str(column).strip()]
    first_row = rows[0] if rows else {}
    field_count = len(columns) if columns else len([key for key in first_row if key != "__metadata"])
    if field_count <= 3:
        return False, "compact_single_result"
    return True, "detailed_single_result"


def _safe_nonnegative_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default
def create_mcp_server(
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
):
    try:
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError(
            "Install MCP support with `pip install -e .[agent]` before running sapclaw-runtime-mcp."
        ) from exc

    read_only_tool = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    read_only_sap_tool = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
    local_feedback_tool = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
    local_viewer_tool = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )

    client = SapClawRuntimeClient(base_url=base_url, timeout_seconds=timeout_seconds)
    tools = SapClawRuntimeToolset(client)
    server = FastMCP("sapclaw-runtime")

    @server.tool(annotations=read_only_tool)
    def sapclaw_runtime_health() -> dict[str, Any]:
        """Check the local read-only SAPClaw Runtime, index, SAP config, and viewer readiness."""
        return tools.call("health", client.health)

    @server.tool(annotations=read_only_tool)
    def sapclaw_catalog(query: str = "", skip: int = 0, limit: int = 20) -> dict[str, Any]:
        """Page through indexed SAP API catalog entries and optional KG candidate evidence.

        Evidence is advisory. Codex must still inspect schema and runtime availability before planning.
        """
        return tools.call("catalog", lambda: client.catalog(query=query, skip=skip, limit=limit))

    @server.tool(annotations=read_only_tool)
    def sapclaw_schema(
        service_name: str,
        entity_sets: list[str] | None = None,
        query: str = "",
        include_fields: bool = True,
        max_fields: int = 500,
    ) -> dict[str, Any]:
        """Read authoritative indexed entities, fields, types, relations, and function imports."""
        return tools.call(
            "schema",
            lambda: client.schema(
                service_name=service_name,
                entity_sets=entity_sets,
                query=query,
                include_fields=include_fields,
                max_fields=max_fields,
            ),
        )

    @server.tool(annotations=read_only_tool)
    def sapclaw_guidance(
        user_input: str,
        service_names: list[str] | None = None,
        max_feedback_memories: int = 5,
    ) -> dict[str, Any]:
        """Read API Skill, Local KG, and feedback evidence without modifying or approving a plan."""
        return tools.call(
            "guidance",
            lambda: client.guidance(
                user_input=user_input,
                service_names=service_names,
                max_feedback_memories=max_feedback_memories,
            ),
        )

    @server.tool(annotations=read_only_tool)
    def sapclaw_validate_plan(plan: dict[str, Any], user_input: str = "") -> dict[str, Any]:
        """Strictly validate a Codex-authored read-only QueryPlan without contacting SAP."""
        return tools.call("validate_plan", lambda: client.validate_plan(plan=plan, user_input=user_input))

    @server.tool(annotations=read_only_sap_tool)
    def sapclaw_execute_plan(
        plan: dict[str, Any],
        user_input: str = "",
        conversation_id: str | None = None,
        resume_case_id: str | None = None,
    ) -> dict[str, Any]:
        """Revalidate and execute a structured read-only QueryPlan against SAP OData.

        Pass resume_case_id from an interrupted aggregate execution to continue stable source
        pagination without refetching already saved rows.
        """
        return tools.call(
            "execute_plan",
            lambda: client.execute_plan(
                plan=plan,
                user_input=user_input,
                conversation_id=conversation_id,
                resume_case_id=resume_case_id,
            ),
        )

    @server.tool(annotations=read_only_sap_tool)
    def sapclaw_execute_get(
        service_name: str,
        resource_path: str,
        query_options: dict[str, str] | None = None,
        function_parameters: dict[str, str] | None = None,
        output_contract: RuntimeOutputContract | None = None,
        user_input: str = "",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a controlled relative OData GET for an indexed executable service.

        Absolute URLs, external hosts, custom headers, traversal, non-GET operations, and unknown
        query options are rejected before SAP is contacted.

        A minimal valid output_contract is
        {"display_fields": ["PurchaseOrder"], "reason": "Return the requested purchase order."}.
        """
        return tools.call(
            "execute_get",
            lambda: client.execute_get(
                service_name=service_name,
                resource_path=resource_path,
                query_options=query_options,
                function_parameters=function_parameters,
                output_contract=output_contract.model_dump(mode="json") if output_contract is not None else None,
                user_input=user_input,
                conversation_id=conversation_id,
            ),
        )

    @server.tool(annotations=read_only_sap_tool)
    def sapclaw_runtime_page(case_id: str, skip: int = 0) -> dict[str, Any]:
        """Load a result page for a previous SAPClaw Runtime case by skip offset."""
        return tools.call("page", lambda: client.page(case_id=case_id, skip=skip))

    @server.tool(annotations=local_viewer_tool)
    def sapclaw_runtime_open_viewer(case_id: str, page: int = 1) -> dict[str, Any]:
        """Open a saved local result page in the system default browser, outside Codex's embedded browser."""
        return tools.open_viewer(case_id=case_id, page=page)

    @server.tool(annotations=local_feedback_tool)
    def sapclaw_runtime_feedback(
        case_id: str,
        status: Literal["correct", "incorrect"],
        comment: str = "",
        expected_result: str = "",
    ) -> dict[str, Any]:
        """Save user feedback for a SAPClaw Runtime case without executing SAP."""
        return tools.call(
            "feedback",
            lambda: client.feedback(
                case_id=case_id,
                status=status,
                comment=comment,
                expected_result=expected_result,
            ),
        )

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Expose SAPClaw Runtime as an MCP stdio server.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="SAPClaw FastAPI base URL.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds for SAPClaw Runtime calls.",
    )
    args = parser.parse_args(argv)
    create_mcp_server(base_url=args.base_url, timeout_seconds=args.timeout).run()


if __name__ == "__main__":
    main()
