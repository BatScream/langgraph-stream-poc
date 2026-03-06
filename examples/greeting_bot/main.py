"""Example FastAPI controller using soprano-streaming.

This is a minimal example showing how a client application integrates
the library.  The controller is intentionally thin — it only wires HTTP
to the streaming helper.
"""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from soprano_streaming import WorkflowStreamer
from soprano_streaming.sse import events_to_sse

app = FastAPI(title="Greeting Bot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HERE = Path(__file__).resolve().parent
streamer: WorkflowStreamer = None  # type: ignore[assignment]


@app.on_event("startup")
def startup():
    global streamer
    streamer = WorkflowStreamer.from_env(str(HERE / "workflow.yaml"))


class ChatRequest(BaseModel):
    thread_id: Optional[str] = None
    message: Optional[str] = None


@app.post("/chat")
def chat(req: ChatRequest):
    thread_id = req.thread_id or str(uuid.uuid4())
    return EventSourceResponse(
        events_to_sse(
            streamer.stream(thread_id, req.message),
            thread_id=thread_id,
        )
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
