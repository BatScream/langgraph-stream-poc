"""Domain events emitted by WorkflowStreamer.

These dataclasses are the public contract between the streaming library
and consumer code.  They carry **no** soprano-sdk or LangGraph types —
consumers never need to import from those packages.

Event types
-----------
``NodeCompleteEvent``
    Emitted once per graph node after it finishes execution.
    Contains the node name and its state update dict.

``CustomEvent``
    Emitted *mid-node* when a workflow function calls
    ``langgraph.config.get_stream_writer()``.  The ``payload`` dict is
    whatever the function wrote — e.g. a static data list, LLM tokens, etc.

``InterruptEvent``
    The workflow has paused and is waiting for user input.
    Contains the agent's prompt, optional selectable options, and
    field-level details for the active collector node.

``CompleteEvent``
    The workflow reached a terminal outcome.
    Contains the final message and any options.

``ErrorEvent``
    An unrecoverable error occurred during streaming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Union


@dataclass
class NodeCompleteEvent:
    """A graph node finished execution."""

    node: str
    """Name of the node that completed (matches the step ``id`` in the YAML)."""

    state_update: Dict[str, Any]
    """State fields written or changed by this node."""


@dataclass
class CustomEvent:
    """A mid-node event emitted via ``get_stream_writer()``."""

    payload: Dict[str, Any]
    """Arbitrary dict written by the workflow function."""


@dataclass
class InterruptEvent:
    """The workflow paused and needs user input to continue."""

    prompt: str
    """The agent's message / question for the user."""

    options: List[Dict[str, Any]] = field(default_factory=list)
    """Selectable options (each has ``text`` and optional ``subtext``)."""

    is_selectable: bool = False
    """``True`` if the user *must* pick from ``options``; ``False`` if
    free-text is also accepted."""

    field_details: List[Dict[str, Any]] = field(default_factory=list)
    """Metadata for the active collector node's fields.
    Each entry: ``{"name": str, "value": Any}`` with optional
    ``"label"`` and ``"error"`` keys."""


@dataclass
class CompleteEvent:
    """The workflow reached a terminal outcome."""

    message: str
    """Final outcome message (success or failure)."""

    options: List[Dict[str, Any]] = field(default_factory=list)
    """Optional outcome options."""

    is_selectable: bool = False
    """Whether the user must select from ``options``."""


@dataclass
class ErrorEvent:
    """An error occurred during streaming."""

    error: str
    """Human-readable error description."""


WorkflowEvent = Union[
    NodeCompleteEvent, CustomEvent, InterruptEvent, CompleteEvent, ErrorEvent
]
"""Union of all event types yielded by ``WorkflowStreamer.stream()``."""
