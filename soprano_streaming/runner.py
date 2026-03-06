"""Core streaming runner — wraps soprano-sdk's LangGraph workflow and
yields high-level :mod:`soprano_streaming.events` instead of raw SDK types.

This is the **only** module that imports from ``soprano_sdk`` and
``langgraph``.  Consumer code should depend only on
:class:`WorkflowStreamer` and the event dataclasses.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Generator, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from soprano_sdk import load_workflow
from soprano_sdk.core.constants import MFAConfig, WorkflowKeys
from soprano_sdk.core.engine import WorkflowEngine

from .events import (
    CompleteEvent,
    CustomEvent,
    ErrorEvent,
    InterruptEvent,
    NodeCompleteEvent,
    WorkflowEvent,
)


class WorkflowStreamer:
    """Streaming wrapper around a soprano-sdk workflow.

    This is the main entry point for the library.  It replaces
    ``WorkflowTool.execute()`` with a generator-based API that yields
    typed events as each graph node runs, enabling real-time streaming
    to clients via SSE or any other transport.

    Parameters
    ----------
    yaml_path:
        Path to the soprano-sdk workflow YAML file.
    config:
        soprano-sdk configuration dict.  Must include ``"model_config"``
        with at least ``"model_name"`` and ``"api_key"``.
    checkpointer:
        Optional LangGraph checkpointer for state persistence.
        Defaults to ``InMemorySaver()``.
    mfa_config:
        Optional MFA configuration (passed through to soprano-sdk).

    Examples
    --------
    Construct explicitly::

        streamer = WorkflowStreamer(
            yaml_path="workflow.yaml",
            config={
                "model_config": {
                    "model_name": "gpt-4o-mini",
                    "api_key": "sk-...",
                },
            },
        )

    Or from environment variables::

        streamer = WorkflowStreamer.from_env("workflow.yaml")

    Then stream a conversation turn::

        for event in streamer.stream(thread_id="t1", message="hello"):
            match event:
                case InterruptEvent():
                    send_to_user(event.prompt)
                case CustomEvent():
                    send_to_user(event.payload)
                case CompleteEvent():
                    send_to_user(event.message)
    """

    def __init__(
        self,
        yaml_path: str,
        config: Dict[str, Any],
        checkpointer: Any = None,
        mfa_config: Optional[MFAConfig] = None,
    ):
        if checkpointer is None:
            checkpointer = InMemorySaver()
        self._graph: CompiledStateGraph
        self._engine: WorkflowEngine
        self._graph, self._engine = load_workflow(
            yaml_path,
            checkpointer=checkpointer,
            config=config,
            mfa_config=mfa_config,
        )

    @classmethod
    def from_env(
        cls,
        yaml_path: str = "workflow.yaml",
        checkpointer: Any = None,
        mfa_config: Optional[MFAConfig] = None,
    ) -> WorkflowStreamer:
        """Build a streamer using environment variables.

        Required env vars:
            ``OPENAI_API_KEY``
        Optional env vars:
            ``MODEL_NAME``  (default: ``gpt-4o-mini``)

        Raises
        ------
        RuntimeError
            If ``OPENAI_API_KEY`` is not set.
        """
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY environment variable is not set")

        return cls(
            yaml_path=yaml_path,
            config={
                "model_config": {
                    "model_name": os.environ.get("MODEL_NAME", "gpt-4o-mini"),
                    "api_key": api_key,
                },
            },
            checkpointer=checkpointer,
            mfa_config=mfa_config,
        )

    @property
    def workflow_name(self) -> str:
        """Name of the loaded workflow (from the YAML ``name`` field)."""
        return self._engine.workflow_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stream(
        self, thread_id: str, message: Optional[str] = None
    ) -> Generator[WorkflowEvent, None, None]:
        """Execute one conversation turn and yield events as they occur.

        This method handles both fresh starts and resumes automatically.
        If the thread already has an interrupted workflow, sending a
        ``message`` resumes it.

        Parameters
        ----------
        thread_id:
            Unique conversation thread identifier.  The same
            ``thread_id`` must be used across turns of one conversation.
        message:
            The user's message.  ``None`` or ``""`` to start the workflow
            without user input.

        Yields
        ------
        WorkflowEvent
            One of ``NodeCompleteEvent``, ``CustomEvent``,
            ``InterruptEvent``, ``CompleteEvent``, or ``ErrorEvent``.

        Examples
        --------
        ::

            for event in streamer.stream("thread-1", "Alice"):
                print(type(event).__name__, event)
        """
        try:
            yield from self._stream_graph(thread_id, message)
            yield self._resolve_final_state(thread_id)
        except Exception as exc:
            yield ErrorEvent(error=str(exc))

    # ------------------------------------------------------------------
    # Internals — all SDK detail is below this line
    # ------------------------------------------------------------------

    def _stream_graph(
        self, thread_id: str, message: Optional[str]
    ) -> Generator[NodeCompleteEvent | CustomEvent, None, None]:
        config = self._thread_config(thread_id)
        state = self._graph.get_state(config)

        if state.next:
            input_val = Command(
                resume=message or "",
                update={WorkflowKeys.USER_MESSAGE: message or ""},
            )
        else:
            input_val = {WorkflowKeys.USER_MESSAGE: message or ""}

        for mode, chunk in self._graph.stream(
            input_val, config=config, stream_mode=["updates", "custom"]
        ):
            if mode == "updates":
                for node_name, update in chunk.items():
                    yield NodeCompleteEvent(
                        node=node_name, state_update=_serialize(update)
                    )
            elif mode == "custom":
                yield CustomEvent(payload=_serialize(chunk))

    def _resolve_final_state(
        self, thread_id: str
    ) -> InterruptEvent | CompleteEvent:
        config = self._thread_config(thread_id)
        final_state = self._graph.get_state(config)

        if final_state.next:
            return self._build_interrupt(final_state)
        return self._build_complete(final_state, thread_id)

    def _build_interrupt(self, final_state: Any) -> InterruptEvent:
        interrupt_val = (
            final_state.tasks[0].interrupts[0].value
            if final_state.tasks
            else None
        )

        if isinstance(interrupt_val, dict) and "text" in interrupt_val:
            prompt = interrupt_val["text"]
            options = interrupt_val.get("options", [])
            is_selectable = interrupt_val.get("is_selectable", False)
        else:
            prompt = str(interrupt_val) if interrupt_val else ""
            options = []
            is_selectable = False

        field_details = self._engine.build_field_details(
            final_state.values, node_id=final_state.next[0]
        )

        return InterruptEvent(
            prompt=prompt,
            options=options,
            is_selectable=is_selectable,
            field_details=field_details,
        )

    def _build_complete(
        self, final_state: Any, thread_id: str
    ) -> CompleteEvent:
        outcome = self._engine.get_outcome_message(
            final_state.values,
            thread_id=thread_id,
            workflow_name=self._engine.workflow_name,
        )
        return CompleteEvent(
            message=outcome.message,
            options=outcome.options or [],
            is_selectable=outcome.is_selectable,
        )

    @staticmethod
    def _thread_config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}


def _serialize(obj: Any) -> Any:
    """Best-effort JSON-safe serialisation of arbitrary state values."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)
