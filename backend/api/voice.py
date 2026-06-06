"""
Voice API Endpoint — Retell AI Webhook Handler

Handles incoming calls and live transcription events from Retell AI.
Optimized for voice latency (<2s).
"""

from fastapi import APIRouter, Request, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import List, Dict, Any
from backend.orchestrator.graph import get_graph
from backend.memory.session_store import save_message
from backend.config import settings
import hmac
import hashlib
import json

router = APIRouter(prefix="/voice", tags=["voice"])

class RetellUtterance(BaseModel):
    role: str       # "user" | "agent"
    content: str

class RetellRequest(BaseModel):
    call_id: str
    agent_id: str
    transcript: List[RetellUtterance]
    interaction_type: str     # "response_required" | "reminder_required"

def _transcript_to_history(transcript: List[RetellUtterance]) -> List[Dict[str, str]]:
    return [
        {"role": "user" if t.role == "user" else "assistant", "content": t.content}
        for t in transcript
    ]

async def _verify_retell_signature(request: Request):
    """Verify request signature if RETELL_SECRET_KEY or RETELL_API_KEY is configured."""
    key = settings.RETELL_SECRET_KEY or settings.RETELL_API_KEY
    if not key:
        return
        
    sig = request.headers.get("x-retell-signature", "")
    if not sig:
        raise HTTPException(status_code=403, detail="Missing x-retell-signature header")
        
    body_bytes = await request.body()
    body_str = body_bytes.decode('utf-8')
    
    # pyrefly: ignore [missing-import]
    from retell.lib.webhook_auth import verify as verify_retell
    
    try:
        is_valid = verify_retell(body_str, key, sig)
        if not is_valid:
            raise HTTPException(status_code=403, detail="Invalid Retell signature")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Signature verification failed: {e}")

@router.post("/webhook")
async def voice_webhook(request: Request):
    await _verify_retell_signature(request)
    
    body = await request.json()
    
    # Handle Retell event notifications (like call_started, call_ended) gracefully
    if "event" in body:
        event_type = body.get("event")
        print(f"[Voice Webhook] Ignored Retell event notification: {event_type}")
        return {"status": "ignored", "event": event_type}
        
    req = RetellRequest(**body)
    
    # Only respond to user speech input
    if req.interaction_type != "response_required":
        return {"response": ""}
        
    # Extract last user message
    user_messages = [t for t in req.transcript if t.role == "user"]
    if not user_messages:
        return {"response": "Hello! I'm Son of Anton, Rehan's AI representative. How can I help you today?"}
        
    last_user_message = user_messages[-1].content
    session_id = f"voice_{req.call_id}"
    
    # Build initial state
    graph = get_graph()
    initial_state = {
        "session_id": session_id,
        "user_message": last_user_message,
        "channel": "voice",
        "intents": [],
        "retrieved_chunks": [],
        "knowledge_answer": None,
        "scheduling_answer": None,
        "available_slots": None,
        "booking_result": None,
        "scheduling_intent": None,
        "conversation_history": _transcript_to_history(req.transcript[:-1]),
        "conversation_summary": None,
        "recruiter_name": None,
        "recruiter_email": None,
        "recruiter_company": None,
        "final_response": None,
        "error": None
    }
    
    try:
        # Use ainvoke for async execution
        result = await graph.ainvoke(initial_state)
        response = result.get("final_response") or "I'm sorry, could you repeat that?"
        
        # Save to Redis history
        save_message(session_id, "user", last_user_message)
        save_message(session_id, "assistant", response)
        
        return {"response": response}
    except Exception as e:
        print(f"[Voice Webhook] Error: {e}")
        return {"response": "I'm sorry, I encountered an error. Could you repeat that?"}


@router.websocket("/webhook/{call_id}")
async def voice_websocket(websocket: WebSocket, call_id: str):
    await websocket.accept()
    print(f"[Voice WebSocket] Accepted connection for call: {call_id}")
    
    # Send initial greeting (Retell custom LLM protocol expects greeting response_id = 0)
    greeting = {
        "response_id": 0,
        "content": "Hello! I'm Son of Anton, Rehan's AI representative. How can I help you today?",
        "content_complete": True,
        "end_call": False
    }
    await websocket.send_text(json.dumps(greeting))
    
    try:
        while True:
            data = await websocket.receive_text()
            print(f"[Voice WebSocket] Received raw message: {data}")
            msg = json.loads(data)
            
            interaction_type = msg.get("interaction_type")
            response_id = msg.get("response_id", 0)
            
            print(f"[Voice WebSocket] Received interaction: {interaction_type}, response_id: {response_id}")
            
            if interaction_type == "response_required":
                transcript_raw = msg.get("transcript", [])
                
                transcript = []
                for t in transcript_raw:
                    role = t.get("role")
                    content = t.get("content")
                    if role and content:
                        transcript.append(RetellUtterance(role=role, content=content))
                
                user_messages = [t for t in transcript if t.role == "user"]
                if not user_messages:
                    await websocket.send_text(json.dumps({
                        "response_id": response_id,
                        "content": "Hello! I'm Son of Anton. How can I help you?",
                        "content_complete": True,
                        "end_call": False
                    }))
                    continue
                    
                last_user_message = user_messages[-1].content
                session_id = f"voice_{call_id}"
                
                graph = get_graph()
                initial_state = {
                    "session_id": session_id,
                    "user_message": last_user_message,
                    "channel": "voice",
                    "intents": [],
                    "retrieved_chunks": [],
                    "knowledge_answer": None,
                    "scheduling_answer": None,
                    "available_slots": None,
                    "booking_result": None,
                    "scheduling_intent": None,
                    "conversation_history": _transcript_to_history(transcript[:-1]),
                    "conversation_summary": None,
                    "recruiter_name": None,
                    "recruiter_email": None,
                    "recruiter_company": None,
                    "final_response": None,
                    "error": None
                }
                
                try:
                    import time
                    start_time = time.time()
                    result = await graph.ainvoke(initial_state)
                    latency = time.time() - start_time
                    print(f"[Voice WebSocket] Graph execution for response_id {response_id} took: {latency:.2f}s")
                    response = result.get("final_response") or "I'm sorry, could you repeat that?"
                    
                    save_message(session_id, "user", last_user_message)
                    save_message(session_id, "assistant", response)
                    
                    await websocket.send_text(json.dumps({
                        "response_id": response_id,
                        "content": response,
                        "content_complete": True,
                        "end_call": False
                    }))
                    print(f"[Voice WebSocket] Sent response for response_id {response_id}: {response}")
                except Exception as e:
                    print(f"[Voice WebSocket] Graph Error: {e}")
                    await websocket.send_text(json.dumps({
                        "response_id": response_id,
                        "content": "I'm sorry, I encountered an error. Could you repeat that?",
                        "content_complete": True,
                        "end_call": False
                    }))
                    
            elif interaction_type == "ping":
                await websocket.send_text(json.dumps({
                    "response_type": "pong"
                }))
                
    except WebSocketDisconnect:
        print(f"[Voice WebSocket] Connection disconnected for call: {call_id}")
    except Exception as e:
        print(f"[Voice WebSocket] Error: {e}")
