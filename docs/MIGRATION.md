# Migration Guide: WorkflowTool.execute() → soprano-streaming

This guide helps you migrate from the synchronous `WorkflowTool.execute()` API
to the streaming `WorkflowStreamer.stream()` API provided by `soprano-streaming`.

## Why migrate?

| | `WorkflowTool.execute()` | `WorkflowStreamer.stream()` |
|---|---|---|
| **Response model** | Returns one `WorkflowResult` per call | Yields multiple typed events per call |
| **Intermediate data** | Not visible — you only see the final result | `NodeCompleteEvent` and `CustomEvent` arrive as nodes execute |
| **Mid-node streaming** | Not supported | Functions can emit `CustomEvent` via `get_stream_writer()` (e.g. LLM tokens) |
| **Transport** | Caller must poll or block | Natural fit for SSE, WebSockets, or any push transport |
| **Interrupt handling** | Caller parses `__WORKFLOW_INTERRUPT__` prefix strings | Caller receives a typed `InterruptEvent` dataclass |
| **Error handling** | Exceptions or error strings embedded in `WorkflowResult` | Typed `ErrorEvent` in the stream |

---

## Step 1: Install soprano-streaming

```bash
pip install soprano-streaming
# or
uv add soprano-streaming
```

The library depends on `soprano-sdk>=0.2.70` — it will be installed automatically.

---

## Step 2: Replace WorkflowTool with WorkflowStreamer

### Before

```python
from soprano_sdk import WorkflowTool

tool = WorkflowTool(
    yaml_path="workflow.yaml",
    name="my_workflow",
    description="My workflow",
    config={
        "model_config": {
            "model_name": "gpt-4o-mini",
            "api_key": "sk-...",
        },
    },
)
```

### After

```python
from soprano_streaming import WorkflowStreamer

streamer = WorkflowStreamer(
    yaml_path="workflow.yaml",
    config={
        "model_config": {
            "model_name": "gpt-4o-mini",
            "api_key": "sk-...",
        },
    },
)
```

Or use the environment-variable shortcut:

```python
# Reads OPENAI_API_KEY and MODEL_NAME from env
streamer = WorkflowStreamer.from_env("workflow.yaml")
```

**Parameter mapping:**

| `WorkflowTool` | `WorkflowStreamer` | Notes |
|---|---|---|
| `yaml_path` | `yaml_path` | Same |
| `name` | *(removed)* | Not needed — the streamer is not an agent tool |
| `description` | *(removed)* | Not needed |
| `config` | `config` | Same dict structure |
| `checkpointer` | `checkpointer` | Same, defaults to `InMemorySaver()` |
| `mfa_config` | `mfa_config` | Same |

---

## Step 3: Replace execute() / resume() with stream()

### Before — synchronous execute with interrupt parsing

```python
import uuid

thread_id = str(uuid.uuid4())

# First turn
result = tool.execute(
    thread_id=thread_id,
    user_message="hello",
    initial_context={"customer_id": "123"},
)

if result.startswith("__WORKFLOW_INTERRUPT__"):
    prompt = result.text
    options = result.options
    is_selectable = result.is_selectable
    field_details = result.field_details
    # ... show prompt to user, collect response ...

    # Resume
    result = tool.execute(
        thread_id=thread_id,
        user_message=user_response,
        initial_context={"customer_id": "123"},
    )

# Check completion
if not result.startswith("__WORKFLOW_INTERRUPT__"):
    final_message = result.text
```

### After — streaming with typed events

```python
from soprano_streaming import (
    WorkflowStreamer,
    InterruptEvent,
    CompleteEvent,
    CustomEvent,
    NodeCompleteEvent,
    ErrorEvent,
)

thread_id = "unique-thread-id"

for event in streamer.stream(thread_id=thread_id, message="hello"):
    match event:
        case NodeCompleteEvent():
            # A graph node finished — optional, for progress tracking
            print(f"Node {event.node} done")

        case CustomEvent():
            # Mid-node data (e.g. LLM tokens, static lists)
            print(f"Stream data: {event.payload}")

        case InterruptEvent():
            # Workflow paused — show prompt to user
            prompt = event.prompt
            options = event.options
            is_selectable = event.is_selectable
            field_details = event.field_details

        case CompleteEvent():
            # Workflow finished
            final_message = event.message

        case ErrorEvent():
            # Something went wrong
            print(f"Error: {event.error}")

# To resume after an InterruptEvent, call stream() again
# with the same thread_id and the user's response:
for event in streamer.stream(thread_id=thread_id, message=user_response):
    # ... handle events same as above ...
```

