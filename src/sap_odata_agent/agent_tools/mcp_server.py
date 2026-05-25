from __future__ import annotations

import argparse
from typing import Any, Literal

from sap_odata_agent.agent_tools.client import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    START_COMMAND,
    SapClawClient,
    SapClawClientError,
)


class SapClawToolset:
    """MCP-exposed operations backed by the local SAPClaw HTTP service."""

    def __init__(self, client: SapClawClient) -> None:
        self.client = client

    def health(self) -> dict[str, Any]:
        return self._call("health", self.client.health, success_key="ok")

    def query(
        self,
        user_input: str,
        conversation_id: str | None = None,
        mode: Literal["read_only", "write_confirm_required"] = "read_only",
        llm_profile_id: str | None = None,
    ) -> dict[str, Any]:
        if not str(user_input or "").strip():
            return self._tool_error("user_input is required.", success_key="success")
        return self._call(
            "query",
            lambda: self.client.query(
                user_input=user_input,
                conversation_id=conversation_id,
                mode=mode,
                llm_profile_id=llm_profile_id,
            ),
            success_key="success",
            preserve_success=True,
        )

    def page(self, case_id: str, skip: int = 0) -> dict[str, Any]:
        if not str(case_id or "").strip():
            return self._tool_error("case_id is required.", success_key="success")
        return self._call("page", lambda: self.client.page(case_id=case_id, skip=skip), success_key="success")

    def feedback(
        self,
        case_id: str,
        status: Literal["correct", "incorrect"],
        comment: str = "",
        expected_result: str = "",
    ) -> dict[str, Any]:
        if not str(case_id or "").strip():
            return self._tool_error("case_id is required.", success_key="ok")
        return self._call(
            "feedback",
            lambda: self.client.feedback(
                case_id=case_id,
                status=status,
                comment=comment,
                expected_result=expected_result,
            ),
            success_key="ok",
            preserve_success=True,
        )

    def model_profiles(self) -> dict[str, Any]:
        return self._call("model_profiles", self.client.model_profiles, success_key="ok")

    def _call(
        self,
        operation: str,
        callback,
        *,
        success_key: str,
        preserve_success: bool = False,
    ) -> dict[str, Any]:
        try:
            payload = callback()
        except SapClawClientError as exc:
            return self._tool_error(
                exc.message,
                success_key=success_key,
                error=exc.to_payload(),
                operation=operation,
            )
        if preserve_success or success_key in payload:
            return payload
        return {success_key: True, **payload}

    @staticmethod
    def _tool_error(
        message: str,
        *,
        success_key: str,
        error: dict[str, Any] | None = None,
        operation: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            success_key: False,
            "error": error or {"type": "validation_error", "message": message},
            "final_message": message,
            "start_command": START_COMMAND,
        }
        if operation:
            payload["operation"] = operation
        return payload


def create_mcp_server(
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("Install MCP support with `pip install -e .[agent]` before running sapclaw-mcp.") from exc

    client = SapClawClient(base_url=base_url, timeout_seconds=timeout_seconds)
    tools = SapClawToolset(client)
    server = FastMCP("sapclaw")

    @server.tool()
    def sapclaw_health() -> dict[str, Any]:
        """Check whether the local SAPClaw FastAPI service is reachable."""
        return tools.health()

    @server.tool()
    def sapclaw_query(
        user_input: str,
        conversation_id: str | None = None,
        mode: Literal["read_only", "write_confirm_required"] = "read_only",
        llm_profile_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a natural-language SAP OData query through SAPClaw."""
        return tools.query(
            user_input=user_input,
            conversation_id=conversation_id,
            mode=mode,
            llm_profile_id=llm_profile_id,
        )

    @server.tool()
    def sapclaw_page(case_id: str, skip: int = 0) -> dict[str, Any]:
        """Load another result page for a previous SAPClaw query case."""
        return tools.page(case_id=case_id, skip=skip)

    @server.tool()
    def sapclaw_feedback(
        case_id: str,
        status: Literal["correct", "incorrect"],
        comment: str = "",
        expected_result: str = "",
    ) -> dict[str, Any]:
        """Record feedback for a SAPClaw query result."""
        return tools.feedback(
            case_id=case_id,
            status=status,
            comment=comment,
            expected_result=expected_result,
        )

    @server.tool()
    def sapclaw_model_profiles() -> dict[str, Any]:
        """List SAPClaw LLM profiles exposed by the local service."""
        return tools.model_profiles()

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Expose SAPClaw as an MCP stdio server.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="SAPClaw FastAPI base URL.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds for SAPClaw service calls.",
    )
    args = parser.parse_args(argv)
    server = create_mcp_server(base_url=args.base_url, timeout_seconds=args.timeout)
    server.run()


if __name__ == "__main__":
    main()
