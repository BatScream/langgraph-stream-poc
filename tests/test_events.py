"""TDD tests for soprano_streaming.events — the public contract."""

from soprano_streaming.events import (
    CompleteEvent,
    CustomEvent,
    ErrorEvent,
    InterruptEvent,
    NodeCompleteEvent,
    WorkflowEvent,
)


# ------------------------------------------------------------------
# Construction — each event builds with required fields
# ------------------------------------------------------------------


class TestNodeCompleteEvent:
    def test_construction(self):
        event = NodeCompleteEvent(node="collect_name", state_update={"user_name": "Alice"})
        assert event.node == "collect_name"
        assert event.state_update == {"user_name": "Alice"}

    def test_state_update_can_be_empty(self):
        event = NodeCompleteEvent(node="noop", state_update={})
        assert event.state_update == {}


class TestCustomEvent:
    def test_construction(self):
        payload = {"type": "llm_token", "chunk": "Hello"}
        event = CustomEvent(payload=payload)
        assert event.payload == payload

    def test_payload_is_arbitrary_dict(self):
        event = CustomEvent(payload={"any": "thing", "nested": {"ok": True}})
        assert event.payload["nested"]["ok"] is True


class TestInterruptEvent:
    def test_construction_minimal(self):
        event = InterruptEvent(prompt="What is your name?")
        assert event.prompt == "What is your name?"
        assert event.options == []
        assert event.is_selectable is False
        assert event.field_details == []

    def test_construction_full(self):
        event = InterruptEvent(
            prompt="Pick a color",
            options=[{"text": "Red", "subtext": ""}],
            is_selectable=True,
            field_details=[{"name": "color", "value": None}],
        )
        assert event.prompt == "Pick a color"
        assert len(event.options) == 1
        assert event.is_selectable is True
        assert event.field_details[0]["name"] == "color"

    def test_defaults_are_independent_instances(self):
        """Each event must get its own default list, not a shared mutable."""
        a = InterruptEvent(prompt="a")
        b = InterruptEvent(prompt="b")
        a.options.append({"text": "X"})
        assert b.options == []


class TestCompleteEvent:
    def test_construction_minimal(self):
        event = CompleteEvent(message="Done!")
        assert event.message == "Done!"
        assert event.options == []
        assert event.is_selectable is False

    def test_construction_with_options(self):
        event = CompleteEvent(
            message="Choose next",
            options=[{"text": "A"}],
            is_selectable=True,
        )
        assert event.is_selectable is True
        assert len(event.options) == 1

    def test_defaults_are_independent_instances(self):
        a = CompleteEvent(message="a")
        b = CompleteEvent(message="b")
        a.options.append({"text": "X"})
        assert b.options == []


class TestErrorEvent:
    def test_construction(self):
        event = ErrorEvent(error="something broke")
        assert event.error == "something broke"


# ------------------------------------------------------------------
# Union type — all events are part of WorkflowEvent
# ------------------------------------------------------------------


class TestWorkflowEventUnion:
    def test_node_complete_is_workflow_event(self):
        event = NodeCompleteEvent(node="x", state_update={})
        assert isinstance(event, NodeCompleteEvent)

    def test_all_types_match_in_structural_pattern(self):
        """Verify match/case works with all event types."""
        events = [
            NodeCompleteEvent(node="n", state_update={}),
            CustomEvent(payload={}),
            InterruptEvent(prompt="q"),
            CompleteEvent(message="done"),
            ErrorEvent(error="err"),
        ]
        labels = []
        for event in events:
            match event:
                case NodeCompleteEvent():
                    labels.append("node")
                case CustomEvent():
                    labels.append("custom")
                case InterruptEvent():
                    labels.append("interrupt")
                case CompleteEvent():
                    labels.append("complete")
                case ErrorEvent():
                    labels.append("error")
        assert labels == ["node", "custom", "interrupt", "complete", "error"]
