"""soprano-streaming — Real-time streaming wrapper for soprano-sdk workflows.

This library wraps soprano-sdk's LangGraph-based workflow engine and
exposes a generator-based streaming API.  Instead of the synchronous
``WorkflowTool.execute()`` call that returns a single ``WorkflowResult``,
you get a stream of typed events as each graph node executes — enabling
Server-Sent Events, WebSocket pushes, or any incremental transport.

Quick start
-----------
::

    from soprano_streaming import WorkflowStreamer, InterruptEvent, CompleteEvent

    streamer = WorkflowStreamer.from_env("workflow.yaml")

    for event in streamer.stream(thread_id="t1", message="hello"):
        match event:
            case InterruptEvent():
                print(f"Bot asks: {event.prompt}")
            case CompleteEvent():
                print(f"Done: {event.message}")

See ``soprano_streaming.sse`` for a ready-made SSE mapping helper.
"""

from .events import (
    CompleteEvent,
    CustomEvent,
    ErrorEvent,
    InterruptEvent,
    NodeCompleteEvent,
    WorkflowEvent,
)
from .runner import WorkflowStreamer

__all__ = [
    "WorkflowStreamer",
    "NodeCompleteEvent",
    "CustomEvent",
    "InterruptEvent",
    "CompleteEvent",
    "ErrorEvent",
    "WorkflowEvent",
]
