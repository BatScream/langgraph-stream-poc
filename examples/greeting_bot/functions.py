import time

from langgraph.config import get_stream_writer


COLORS_DB = [
    {"name": "Crimson Red", "hex": "#DC143C"},
    {"name": "Ocean Blue", "hex": "#0077BE"},
    {"name": "Forest Green", "hex": "#228B22"},
    {"name": "Sunset Orange", "hex": "#FD5E53"},
    {"name": "Royal Purple", "hex": "#7851A9"},
    {"name": "Goldenrod", "hex": "#DAA520"},
]


def suggest_colors(state: dict) -> list:
    """Emit a static list of colors to the stream, then return it as state."""
    writer = get_stream_writer()
    name = state.get("user_name", "friend")

    writer({
        "type": "color_list",
        "message": f"Here are some colors to choose from, {name}:",
        "colors": COLORS_DB,
    })

    return COLORS_DB


def generate_color_recommendation(state: dict) -> str:
    """Simulate an LLM generating a recommendation, streaming tokens as they arrive."""
    writer = get_stream_writer()
    name = state.get("user_name", "friend")
    color = state.get("favorite_color", "that color")

    chunks = [
        f"Great choice, {name}! ",
        f"{color} is associated with ",
        "creativity and calm. ",
        "It pairs beautifully with soft whites ",
        "and warm metallics.",
    ]

    accumulated = ""
    for chunk in chunks:
        accumulated += chunk
        time.sleep(0.3)  # simulate LLM latency
        writer({
            "type": "llm_token",
            "node": "generate_recommendation",
            "chunk": chunk,
            "accumulated": accumulated,
            "done": False,
        })

    writer({
        "type": "llm_token",
        "node": "generate_recommendation",
        "chunk": "",
        "accumulated": accumulated,
        "done": True,
    })

    return accumulated


def build_greeting(state: dict) -> str:
    name = state.get("user_name", "friend")
    color = state.get("favorite_color", "your color")
    recommendation = state.get("color_recommendation", "")
    return f"Hello {name}! Your favorite color is {color}. {recommendation} Welcome aboard!"
