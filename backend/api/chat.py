"""
Chat API Endpoint

Main entry point for Next.js web interface.

Two routes:
  POST /chat         — Synchronous JSON response (legacy / fallback).
  POST /chat/stream  — Server-Sent Events (OpenAI chat.completion.chunk
                        format). The frontend prefers this; /chat is kept
                        for compatibility and non-streaming clients.
"""

import json
import time
import uuid
from typing import AsyncIterator, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.orchestrator.graph import get_graph
from backend.orchestrator.nodes.response_node import stream_chat_response
from backend.memory.session_store import save_message, save_session_meta

router = APIRouter(prefix="/chat", tags=["chat"])


# ─── Shared request/response models ──────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str = Field(..., description="Message from the recruiter")
    session_id: Optional[str] = Field(
        None, description="Unique session ID to persist history"
    )
    recruiter_name: Optional[str] = Field(
        None, description="Optional name of recruiter"
    )
    recruiter_email: Optional[str] = Field(
        None, description="Optional email of recruiter"
    )
    recruiter_company: Optional[str] = Field(
        None, description="Optional company of recruiter"
    )


class SourceMetadata(BaseModel):
    source: str
    section: Optional[str] = None
    repo_name: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    response: str
    sources: List[SourceMetadata] = []


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _build_initial_state(payload: ChatRequest, session_id: str) -> dict:
    return {
        "session_id": session_id,
        "user_message": payload.message,
        "channel": "chat",
        "intents": [],
        "retrieved_chunks": [],
        "knowledge_answer": None,
        "available_slots": None,
        "booking_result": None,
        "scheduling_answer": None,
        "scheduling_intent": None,
        "conversation_history": [],
        "conversation_summary": None,
        "recruiter_name": payload.recruiter_name,
        "recruiter_email": payload.recruiter_email,
        "recruiter_company": payload.recruiter_company,
        "final_response": None,
        "error": None,
    }


def _dedupe_sources(retrieved_chunks: list) -> List[SourceMetadata]:
    sources: List[SourceMetadata] = []
    seen = set()
    for chunk in retrieved_chunks or []:
        meta = chunk.get("metadata", {}) or {}
        source_type = chunk.get("source", "unknown")
        section = meta.get("section")
        repo = meta.get("repo_name")
        key = (source_type, section, repo)
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            SourceMetadata(
                source=source_type, section=section, repo_name=repo
            )
        )
    return sources


def _save_recruiter_meta(payload: ChatRequest) -> None:
    meta = {}
    if payload.recruiter_name:
        meta["recruiter_name"] = payload.recruiter_name
    if payload.recruiter_email:
        meta["recruiter_email"] = payload.recruiter_email
    if payload.recruiter_company:
        meta["recruiter_company"] = payload.recruiter_company
    if meta:
        save_session_meta(payload.session_id or "", meta)


# ─── /chat — synchronous JSON ───────────────────────────────────────────────


@router.post("", response_model=ChatResponse)
def handle_chat(payload: ChatRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    _save_recruiter_meta(payload)

    state = _build_initial_state(payload, session_id)

    try:
        graph = get_graph()
        output = graph.invoke(state)

        final_resp = (
            output.get("final_response")
            or "I'm having trouble formulating a response right now. "
               "Please try again."
        )

        save_message(session_id, "user", payload.message)
        save_message(session_id, "assistant", final_resp)

        return ChatResponse(
            session_id=session_id,
            response=final_resp,
            sources=_dedupe_sources(output.get("retrieved_chunks", [])),
        )
    except Exception as e:
        print(f"[API Chat] Error processing request: {e}")
        raise HTTPException(
            status_code=500, detail=f"Internal graph error: {str(e)}"
        )


# ─── /chat/stream — Server-Sent Events (OpenAI chunk format) ───────────────


def _sse_chunk(completion_id: str, content: str, first: bool) -> str:
    delta = {"role": "assistant"} if first else {}
    delta["content"] = content
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n"


def _sse_final(completion_id: str) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n"


def _sse_meta(event: str, data: dict) -> str:
    """Emit a named SSE event (not 'data:') for non-token metadata."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/stream")
async def handle_chat_stream(payload: ChatRequest):
    """
    Streaming chat endpoint. Returns an SSE stream of OpenAI-shaped
    chat.completion.chunk objects. Token-level deltas come from
    `stream_chat_response(final_state)`; session_id and sources are
    emitted as named events.
    """
    session_id = payload.session_id or str(uuid.uuid4())
    _save_recruiter_meta(payload)

    state = _build_initial_state(payload, session_id)
    completion_id = f"chatcmpl-{session_id}-{int(time.time() * 1000)}"

    try:
        graph = get_graph()
        final_state = await graph.ainvoke(state)
    except Exception as e:
        print(f"[API Chat Stream] graph.ainvoke failed: {e}")

        async def error_stream() -> AsyncIterator[str]:
            yield _sse_chunk(
                completion_id,
                "I'm sorry, I encountered an error. Please try again.",
                first=True,
            )
            yield _sse_final(completion_id)

        return StreamingResponse(
            error_stream(), media_type="text/event-stream"
        )

    final_text = final_state.get("final_response") or ""

    # Persist this turn to Redis (best-effort, non-blocking on failure).
    try:
        save_message(session_id, "user", payload.message)
        save_message(session_id, "assistant", final_text)
    except Exception as e:
        print(f"[API Chat Stream] Redis save failed (non-fatal): {e}")

    sources = _dedupe_sources(final_state.get("retrieved_chunks", []))

    async def event_stream() -> AsyncIterator[str]:
        first = True
        try:
            async for piece in stream_chat_response(final_state):
                if piece is None:
                    continue
                yield _sse_chunk(completion_id, piece, first=first)
                first = False
        except Exception as e:
            print(f"[API Chat Stream] stream_chat_response failed: {e}")
            if first:
                yield _sse_chunk(
                    completion_id,
                    "I'm sorry, I encountered an error. Please try again.",
                    first=True,
                )

        # Final OpenAI-style stop chunk + DONE sentinel
        yield _sse_final(completion_id)

        # Metadata: session id + sources, as a named SSE event so the
        # frontend can ignore it without polluting the text stream.
        yield _sse_meta(
            "meta",
            {
                "session_id": session_id,
                "sources": [s.model_dump() for s in sources],
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
