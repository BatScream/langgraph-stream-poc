"""Terminal chat client that connects to the SSE streaming endpoint."""

import json
import sys

import httpx

BASE_URL = "http://localhost:8000"


def chat_loop():
    thread_id = None

    print("=" * 50)
    print("  Greeting Bot  (type 'quit' to exit)")
    print("=" * 50)
    print()

    # Start the conversation with an empty message
    user_message = ""
    first_turn = True

    while True:
        if not first_turn:
            try:
                user_message = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if user_message.lower() in ("quit", "exit"):
                print("Goodbye!")
                break

        first_turn = False

        payload = {"message": user_message}
        if thread_id:
            payload["thread_id"] = thread_id

        try:
            with httpx.stream(
                "POST",
                f"{BASE_URL}/chat",
                json=payload,
                timeout=120.0,
            ) as response:
                response.raise_for_status()
                done = False

                for line in response.iter_lines():
                    if not line:
                        continue

                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                        continue

                    if not line.startswith("data:"):
                        continue

                    raw = line[len("data:"):].strip()
                    if not raw:
                        continue

                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Update thread_id from any event
                    if isinstance(data, dict) and "thread_id" in data:
                        thread_id = data["thread_id"]

                    if event_type == "custom":
                        _handle_custom(data)
                    elif event_type == "node_complete":
                        _handle_node_complete(data)
                    elif event_type == "interrupt":
                        _handle_interrupt(data)
                    elif event_type == "complete":
                        _handle_complete(data)
                        done = True
                    elif event_type == "error":
                        print(f"\n[error] {data.get('error', 'unknown')}")
                        done = True
                    elif event_type == "done":
                        pass

                if done:
                    print("\n[session ended — start a new one by running the client again]")
                    break

        except httpx.ConnectError:
            print(f"\n[error] Cannot connect to {BASE_URL}. Is the server running?")
            break
        except httpx.HTTPStatusError as exc:
            print(f"\n[error] HTTP {exc.response.status_code}")
            break


def _handle_custom(data: dict):
    """Handle mid-node custom stream events."""
    msg_type = data.get("type", "")

    if msg_type == "color_list":
        print(f"\nBot: {data.get('message', '')}")
        for color in data.get("colors", []):
            print(f"  - {color['name']}  ({color['hex']})")

    elif msg_type == "llm_token":
        chunk = data.get("chunk", "")
        if data.get("done"):
            print()  # newline after final token
        else:
            if data.get("accumulated") == chunk:
                # First chunk — print prefix
                sys.stdout.write("\nBot: ")
            sys.stdout.write(chunk)
            sys.stdout.flush()


def _handle_node_complete(data: dict):
    """Handle node completion events (state updates)."""
    # Silently track; the interesting data was already shown via custom events
    pass


def _handle_interrupt(data: dict):
    """Handle workflow interrupt (bot asking a question)."""
    prompt = data.get("prompt", "")
    if prompt:
        print(f"\nBot: {prompt}")

    options = data.get("options", [])
    if options:
        for i, opt in enumerate(options, 1):
            text = opt.get("text", opt) if isinstance(opt, dict) else opt
            print(f"  {i}. {text}")


def _handle_complete(data: dict):
    """Handle workflow completion."""
    message = data.get("message", "")
    if message:
        print(f"\nBot: {message}")


if __name__ == "__main__":
    chat_loop()
