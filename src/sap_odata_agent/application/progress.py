from __future__ import annotations

import json
import queue
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterator


_current_conversation_id: ContextVar[str | None] = ContextVar("sapclaw_progress_conversation_id", default=None)
_current_broker: ContextVar["QueryProgressBroker | None"] = ContextVar("sapclaw_progress_broker", default=None)


class QueryProgressBroker:
    def __init__(self, max_last_events: int = 200) -> None:
        self._lock = Lock()
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {}
        self._last_events: dict[str, dict[str, Any]] = {}
        self._sequence_by_conversation: dict[str, int] = {}
        self._terminal_at: dict[str, float] = {}
        self._max_last_events = max(1, max_last_events)

    def publish(self, conversation_id: str | None, event: dict[str, Any]) -> None:
        if not conversation_id:
            return
        normalized_id = str(conversation_id).strip()
        if not normalized_id:
            return

        payload = self._normalize_event(normalized_id, event)
        with self._lock:
            self._last_events[normalized_id] = payload
            if payload.get("terminal"):
                self._terminal_at[normalized_id] = time.monotonic()
            self._cleanup_locked()
            subscribers = list(self._subscribers.get(normalized_id, []))

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(payload)
            except queue.Full:
                pass

    def subscribe(self, conversation_id: str) -> Iterator[str]:
        normalized_id = str(conversation_id).strip()
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.setdefault(normalized_id, []).append(subscriber)
            last_event = self._last_events.get(normalized_id)

        try:
            if last_event is not None:
                yield _format_sse(last_event)
                if last_event.get("terminal"):
                    return
            else:
                yield _format_sse(
                    self._normalize_event(
                        normalized_id,
                        {
                            "key": "progress.connected",
                            "label": "等待后端开始处理",
                            "status": "running",
                        },
                    )
                )

            while True:
                try:
                    event = subscriber.get(timeout=15)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                yield _format_sse(event)
                if event.get("terminal"):
                    return
        finally:
            with self._lock:
                subscribers = self._subscribers.get(normalized_id)
                if subscribers and subscriber in subscribers:
                    subscribers.remove(subscriber)
                if subscribers == []:
                    self._subscribers.pop(normalized_id, None)

    def _normalize_event(self, conversation_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            next_sequence = self._sequence_by_conversation.get(conversation_id, 0) + 1
            self._sequence_by_conversation[conversation_id] = next_sequence

        payload = {
            "conversation_id": conversation_id,
            "sequence": next_sequence,
            "key": str(event.get("key") or "progress"),
            "label": str(event.get("label") or event.get("key") or "处理中"),
            "status": str(event.get("status") or "running"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for field in ("duration_ms", "error_message", "detail", "terminal"):
            if field in event and event[field] is not None:
                payload[field] = event[field]
        return payload

    def _cleanup_locked(self) -> None:
        if len(self._last_events) <= self._max_last_events:
            return
        terminal_items = sorted(self._terminal_at.items(), key=lambda item: item[1])
        for conversation_id, _timestamp in terminal_items:
            if len(self._last_events) <= self._max_last_events:
                break
            if conversation_id in self._subscribers:
                continue
            self._last_events.pop(conversation_id, None)
            self._terminal_at.pop(conversation_id, None)
            self._sequence_by_conversation.pop(conversation_id, None)


_default_progress_broker = QueryProgressBroker()


def get_progress_broker() -> QueryProgressBroker:
    return _default_progress_broker


@contextmanager
def progress_context(conversation_id: str | None, broker: QueryProgressBroker | None = None):
    conversation_token = _current_conversation_id.set(conversation_id)
    broker_token = _current_broker.set(broker)
    try:
        yield
    finally:
        _current_broker.reset(broker_token)
        _current_conversation_id.reset(conversation_token)


def publish_progress_event(
    *,
    key: str,
    label: str,
    status: str = "running",
    duration_ms: float | None = None,
    error_message: str | None = None,
    detail: str | None = None,
    terminal: bool = False,
) -> None:
    conversation_id = _current_conversation_id.get()
    if not conversation_id:
        return
    broker = _current_broker.get() or get_progress_broker()
    broker.publish(
        conversation_id,
        {
            "key": key,
            "label": label,
            "status": status,
            "duration_ms": duration_ms,
            "error_message": error_message,
            "detail": detail,
            "terminal": terminal,
        },
    )


def _format_sse(event: dict[str, Any]) -> str:
    data = json.dumps(event, ensure_ascii=False, default=str)
    return f"event: progress\ndata: {data}\n\n"
