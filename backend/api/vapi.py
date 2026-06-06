"""
Vapi Voice API — Custom LLM endpoint + Server URL webhook.

Two routes:
  POST /vapi/chat     — Custom LLM endpoint.
                         Receives an OpenAI-compatible messages array.
                         Returns an SSE stream of OpenAI chat.completion.chunk
                         objects. The LangGraph orchestrator is invoked once
                         synchronously; the final LLM hop is then re-issued
                         with stream=True so the caller hears Anton within
                         one LLM round-trip.
  POST /vapi/webhook  — Lifecycle event handler (status-update,
                         end-of-call-report, function-call, hang, ...).
"""

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import StreamingResponse
from typing import AsyncIterator, List, Dict
import hmac
import hashlib
import json
import logging
import time

from backend.config import settings
from backend.orchestrator.graph import get_graph
from backend.orchestrator.nodes.response_node import stream_voice_response
from backend.memory.session_store import save_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["vapi"])


# ─── /vapi/chat — Custom LLM endpoint ─────────────────────────────────────────

def _content_to_text(content) -> str:
    """Normalize a message's content (string or list-of-parts) to a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return " ".join(p for p in parts if p)
    return ""


def _extract_last_user_message(messages: List[Dict]) -> str:
    """Get the content of the last user-role message."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            text = _content_to_text(msg.get("content", ""))
            if text:
                return text
    return ""


def _messages_to_history(messages: List[Dict]) -> List[Dict[str, str]]:
    """
    Convert prior messages into LangGraph conversation_history format.

    Drops the system message and the trailing user message (which becomes
    state['user_message']). Keeps prior user/assistant turns so follow-up
    questions resolve naturally.
    """
    if not messages:
        return []

    # Find the index of the last user message; that's the new turn.
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_idx = i
            break

    history = []
    for i, msg in enumerate(messages):
        if i == last_user_idx:
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _content_to_text(msg.get("content", ""))
        history.append({"role": role, "content": text})
    return history


def _sse_chunk(completion_id: str, content: str, first: bool, finish_reason=None) -> str:
    delta = {}
    if first:
        delta["role"] = "assistant"
    delta["content"] = content
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
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


