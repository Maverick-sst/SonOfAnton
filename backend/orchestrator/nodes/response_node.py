"""
Response Node — Final Response Synthesis

Combines knowledge_answer + scheduling_answer into a single natural response.
Strips markdown for voice channel.

Also exposes `stream_voice_response()` for the Vapi Custom LLM endpoint:
an async generator that re-issues the final LLM hop with `stream=True` so the
caller hears Anton within ~one LLM round-trip instead of waiting for the
entire graph to finish. The synchronous `run()` is unchanged.
"""

import re
from typing import AsyncIterator
from backend.orchestrator.state import AntonState
from backend.orchestrator.prompts import CHITCHAT_PROMPT, ANTON_SYSTEM_PROMPT
from backend.config import settings
from openai import OpenAI

_client = None
_async_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client

def _get_async_client():
    global _async_client
    if _async_client is None:
        from openai import AsyncOpenAI
        _async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _async_client


def run(state: AntonState) -> AntonState:
    # Scheduling answer always takes priority — it's a step-based wizard.
    # Never mix it with knowledge via synthesis, as that corrupts the flow.
    # Also skip voice reformat: scheduling answers are already concise spoken
    # sentences — the reformatter LLM misinterprets questions like
    # "What's your email?" as prompts to answer, causing hallucinations.
    if state.get("scheduling_answer"):
        return {**state, "final_response": state["scheduling_answer"]}

    if state.get("knowledge_answer"):
        final = state["knowledge_answer"]
        if state.get("channel") == "voice":
            final = _reformat_for_voice(final, _get_client())
        return {**state, "final_response": final}

    # Chitchat fallback — also skip voice reformat (short, already conversational)
    final = _generate_chitchat_response(state)
    return {**state, "final_response": final}


def _reformat_for_voice(text: str, client) -> str:
    """Rewrite answer as natural spoken English for TTS."""
    from backend.orchestrator.prompts import VOICE_REFORMAT_PROMPT
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": VOICE_REFORMAT_PROMPT},
                {"role": "user", "content": text}
            ],
            temperature=0.5,
            max_tokens=200
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ResponseNode] Voice reformat failed: {e}")
        return _strip_markdown(text)


def _synthesize_response(parts: list[str], state: AntonState, client) -> str:
    combined = "\n\n".join(parts)
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are Anton, Rehan's AI representative. Combine these two partial answers into one natural, flowing response. Don't repeat information. Add a smooth transition between topics. Keep it under 150 words."},
                {"role": "user", "content": combined}
            ],
            temperature=0.4,
            max_tokens=200
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ResponseNode] Synthesis failed: {e}")
        return " ".join(parts)


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


# ─── Streaming variants (Vapi Custom LLM) ────────────────────────────────────

async def _stream_reformat_for_voice(text: str) -> AsyncIterator[str]:
    """Stream-rewrite an answer as natural spoken English for TTS."""
    from backend.orchestrator.prompts import VOICE_REFORMAT_PROMPT
    client = _get_async_client()
    try:
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": VOICE_REFORMAT_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0.5,
            max_tokens=200,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        print(f"[ResponseNode] Stream voice reformat failed: {e}")
        # Fall back to a stripped, word-by-word emission of the original
        for word in _strip_markdown(text).split():
            yield word + " "


async def _stream_chitchat_response(state: AntonState) -> AsyncIterator[str]:
    """Stream a chitchat / greeting response."""
    client = _get_async_client()
    try:
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ANTON_SYSTEM_PROMPT},
                {"role": "user", "content": CHITCHAT_PROMPT.format(message=state["user_message"])},
            ],
            temperature=0.7,
            max_tokens=100,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        print(f"[ResponseNode] Stream chitchat failed: {e}")
        yield (
            "Hi! I'm Anton, Rehan's AI representative. "
            "I can tell you about his background, projects, and skills, "
            "or help schedule an interview. What would you like to know?"
        )


async def stream_voice_response(state: AntonState) -> AsyncIterator[str]:
    """
    Async generator that streams the final voice-channel response.

    Mirrors the dispatch in `run()`:
      - scheduling_answer → yield the pre-formatted text as a single chunk
      - knowledge_answer  → stream `_reformat_for_voice` (the LLM hop that
                            matters for perceived latency)
      - chitchat          → stream `_generate_chitchat_response`

    The caller (Vapi Custom LLM endpoint) is responsible for wrapping each
    yielded string in OpenAI SSE format. Does not mutate state.
    """
    if state.get("scheduling_answer"):
        yield state["scheduling_answer"]
        return

    if state.get("knowledge_answer"):
        async for token in _stream_reformat_for_voice(state["knowledge_answer"]):
            yield token
        return

    async for token in _stream_chitchat_response(state):
        yield token


async def _chunk_text(text: str, chunk_size: int = 24) -> AsyncIterator[str]:
    """
    Yield `text` in small character slices. Visual streaming only — the
    final_response has already been computed by graph.ainvoke(); this lets
    the chat SSE client render the answer progressively without an extra
    LLM hop.
    """
    if not text:
        return
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


async def stream_chat_response(state: AntonState) -> AsyncIterator[str]:
    """
    Async generator that streams the final chat-channel response.

    Chat differs from voice in two ways:
      - Markdown formatting is preserved (the UI renders it).
      - No TTS reformat hop (it was already computed by graph.ainvoke and
        lives in `state['final_response']`).

    Mirrors the dispatch in `run()`:
      - scheduling_answer → chunk and yield (preserves the plain-text
                            scheduling wizard sentences)
      - knowledge_answer  → chunk and yield from `final_response`
      - chitchat          → chunk and yield from `final_response`
      - empty             → yield a one-shot greeting

    The caller is responsible for wrapping each yielded string in SSE
    format. Does not mutate state.
    """
    final = (
        state.get("final_response")
        or state.get("scheduling_answer")
        or state.get("knowledge_answer")
    )
    if final:
        async for piece in _chunk_text(final):
            yield piece
        return

    yield (
        "Hi! I'm Anton, Rehan's AI representative. "
        "I can tell you about his background, projects, and skills, "
        "or help schedule an interview. What would you like to know?"
    )