**Key differences:**

| Concept | `WorkflowTool` | `WorkflowStreamer` |
|---|---|---|
| Start a workflow | `execute(thread_id, user_message, initial_context)` | `stream(thread_id, message)` |
| Resume after interrupt | `execute(thread_id, user_message, initial_context)` or `resume(thread_id, value)` | `stream(thread_id, message)` — same method |
| Detect interrupt | `result.startswith("__WORKFLOW_INTERRUPT__")` | `isinstance(event, InterruptEvent)` |
| Detect completion | `not result.startswith("__WORKFLOW_INTERRUPT__")` | `isinstance(event, CompleteEvent)` |
| Get prompt text | `result.text` | `event.prompt` |
| Get options | `result.options` | `event.options` |
| Get field details | `result.field_details` | `event.field_details` |
| Intermediate data | Not available | `NodeCompleteEvent` and `CustomEvent` |

---

## Step 4: Update your controller to use SSE

### Before — JSON response

```python
@app.post("/chat")
def chat(req: ChatRequest):
    result = tool.execute(
        thread_id=req.thread_id,
        user_message=req.message,
        initial_context={},
    )
    return {"result": result.text, "options": result.options}
```

### After — SSE streaming (using the built-in helper)

```python
from sse_starlette.sse import EventSourceResponse
from soprano_streaming.sse import events_to_sse

@app.post("/chat")
def chat(req: ChatRequest):
    thread_id = req.thread_id or str(uuid.uuid4())
    return EventSourceResponse(
        events_to_sse(
            streamer.stream(thread_id, req.message),
            thread_id=thread_id,
        )
    )
```

### After — SSE streaming (manual mapping)

If you need custom SSE event formatting, map events yourself:

```python
import json
from soprano_streaming import InterruptEvent, CompleteEvent, CustomEvent

@app.post("/chat")
def chat(req: ChatRequest):
    thread_id = req.thread_id or str(uuid.uuid4())

    def generate():
        for event in streamer.stream(thread_id, req.message):
            match event:
                case InterruptEvent():
                    yield {
                        "event": "question",
                        "data": json.dumps({"prompt": event.prompt}),
                    }
                case CompleteEvent():
                    yield {
                        "event": "answer",
                        "data": json.dumps({"message": event.message}),
                    }
                case CustomEvent():
                    yield {
                        "event": "progress",
                        "data": json.dumps(event.payload),
                    }
        yield {"event": "done", "data": ""}

    return EventSourceResponse(generate())
```

---

## Step 5: Add mid-node streaming to your workflow functions (optional)

Workflow functions called by `call_function` steps can emit real-time
data using LangGraph's `get_stream_writer()`.  These become
`CustomEvent` objects in the stream.

```python
from langgraph.config import get_stream_writer

def my_function(state: dict):
    writer = get_stream_writer()

    # Emit a static data list immediately
    writer({"type": "options_list", "items": ["A", "B", "C"]})

    # Simulate LLM token streaming
    for token in generate_tokens():
        writer({"type": "llm_token", "chunk": token, "done": False})
    writer({"type": "llm_token", "chunk": "", "done": True})

    return result
```

---

## SSE Event Reference

When using the built-in `events_to_sse()` helper, clients receive
these SSE event types:

| SSE Event | Source Event | When |
|---|---|---|
| `node_complete` | `NodeCompleteEvent` | A graph node finished |
| `custom` | `CustomEvent` | Mid-node data from `get_stream_writer()` |
| `interrupt` | `InterruptEvent` | Workflow paused for user input |
| `complete` | `CompleteEvent` | Workflow reached terminal outcome |
| `error` | `ErrorEvent` | Unrecoverable error |
| `done` | *(sentinel)* | Stream ended |

---

## Checklist

- [ ] Replace `WorkflowTool(...)` with `WorkflowStreamer(...)` or `WorkflowStreamer.from_env(...)`
- [ ] Replace `tool.execute()` / `tool.resume()` with `streamer.stream()`
- [ ] Replace `result.startswith("__WORKFLOW_INTERRUPT__")` checks with `isinstance(event, InterruptEvent)`
- [ ] Replace `result.text` / `result.options` with `event.prompt` / `event.options`
- [ ] Update controller to return `EventSourceResponse` (or your transport of choice)
- [ ] Update frontend to consume SSE events instead of JSON responses
- [ ] (Optional) Add `get_stream_writer()` calls to workflow functions for mid-node streaming
