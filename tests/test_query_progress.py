from __future__ import annotations

import json

from fastapi.testclient import TestClient

from sap_odata_agent.api.app import create_app
from sap_odata_agent.api.routes import agent as agent_module
from sap_odata_agent.application.progress import QueryProgressBroker, progress_context, publish_progress_event
from sap_odata_agent.domain.models import AgentResponse, QueryPlan


def _event_from_chunk(chunk: str) -> dict:
    data_lines = [line.removeprefix("data: ") for line in chunk.splitlines() if line.startswith("data: ")]
    assert data_lines
    return json.loads("".join(data_lines))


def test_progress_broker_streams_events_for_conversation() -> None:
    broker = QueryProgressBroker()
    stream = broker.subscribe("conv-1")

    connected = _event_from_chunk(next(stream))
    assert connected["key"] == "progress.connected"

    with progress_context("conv-1", broker=broker):
        publish_progress_event(key="api.router", label="选择 API", status="running")

    event = _event_from_chunk(next(stream))
    assert event["conversation_id"] == "conv-1"
    assert event["key"] == "api.router"
    assert event["label"] == "选择 API"
    assert event["status"] == "running"
    stream.close()


def test_progress_broker_replays_terminal_event_to_late_subscriber() -> None:
    broker = QueryProgressBroker()
    broker.publish("conv-2", {"key": "query.completed", "label": "查询完成", "status": "succeeded", "terminal": True})

    stream = broker.subscribe("conv-2")
    event = _event_from_chunk(next(stream))

    assert event["key"] == "query.completed"
    assert event["terminal"] is True
    try:
        next(stream)
    except StopIteration:
        pass
    else:
        raise AssertionError("terminal progress stream should stop after replay")


def test_agent_query_route_publishes_terminal_progress(monkeypatch) -> None:
    class FakeProfile:
        id = "fake-profile"
        enabled = False

    class FakeOrchestrator:
        def run(self, request):
            assert request.conversation_id == "conv-route-progress"
            return AgentResponse(
                success=True,
                plan=QueryPlan(service_name="API_TEST", entity_set="A_Test"),
                validation_issues=[],
                attempts=[],
                final_message="ok",
                case_id="case-progress",
            )

    monkeypatch.setattr(agent_module, "get_llm_profile", lambda profile_id=None: FakeProfile())
    monkeypatch.setattr(agent_module, "get_orchestrator_for_profile", lambda profile_id=None: FakeOrchestrator())

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/agent/query",
        json={"user_input": "query test data", "conversation_id": "conv-route-progress"},
    )

    assert response.status_code == 200
    stream = agent_module.get_progress_broker().subscribe("conv-route-progress")
    event = _event_from_chunk(next(stream))
    assert event["key"] == "query.completed"
    assert event["terminal"] is True
    stream.close()