@router.post("/chat")
async def vapi_custom_llm(request: Request):
    """
    Vapi Custom LLM endpoint.

    Accepts an OpenAI-compatible request body:
        { "model": ..., "messages": [...], "stream": true, "call": { "id": ... } }

    Returns an SSE stream of OpenAI chat.completion.chunk objects.
    """
    try:
        body = await request.json()
    except Exception as e:
        logger.warning(f"[Vapi] /vapi/chat invalid JSON: {e}")
        return await _sse_error_response(
            "vapi-chat-badjson",
            "Sorry, I couldn't process that. Could you repeat that?",
        )

    messages = body.get("messages") or []
    call = body.get("call") or {}
    call_id = call.get("id") or "unknown"
    completion_id = f"chatcmpl-{call_id}-{int(time.time() * 1000)}"

    last_user = _extract_last_user_message(messages)
    if not last_user:
        # No user message in the transcript — emit a polite greeting and stop.
        async def greeting() -> AsyncIterator[str]:
            yield _sse_chunk(
                completion_id,
                "Hi! I'm Anton, Rehan's AI representative. How can I help you today?",
                first=True,
            )
            yield _sse_final(completion_id)
        return StreamingResponse(greeting(), media_type="text/event-stream")

    history = _messages_to_history(messages)
    session_id = f"voice_{call_id}"

    initial_state = {
        "session_id": session_id,
        "user_message": last_user,
        "channel": "voice",
        "intents": [],
        "retrieved_chunks": [],
        "knowledge_answer": None,
        "scheduling_answer": None,
        "available_slots": None,
        "booking_result": None,
        "scheduling_intent": None,
        "conversation_history": history,
        "conversation_summary": None,
        "recruiter_name": None,
        "recruiter_email": None,
        "recruiter_company": None,
        "final_response": None,
        "error": None,
    }

    # Run the orchestrator graph synchronously (memory → router →
    # knowledge/scheduling → response). The response node's LLM call is
    # the bottleneck for perceived latency, so we re-issue it with
    # stream=True via stream_voice_response() below.
    try:
        graph = get_graph()
        final_state = await graph.ainvoke(initial_state)
    except Exception as e:
        logger.exception(f"[Vapi] graph.ainvoke failed: {e}")
        return await _sse_error_response(
            completion_id,
            "I'm sorry, I encountered an error. Could you repeat that?",
        )

    # Persist this turn to Redis (session history).
    try:
        final_text = final_state.get("final_response") or ""
        if final_text:
            save_message(session_id, "user", last_user)
            save_message(session_id, "assistant", final_text)
    except Exception as e:
        logger.warning(f"[Vapi] Redis save failed (non-fatal): {e}")

    async def event_stream() -> AsyncIterator[str]:
        first = True
        emitted_any = False
        try:
            async for token in stream_voice_response(final_state):
                if not token:
                    continue
                yield _sse_chunk(completion_id, token, first=first)
                first = False
                emitted_any = True
        except Exception as e:
            logger.exception(f"[Vapi] stream_voice_response failed: {e}")
            if not emitted_any:
                yield _sse_chunk(
                    completion_id,
                    "I'm sorry, I encountered an error. Could you repeat that?",
                    first=first,
                    finish_reason="stop",
                )
                yield "data: [DONE]\n\n"
                return

        yield _sse_final(completion_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _sse_error_response(completion_id: str, message: str) -> StreamingResponse:
    """Build a one-shot error SSE response. Vapi handles 5xx poorly."""
    async def err() -> AsyncIterator[str]:
        yield _sse_chunk(completion_id, message, first=True, finish_reason="stop")
        yield "data: [DONE]\n\n"
    return StreamingResponse(err(), media_type="text/event-stream")


# ─── /vapi/webhook — Server URL lifecycle events ──────────────────────────────


def _verify_vapi_signature(raw: bytes, signature: str) -> tuple[bool, str]:
    """
    Verify a Vapi webhook request.

    Vapi sends the configured serverUrlSecret verbatim in the
    X-Vapi-Secret header (not as an HMAC of the body). Verification is a
    constant-time equality check against the secret we have in config.
    The `raw` argument is unused but kept for API symmetry / future HMAC
    fallback.
    """
    del raw  # currently unused — kept for future HMAC fallback
    configured = settings.VAPI_SERVER_SECRET or ""
    if not configured:
        return False, "no-secret-configured"
    if not signature:
        return False, "empty-signature"
    if hmac.compare_digest(signature, configured):
        return True, "secret-match"
    return False, (
        f"received={signature[:8]}... "
        f"expected={configured[:8]}..."
    )


@router.post("/webhook")
async def vapi_webhook(
    request: Request,
    x_vapi_signature: str = Header(default=""),
    x_vapi_secret: str = Header(default=""),
):
    raw = await request.body()

    sig = x_vapi_signature or x_vapi_secret
    if not settings.VAPI_SERVER_SECRET:
        logger.warning(
            "[Vapi] webhook received with no VAPI_SERVER_SECRET configured; "
            "skipping verification"
        )
    else:
        ok, debug = _verify_vapi_signature(raw, sig)
        if not ok:
            logger.warning(
                f"[Vapi] signature mismatch ({debug}): "
                f"x_vapi_signature_len={len(x_vapi_signature)} "
                f"x_vapi_secret_len={len(x_vapi_secret)} "
                f"body_len={len(raw)}"
            )
            raise HTTPException(status_code=401, detail="Invalid Vapi signature")

    try:
        body = json.loads((raw or b"{}").decode("utf-8"))
    except Exception:
        logger.warning("[Vapi] /vapi/webhook received non-JSON body")
        return {"status": "ok"}

    message = body.get("message") or {}
    event_type = message.get("type")
    call = message.get("call") or {}
    call_id = call.get("id", "unknown")

    logger.info(f"[Vapi webhook] type={event_type} call_id={call_id}")

    if event_type == "status-update":
        status = message.get("status")
        logger.info(f"[Vapi] Call {call_id} status: {status}")

    elif event_type == "end-of-call-report":
        transcript = message.get("transcript", "")
        recording_url = message.get("recordingUrl", "")
        duration = message.get("durationSeconds")
        logger.info(
            f"[Vapi] Call {call_id} ended. "
            f"transcript_len={len(transcript) if isinstance(transcript, str) else 'n/a'} "
            f"duration={duration}s recording={recording_url}"
        )
        # Per PRD §12 — no DB writes; logging only.

    elif event_type == "function-call":
        fn = message.get("functionCall") or {}
        name = fn.get("name")
        params = fn.get("parameters", {})
        logger.info(f"[Vapi] function-call: {name} params={params}")
        # No Vapi tools registered in this migration — log and ack.
        return {"result": "ok"}

    elif event_type == "hang":
        logger.info(f"[Vapi] Call {call_id} hung up.")

    elif event_type == "assistant-request":
        # Dynamic-assistant mode. We don't use it (assistant is static),
        # but ack cleanly.
        return {
            "assistantId": settings.VAPI_ASSISTANT_ID,
        }

    return {"status": "ok"}
