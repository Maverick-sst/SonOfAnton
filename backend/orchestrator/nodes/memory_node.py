"""
Memory Node — Runs BEFORE the router.

Loads conversation history from Redis into state.
Triggers summarization if history exceeds 20 turns.
"""

from backend.memory.session_store import get_history
from backend.memory.summarizer import maybe_summarize
from backend.orchestrator.state import AntonState


def run(state: AntonState) -> AntonState:
    """Load conversation history and optional summary into state."""
    session_id = state["session_id"]

    # Load history from Redis
    history = get_history(session_id)

    # Summarize if too long (> 20 turns)
    summary = state.get("conversation_summary")
    if len(history) > 20:
        summary, history = maybe_summarize(history, session_id)

    return {
        **state,
        "conversation_history": history,
        "conversation_summary": summary
    }
