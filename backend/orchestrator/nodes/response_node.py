"""
Response Node — Final Response Synthesis

Combines knowledge_answer + scheduling_answer into a single natural response.
Strips markdown for voice channel.
"""

import re
from backend.orchestrator.state import AntonState
from backend.orchestrator.prompts import CHITCHAT_PROMPT, ANTON_SYSTEM_PROMPT
from backend.config import settings
from openai import OpenAI

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def run(state: AntonState) -> AntonState:
    parts = []

    if state.get("knowledge_answer"):
        parts.append(state["knowledge_answer"])

    if state.get("scheduling_answer"):
        parts.append(state["scheduling_answer"])

    if not parts:
        # Chitchat fallback
        parts.append(_generate_chitchat_response(state))

    final = " ".join(parts) if len(parts) > 1 else parts[0]

    # For voice: strip markdown for TTS readability
    if state.get("channel") == "voice":
        final = _strip_markdown(final)

    return {**state, "final_response": final}


def _generate_chitchat_response(state: AntonState) -> str:
    try:
        c = _get_client()
        resp = c.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ANTON_SYSTEM_PROMPT},
                {"role": "user", "content": CHITCHAT_PROMPT.format(message=state["user_message"])}
            ],
            temperature=0.7,
            max_tokens=100
        )
        return resp.choices[0].message.content
    except Exception:
        return (
            "Hi! I'm Anton, Rehan's AI representative. "
            "I can tell you about his background, projects, and skills, "
            "or help schedule an interview. What would you like to know?"
        )


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting for voice TTS readability."""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)   # bold
    text = re.sub(r'\*(.*?)\*', r'\1', text)        # italic
    text = re.sub(r'`(.*?)`', r'\1', text)          # code
    text = re.sub(r'#{1,6}\s', '', text)             # headers
    text = re.sub(r'[-*•]\s', '', text)              # bullets
    return text.strip()
