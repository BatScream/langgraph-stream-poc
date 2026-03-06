"""TDD tests for soprano_streaming.runner — WorkflowStreamer with mocked SDK."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from soprano_streaming.events import (
    CompleteEvent,
    CustomEvent,
    ErrorEvent,
    InterruptEvent,
    NodeCompleteEvent,
)
from soprano_streaming.runner import WorkflowStreamer, _serialize


# ------------------------------------------------------------------
# Helpers to build mock graph / engine
# ------------------------------------------------------------------


def _make_state_snapshot(*, next_nodes=None, values=None, tasks=None):
    """Build a lightweight mock that mimics LangGraph's StateSnapshot."""
    snap = SimpleNamespace()
    snap.next = tuple(next_nodes) if next_nodes else ()
    snap.values = values or {}
    snap.tasks = tasks or []
    return snap


def _make_interrupt_task(value):
    """Build a mock task with one interrupt carrying *value*."""
    interrupt = SimpleNamespace(value=value)
    task = SimpleNamespace(interrupts=[interrupt])
    return task


def _make_streamer(graph=None, engine=None):
    """Build a WorkflowStreamer with mock graph + engine, bypassing __init__."""
    if graph is None:
        graph = MagicMock()
    if engine is None:
        engine = MagicMock()
        engine.workflow_name = "test_workflow"
    streamer = object.__new__(WorkflowStreamer)
    streamer._graph = graph
    streamer._engine = engine
    return streamer


# ------------------------------------------------------------------
# _serialize (utility)
# ------------------------------------------------------------------


