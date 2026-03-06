"""TDD tests for soprano_streaming.sse — the SSE mapping helper."""

import json

from soprano_streaming.events import (
    CompleteEvent,
    CustomEvent,
    ErrorEvent,
    InterruptEvent,
    NodeCompleteEvent,
)
from soprano_streaming.sse import events_to_sse


THREAD_ID = "test-thread-123"


def _collect(events, thread_id=THREAD_ID):
    """Run events_to_sse and return the list of SSE dicts."""
    return list(events_to_sse(events, thread_id=thread_id))


def _parse_data(sse_dict):
    """Parse the JSON in the 'data' field."""
    return json.loads(sse_dict["data"])


# ------------------------------------------------------------------
# Individual event mapping
# ------------------------------------------------------------------


class TestNodeCompleteEventSSE:
    def test_event_type(self):
        result = _collect([NodeCompleteEvent(node="step1", state_update={"x": 1})])
        assert result[0]["event"] == "node_complete"

    def test_payload_contains_thread_id_and_node(self):
        result = _collect([NodeCompleteEvent(node="step1", state_update={"x": 1})])
        data = _parse_data(result[0])
        assert data["thread_id"] == THREAD_ID
        assert data["node"] == "step1"
        assert data["state_update"] == {"x": 1}


class TestCustomEventSSE:
    def test_event_type(self):
        result = _collect([CustomEvent(payload={"type": "token", "chunk": "hi"})])
        assert result[0]["event"] == "custom"

    def test_payload_merged_with_thread_id(self):
        result = _collect([CustomEvent(payload={"type": "token", "chunk": "hi"})])
        data = _parse_data(result[0])
        assert data["thread_id"] == THREAD_ID
        assert data["type"] == "token"
        assert data["chunk"] == "hi"


class TestInterruptEventSSE:
    def test_event_type(self):
        result = _collect([InterruptEvent(prompt="Name?")])
        assert result[0]["event"] == "interrupt"

    def test_payload_fields(self):
        event = InterruptEvent(
            prompt="Pick one",
            options=[{"text": "A"}],
            is_selectable=True,
            field_details=[{"name": "color", "value": None}],
        )
        data = _parse_data(_collect([event])[0])
        assert data["thread_id"] == THREAD_ID
        assert data["type"] == "user_input"
        assert data["prompt"] == "Pick one"
        assert data["options"] == [{"text": "A"}]
        assert data["is_selectable"] is True
        assert data["field_details"] == [{"name": "color", "value": None}]

    def test_defaults(self):
        data = _parse_data(_collect([InterruptEvent(prompt="q")])[0])
        assert data["options"] == []
        assert data["is_selectable"] is False
        assert data["field_details"] == []


class TestCompleteEventSSE:
    def test_event_type(self):
        result = _collect([CompleteEvent(message="All done")])
        assert result[0]["event"] == "complete"

    def test_payload_fields(self):
        data = _parse_data(_collect([CompleteEvent(message="Done", options=[{"text": "OK"}], is_selectable=True)])[0])
        assert data["thread_id"] == THREAD_ID
        assert data["message"] == "Done"
        assert data["options"] == [{"text": "OK"}]
        assert data["is_selectable"] is True


class TestErrorEventSSE:
    def test_event_type(self):
        result = _collect([ErrorEvent(error="boom")])
        assert result[0]["event"] == "error"

    def test_payload(self):
        data = _parse_data(_collect([ErrorEvent(error="boom")])[0])
        assert data["error"] == "boom"


# ------------------------------------------------------------------
# Stream-level behaviour
# ------------------------------------------------------------------


class TestEventsToSSEStream:
    def test_done_sentinel_appended(self):
        """Stream always ends with a 'done' event."""
        result = _collect([CompleteEvent(message="ok")])
        assert result[-1] == {"event": "done", "data": ""}

    def test_empty_stream_still_emits_done(self):
        result = _collect([])
        assert result == [{"event": "done", "data": ""}]

    def test_preserves_order(self):
        events = [
            NodeCompleteEvent(node="a", state_update={}),
            CustomEvent(payload={"type": "x"}),
            InterruptEvent(prompt="q"),
        ]
        result = _collect(events)
        types = [d["event"] for d in result]
        assert types == ["node_complete", "custom", "interrupt", "done"]

    def test_generates_thread_id_when_none(self):
        """When thread_id is None, a UUID is generated."""
        result = list(events_to_sse([CompleteEvent(message="ok")], thread_id=None))
        data = _parse_data(result[0])
        assert "thread_id" in data
        assert len(data["thread_id"]) > 0

    def test_multiple_custom_events_streamed_individually(self):
        events = [
            CustomEvent(payload={"type": "token", "chunk": "a"}),
            CustomEvent(payload={"type": "token", "chunk": "b"}),
            CustomEvent(payload={"type": "token", "chunk": "c"}),
        ]
        result = _collect(events)
        # 3 custom + 1 done
        assert len(result) == 4
        chunks = [_parse_data(r)["chunk"] for r in result[:3]]
        assert chunks == ["a", "b", "c"]
