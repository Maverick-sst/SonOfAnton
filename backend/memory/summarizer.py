"""
Conversation Summarizer

Called when history exceeds 20 turns to prevent context window bloat.
Summarizes older turns, keeps last 6 as-is.
"""

from openai import OpenAI
from backend.memory.session_store import get_redis_client
from backend.config import settings
from backend.orchestrator.prompts import SUMMARIZE_PROMPT
import json

client = None


def _get_client():
    global client
    if client is None:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return client


def maybe_summarize(history: list[dict], session_id: str) -> tuple[str, list[dict]]:
    """
    Summarizes old turns if history > 20 turns.
    Returns (summary_string, recent_history_last_6_turns)
    """
    r = get_redis_client()

    # Check if summary already exists
    existing_summary = None
    if r:
        try:
            existing_summary = r.get(f"session:{session_id}:summary")
        except Exception:
            pass

    to_summarize = history[:-6]   # Everything except last 6
    recent = history[-6:]          # Keep last 6 as-is

    convo_text = "\n".join([
        f"{turn['role'].upper()}: {turn['content']}"
        for turn in to_summarize
    ])

    # Prepend existing summary if available
    if existing_summary:
        convo_text = f"Previous summary:\n{existing_summary}\n\nNew turns:\n{convo_text}"

    try:
        c = _get_client()
        resp = c.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": SUMMARIZE_PROMPT.format(conversation=convo_text)
            }],
            max_tokens=300
        )
        summary = resp.choices[0].message.content
    except Exception as e:
        print(f"[Summarizer] Error: {e}")
        summary = existing_summary or "Conversation with a recruiter about Rehan's background."

    # Store summary
    if r:
        try:
            r.setex(f"session:{session_id}:summary", 7200, summary)
        except Exception:
            pass

    return summary, recent
