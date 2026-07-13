from __future__ import annotations

import argparse
from typing import Any, Literal

from sap_odata_agent.agent_tools.client import DEFAULT_BASE_URL, DEFAULT_TIMEOUT_SECONDS, START_COMMAND
from sap_odata_agent.agent_tools.runtime_client import RuntimeClientError, SapClawRuntimeClient


class SapClawRuntimeToolset:
    def __init__(self, client: SapClawRuntimeClient) -> None:
        self.client = client

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
                    "origin": "thin_mcp",
                    "read_only": True,
                    "operation": operation,
                    "start_command": START_COMMAND,
                },
            }
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

    client = SapClawRuntimeClient(base_url=base_url, timeout_seconds=timeout_seconds)
    tools = SapClawRuntimeToolset(client)
    server = FastMCP("sapclaw-runtime")

    @server.tool(annotations=read_only_tool)
    def sapclaw_runtime_health() -> dict[str, Any]:
        """Check the local read-only Thin Runtime, index, SAP config, and viewer readiness."""
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
    ) -> dict[str, Any]:
        """Revalidate and execute a structured read-only QueryPlan against SAP OData."""
        return tools.call(
            "execute_plan",
            lambda: client.execute_plan(
                plan=plan,
                user_input=user_input,
                conversation_id=conversation_id,
            ),
        )

    @server.tool(annotations=read_only_sap_tool)
    def sapclaw_execute_get(
        service_name: str,
        resource_path: str,
        query_options: dict[str, str] | None = None,
        function_parameters: dict[str, str] | None = None,
        user_input: str = "",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a controlled relative OData GET for an indexed executable service.

        Absolute URLs, external hosts, custom headers, traversal, non-GET operations, and unknown
        query options are rejected before SAP is contacted.
        """
        return tools.call(
            "execute_get",
            lambda: client.execute_get(
                service_name=service_name,
                resource_path=resource_path,
                query_options=query_options,
                function_parameters=function_parameters,
                user_input=user_input,
                conversation_id=conversation_id,
            ),
        )

    @server.tool(annotations=read_only_sap_tool)
    def sapclaw_runtime_page(case_id: str, skip: int = 0) -> dict[str, Any]:
        """Load a result page for a previous Thin Runtime case by skip offset."""
        return tools.call("page", lambda: client.page(case_id=case_id, skip=skip))

    @server.tool(annotations=local_feedback_tool)
    def sapclaw_runtime_feedback(
        case_id: str,
        status: Literal["correct", "incorrect"],
        comment: str = "",
        expected_result: str = "",
    ) -> dict[str, Any]:
        """Save user feedback for a Thin Runtime case without invoking an LLM."""
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
    parser = argparse.ArgumentParser(description="Expose SAPClaw Thin Runtime as an MCP stdio server.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="SAPClaw FastAPI base URL.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds for Thin Runtime calls.",
    )
    args = parser.parse_args(argv)
    create_mcp_server(base_url=args.base_url, timeout_seconds=args.timeout).run()


if __name__ == "__main__":
    main()
