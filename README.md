# soprano-streaming

Real-time streaming wrapper for [soprano-sdk](https://pypi.org/project/soprano-sdk/) workflows.

## What this library does

`soprano-sdk` provides a YAML-driven workflow engine with AI agent integration
powered by LangGraph. The standard way to execute a workflow is via
`WorkflowTool.execute()`, which runs the entire turn synchronously and returns
a single `WorkflowResult`.

**soprano-streaming** replaces that with a generator-based API that yields
typed events as each graph node executes. This enables:

- **Server-Sent Events (SSE)** — push node updates and LLM tokens to the browser in real time
- **Mid-node streaming** — workflow functions can emit data *during* execution (e.g. token-by-token LLM output, static data lists) via LangGraph's `get_stream_writer()`
- **Typed events** — no more parsing `__WORKFLOW_INTERRUPT__` prefix strings; receive `InterruptEvent`, `CompleteEvent`, etc.
- **Transport-agnostic** — the event stream is a plain Python generator; map it to SSE, WebSockets, gRPC, or anything else

## Installation

```bash
pip install soprano-streaming

# With the optional SSE helper for FastAPI:
pip install soprano-streaming[sse]
```

## Quick start

### 1. Create the streamer

```python
from soprano_streaming import WorkflowStreamer

# Explicit configuration
streamer = WorkflowStreamer(
    yaml_path="workflow.yaml",
    config={
        "model_config": {
            "model_name": "gpt-4o-mini",
            "api_key": "sk-...",
        },
    },
)

# Or from environment variables (OPENAI_API_KEY, MODEL_NAME)
streamer = WorkflowStreamer.from_env("workflow.yaml")
```

### 2. Stream a conversation turn

```python
from soprano_streaming import (
    InterruptEvent,
    CompleteEvent,
    CustomEvent,
    NodeCompleteEvent,
    ErrorEvent,
)

for event in streamer.stream(thread_id="t1", message="hello"):
    match event:
        case NodeCompleteEvent():
            print(f"[node done] {event.node}")

        case CustomEvent():
            print(f"[stream] {event.payload}")

        case InterruptEvent():
            print(f"[bot] {event.prompt}")
            # Collect user input, then call stream() again with same thread_id

        case CompleteEvent():
            print(f"[done] {event.message}")

        case ErrorEvent():
            print(f"[error] {event.error}")
```

### 3. Resume after an interrupt

```python
# Same thread_id, new message
for event in streamer.stream(thread_id="t1", message=user_response):
    ...
```

### 4. Wire to a FastAPI SSE endpoint

```python
import uuid
from fastapi import FastAPI
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from soprano_streaming import WorkflowStreamer
from soprano_streaming.sse import events_to_sse

app = FastAPI()
streamer: WorkflowStreamer = None

@app.on_event("startup")
def startup():
    global streamer
    streamer = WorkflowStreamer.from_env("workflow.yaml")

class ChatRequest(BaseModel):
    thread_id: str | None = None
    message: str | None = None

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

## API Reference

### `WorkflowStreamer`

The main entry point. Wraps a soprano-sdk workflow and exposes streaming.

| Method | Description |
|---|---|
| `__init__(yaml_path, config, checkpointer=None, mfa_config=None)` | Create a streamer with explicit configuration |
| `from_env(yaml_path, checkpointer=None, mfa_config=None)` | Create from `OPENAI_API_KEY` and `MODEL_NAME` env vars |
| `stream(thread_id, message=None)` | Execute one turn; yields `WorkflowEvent` objects |
| `workflow_name` | Property — name from the YAML |

### Event types

All events are plain dataclasses with no SDK dependencies.

| Event | Fields | When emitted |
|---|---|---|
| `NodeCompleteEvent` | `node`, `state_update` | After each graph node finishes |
| `CustomEvent` | `payload` | Mid-node, via `get_stream_writer()` |
| `InterruptEvent` | `prompt`, `options`, `is_selectable`, `field_details` | Workflow paused for user input |
| `CompleteEvent` | `message`, `options`, `is_selectable` | Workflow reached a terminal outcome |
| `ErrorEvent` | `error` | Unrecoverable error |

### `events_to_sse(events, thread_id=None)`

Optional helper (requires `soprano-streaming[sse]`). Converts event generator
to SSE dicts for `sse_starlette.EventSourceResponse`.

## SSE Event Reference

When using `events_to_sse()`, clients receive these SSE event types:

| SSE event | Payload keys |
|---|---|
| `node_complete` | `thread_id`, `node`, `state_update` |
| `custom` | `thread_id` + custom payload from `get_stream_writer()` |
| `interrupt` | `thread_id`, `type`, `prompt`, `options`, `is_selectable`, `field_details` |
| `complete` | `thread_id`, `message`, `options`, `is_selectable` |
| `error` | `error` |
| `done` | *(empty — signals end of stream)* |

## Mid-node streaming

Workflow functions called by `call_function` steps can emit real-time
data using LangGraph's `get_stream_writer()`. These appear as
`CustomEvent` objects in the stream:

```python
from langgraph.config import get_stream_writer

def my_step(state: dict):
    writer = get_stream_writer()

    # Emit static data immediately
    writer({"type": "product_list", "items": [...]})

    # Stream LLM tokens
    for token in generate_tokens():
        writer({"type": "llm_token", "chunk": token, "done": False})
    writer({"type": "llm_token", "chunk": "", "done": True})

    return result
```

## Migrating from WorkflowTool.execute()

See [docs/MIGRATION.md](docs/MIGRATION.md) for a complete step-by-step
migration guide with before/after code examples.

**TL;DR:**

| Before | After |
|---|---|
| `WorkflowTool(yaml_path, name, desc, config)` | `WorkflowStreamer(yaml_path, config)` |
| `tool.execute(thread_id, message, context)` | `streamer.stream(thread_id, message)` |
| `result.startswith("__WORKFLOW_INTERRUPT__")` | `isinstance(event, InterruptEvent)` |
| `result.text` | `event.prompt` (interrupt) or `event.message` (complete) |
| `result.options` | `event.options` |
| `result.field_details` | `event.field_details` |

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes (for `from_env()`) | — | OpenAI API key |
| `MODEL_NAME` | No | `gpt-4o-mini` | LLM model name |

## Project structure

```
soprano_streaming/          # The library
    __init__.py             # Public API exports
    events.py               # Event dataclasses (the public contract)
    runner.py               # WorkflowStreamer (all SDK imports live here)
    sse.py                  # Optional SSE mapping helper

examples/greeting_bot/      # Reference implementation
    main.py                 # FastAPI controller
    functions.py            # Workflow step functions with get_stream_writer()
    workflow.yaml           # Workflow definition
    client.py               # Terminal chat client

docs/
    MIGRATION.md            # Migration guide from WorkflowTool.execute()
```

## Running the example

```bash
cd examples/greeting_bot

export OPENAI_API_KEY="sk-..."
python main.py          # Terminal 1 — starts server on :8000
python client.py        # Terminal 2 — interactive chat
```
