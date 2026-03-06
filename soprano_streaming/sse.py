"""Optional SSE helper — maps domain events to ``sse-starlette`` dicts.

This module is provided as a convenience for FastAPI users.  It is
**not** required — you can map events to any transport format you like.

Usage::

    from soprano_streaming import WorkflowStreamer
    from soprano_streaming.sse import events_to_sse
    from sse_starlette.sse import EventSourceResponse

    @app.post("/chat")
    def chat(req: ChatRequest):
        return EventSourceResponse(
            events_to_sse(
                streamer.stream(req.thread_id, req.message),
                thread_id=req.thread_id,
            )
        )
"""

from __future__ import annotations

import json
import uuid
from typing import Generator, Iterable, Optional

from .events import (
    CompleteEvent,
    CustomEvent,
    ErrorEvent,
    InterruptEvent,
    NodeCompleteEvent,
    WorkflowEvent,
)


def events_to_sse(
    events: Iterable[WorkflowEvent],
    thread_id: Optional[str] = None,
) -> Generator[dict, None, None]:
    """Convert a stream of ``WorkflowEvent`` objects into SSE dicts.

    Each yielded dict has ``"event"`` and ``"data"`` keys compatible with
    ``sse_starlette.sse.EventSourceResponse``.

    Parameters
    ----------
    events:
        Iterable of events from ``WorkflowStreamer.stream()``.
    thread_id:
        Thread identifier to include in every SSE payload.
        If ``None`` a new UUID is generated.

    Yields
    ------
    dict
        ``{"event": "<type>", "data": "<json>"}``
    """
    thread_id = thread_id or str(uuid.uuid4())

    for event in events:
        yield _to_sse(thread_id, event)

    yield {"event": "done", "data": ""}


def _to_sse(thread_id: str, event: WorkflowEvent) -> dict:
    match event:
        case NodeCompleteEvent():
            return {
                "event": "node_complete",
                "data": json.dumps({
                    "thread_id": thread_id,
                    "node": event.node,
                    "state_update": event.state_update,
                }),
            }
        case CustomEvent():
            return {
                "event": "custom",
                "data": json.dumps({
                    "thread_id": thread_id,
                    **event.payload,
                }),
            }
        case InterruptEvent():
            return {
                "event": "interrupt",
                "data": json.dumps({
                    "thread_id": thread_id,
                    "type": "user_input",
                    "prompt": event.prompt,
                    "options": event.options,
                    "is_selectable": event.is_selectable,
                    "field_details": event.field_details,
                }),
            }
        case CompleteEvent():
            return {
                "event": "complete",
                "data": json.dumps({
                    "thread_id": thread_id,
                    "message": event.message,
                    "options": event.options,
                    "is_selectable": event.is_selectable,
                }),
            }
        case ErrorEvent():
            return {
                "event": "error",
                "data": json.dumps({"error": event.error}),
            }
        case _:
            return {
                "event": "unknown",
                "data": json.dumps({
                    "thread_id": thread_id,
                    "type": type(event).__name__,
                }),
            }