class TestSerialize:
    def test_primitives(self):
        assert _serialize("hello") == "hello"
        assert _serialize(42) == 42
        assert _serialize(3.14) == 3.14
        assert _serialize(True) is True
        assert _serialize(None) is None

    def test_dict(self):
        assert _serialize({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}

    def test_list(self):
        assert _serialize([1, "two", None]) == [1, "two", None]

    def test_nested(self):
        assert _serialize({"a": [1, {"b": 2}]}) == {"a": [1, {"b": 2}]}

    def test_non_serializable_becomes_str(self):
        class Custom:
            def __str__(self):
                return "custom-obj"

        assert _serialize(Custom()) == "custom-obj"


# ------------------------------------------------------------------
# stream() — fresh start, workflow completes without interrupts
# ------------------------------------------------------------------


class TestStreamFreshComplete:
    def test_yields_node_complete_then_complete(self):
        graph = MagicMock()

        # get_state on first call: no next (fresh start)
        # get_state on second call (resolve final): no next (complete)
        graph.get_state.side_effect = [
            _make_state_snapshot(next_nodes=[]),
            _make_state_snapshot(
                next_nodes=[],
                values={"greeting": "Hello!"},
            ),
        ]

        # graph.stream yields one node update
        graph.stream.return_value = iter([
            ("updates", {"build_greeting": {"greeting": "Hello!"}}),
        ])

        engine = MagicMock()
        engine.workflow_name = "test"
        outcome = MagicMock()
        outcome.message = "Hello!"
        outcome.options = []
        outcome.is_selectable = False
        engine.get_outcome_message.return_value = outcome

        streamer = _make_streamer(graph, engine)
        events = list(streamer.stream("t1", "hi"))

        assert len(events) == 2
        assert isinstance(events[0], NodeCompleteEvent)
        assert events[0].node == "build_greeting"
        assert isinstance(events[1], CompleteEvent)
        assert events[1].message == "Hello!"


# ------------------------------------------------------------------
# stream() — fresh start, workflow interrupts for user input
# ------------------------------------------------------------------


class TestStreamFreshInterrupt:
    def test_yields_node_complete_then_interrupt(self):
        graph = MagicMock()

        # First get_state: fresh
        graph.get_state.side_effect = [
            _make_state_snapshot(next_nodes=[]),
            _make_state_snapshot(
                next_nodes=["collect_name"],
                values={},
                tasks=[_make_interrupt_task("What is your name?")],
            ),
        ]

        graph.stream.return_value = iter([
            ("updates", {"collect_name": {"_status": "collect_name_collecting"}}),
        ])

        engine = MagicMock()
        engine.workflow_name = "test"
        engine.build_field_details.return_value = [{"name": "user_name", "value": None}]

        streamer = _make_streamer(graph, engine)
        events = list(streamer.stream("t1", ""))

        assert len(events) == 2
        assert isinstance(events[0], NodeCompleteEvent)
        assert isinstance(events[1], InterruptEvent)
        assert events[1].prompt == "What is your name?"
        assert events[1].field_details == [{"name": "user_name", "value": None}]

    def test_structured_interrupt_with_options(self):
        graph = MagicMock()

        interrupt_val = {
            "text": "Pick a color",
            "options": [{"text": "Red"}, {"text": "Blue"}],
            "is_selectable": True,
        }

        graph.get_state.side_effect = [
            _make_state_snapshot(next_nodes=[]),
            _make_state_snapshot(
                next_nodes=["collect_color"],
                values={},
                tasks=[_make_interrupt_task(interrupt_val)],
            ),
        ]

        graph.stream.return_value = iter([])

        engine = MagicMock()
        engine.workflow_name = "test"
        engine.build_field_details.return_value = []

        streamer = _make_streamer(graph, engine)
        events = list(streamer.stream("t1", ""))

        interrupt = events[-1]
        assert isinstance(interrupt, InterruptEvent)
        assert interrupt.prompt == "Pick a color"
        assert len(interrupt.options) == 2
        assert interrupt.is_selectable is True


# ------------------------------------------------------------------
# stream() — resume after interrupt
# ------------------------------------------------------------------


class TestStreamResume:
    def test_resume_sends_command(self):
        graph = MagicMock()

        # First get_state: has next (interrupted)
        graph.get_state.side_effect = [
            _make_state_snapshot(next_nodes=["collect_name"]),
            _make_state_snapshot(next_nodes=[], values={"user_name": "Alice"}),
        ]

        graph.stream.return_value = iter([
            ("updates", {"collect_name": {"user_name": "Alice"}}),
        ])

        engine = MagicMock()
        engine.workflow_name = "test"
        outcome = MagicMock()
        outcome.message = "Hello Alice!"
        outcome.options = []
        outcome.is_selectable = False
        engine.get_outcome_message.return_value = outcome

        streamer = _make_streamer(graph, engine)
        events = list(streamer.stream("t1", "Alice"))

        # Verify Command was used (resume path)
        call_args = graph.stream.call_args
        input_val = call_args[0][0]
        # It should be a Command object (has resume attribute)
        assert hasattr(input_val, "resume")
        assert input_val.resume == "Alice"


# ------------------------------------------------------------------
# stream() — custom events from get_stream_writer()
# ------------------------------------------------------------------


class TestStreamCustomEvents:
    def test_custom_events_yielded(self):
        graph = MagicMock()

        graph.get_state.side_effect = [
            _make_state_snapshot(next_nodes=[]),
            _make_state_snapshot(next_nodes=[], values={}),
        ]

        graph.stream.return_value = iter([
            ("custom", {"type": "color_list", "colors": ["red", "blue"]}),
            ("updates", {"suggest_colors": {"available_colors": ["red", "blue"]}}),
        ])

        engine = MagicMock()
        engine.workflow_name = "test"
        outcome = MagicMock()
        outcome.message = "Done"
        outcome.options = []
        outcome.is_selectable = False
        engine.get_outcome_message.return_value = outcome

        streamer = _make_streamer(graph, engine)
        events = list(streamer.stream("t1", ""))

        assert len(events) == 3
        assert isinstance(events[0], CustomEvent)
        assert events[0].payload["type"] == "color_list"
        assert isinstance(events[1], NodeCompleteEvent)
        assert isinstance(events[2], CompleteEvent)

    def test_multiple_custom_events_interleaved(self):
        graph = MagicMock()

        graph.get_state.side_effect = [
            _make_state_snapshot(next_nodes=[]),
            _make_state_snapshot(next_nodes=[], values={}),
        ]

        graph.stream.return_value = iter([
            ("custom", {"type": "token", "chunk": "a"}),
            ("custom", {"type": "token", "chunk": "b"}),
            ("updates", {"gen_node": {"result": "ab"}}),
        ])

        engine = MagicMock()
        engine.workflow_name = "test"
        outcome = MagicMock()
        outcome.message = "ab"
        outcome.options = []
        outcome.is_selectable = False
        engine.get_outcome_message.return_value = outcome

        streamer = _make_streamer(graph, engine)
        events = list(streamer.stream("t1", ""))

        custom_events = [e for e in events if isinstance(e, CustomEvent)]
        assert len(custom_events) == 2
        assert custom_events[0].payload["chunk"] == "a"
        assert custom_events[1].payload["chunk"] == "b"


# ------------------------------------------------------------------
# stream() — error handling
# ------------------------------------------------------------------


class TestStreamErrors:
    def test_exception_yields_error_event(self):
        graph = MagicMock()
        graph.get_state.side_effect = RuntimeError("connection lost")

        streamer = _make_streamer(graph)
        events = list(streamer.stream("t1", ""))

        assert len(events) == 1
        assert isinstance(events[0], ErrorEvent)
        assert "connection lost" in events[0].error

    def test_stream_exception_yields_error_event(self):
        graph = MagicMock()
        graph.get_state.return_value = _make_state_snapshot(next_nodes=[])

        def exploding_stream(*args, **kwargs):
            yield ("updates", {"node1": {"x": 1}})
            raise ValueError("mid-stream failure")

        graph.stream.return_value = exploding_stream()

        streamer = _make_streamer(graph)
        events = list(streamer.stream("t1", ""))

        # Should get the first node_complete, then an error
        assert isinstance(events[0], NodeCompleteEvent)
        assert isinstance(events[1], ErrorEvent)
        assert "mid-stream failure" in events[1].error


# ------------------------------------------------------------------
# from_env() — factory method
# ------------------------------------------------------------------


class TestFromEnv:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            WorkflowStreamer.from_env("workflow.yaml")

    @patch("soprano_streaming.runner.load_workflow")
    def test_passes_model_config(self, mock_load, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setenv("MODEL_NAME", "gpt-4o")

        mock_graph = MagicMock()
        mock_engine = MagicMock()
        mock_load.return_value = (mock_graph, mock_engine)

        streamer = WorkflowStreamer.from_env("test.yaml")

        mock_load.assert_called_once()
        call_kwargs = mock_load.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
        assert config["model_config"]["model_name"] == "gpt-4o"
        assert config["model_config"]["api_key"] == "sk-test-key"

    @patch("soprano_streaming.runner.load_workflow")
    def test_default_model_name(self, mock_load, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("MODEL_NAME", raising=False)

        mock_load.return_value = (MagicMock(), MagicMock())

        WorkflowStreamer.from_env("test.yaml")

        config = mock_load.call_args.kwargs.get("config") or mock_load.call_args[1].get("config")
        assert config["model_config"]["model_name"] == "gpt-4o-mini"


# ------------------------------------------------------------------
# Complete event with options from engine outcome
# ------------------------------------------------------------------


class TestCompleteWithOptions:
    def test_outcome_options_forwarded(self):
        graph = MagicMock()

        graph.get_state.side_effect = [
            _make_state_snapshot(next_nodes=[]),
            _make_state_snapshot(next_nodes=[], values={}),
        ]
        graph.stream.return_value = iter([])

        engine = MagicMock()
        engine.workflow_name = "test"
        outcome = MagicMock()
        outcome.message = "Choose next"
        outcome.options = [{"text": "A"}, {"text": "B"}]
        outcome.is_selectable = True
        engine.get_outcome_message.return_value = outcome

        streamer = _make_streamer(graph, engine)
        events = list(streamer.stream("t1", ""))

        complete = events[-1]
        assert isinstance(complete, CompleteEvent)
        assert complete.options == [{"text": "A"}, {"text": "B"}]
        assert complete.is_selectable is True

    def test_none_options_become_empty_list(self):
        graph = MagicMock()

        graph.get_state.side_effect = [
            _make_state_snapshot(next_nodes=[]),
            _make_state_snapshot(next_nodes=[], values={}),
        ]
        graph.stream.return_value = iter([])

        engine = MagicMock()
        engine.workflow_name = "test"
        outcome = MagicMock()
        outcome.message = "Done"
        outcome.options = None
        outcome.is_selectable = False
        engine.get_outcome_message.return_value = outcome

        streamer = _make_streamer(graph, engine)
        events = list(streamer.stream("t1", ""))

        assert events[-1].options == []
