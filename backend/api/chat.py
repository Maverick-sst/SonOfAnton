"""
Chat API Endpoint

Main entry point for Next.js web interface.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from backend.orchestrator.graph import get_graph
from backend.memory.session_store import save_message, save_session_meta
import uuid

router = APIRouter(prefix="/chat", tags=["chat"])

class ChatRequest(BaseModel):
    message: str = Field(..., description="Message from the recruiter")
    session_id: Optional[str] = Field(None, description="Unique session ID to persist history")
    recruiter_name: Optional[str] = Field(None, description="Optional name of recruiter")
    recruiter_email: Optional[str] = Field(None, description="Optional email of recruiter")
    recruiter_company: Optional[str] = Field(None, description="Optional company of recruiter")

class SourceMetadata(BaseModel):
    source: str
    section: Optional[str] = None
    repo_name: Optional[str] = None

class ChatResponse(BaseModel):
    session_id: str
    response: str
    sources: List[SourceMetadata] = []

@router.post("", response_model=ChatResponse)
def handle_chat(payload: ChatRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    
    # Store initial recruiter info in session metadata if provided
    meta = {}
    if payload.recruiter_name:
        meta["recruiter_name"] = payload.recruiter_name
    if payload.recruiter_email:
        meta["recruiter_email"] = payload.recruiter_email
    if payload.recruiter_company:
        meta["recruiter_company"] = payload.recruiter_company
    if meta:
        save_session_meta(session_id, meta)

    # Initial state
    state = {
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
        "error": None
    }

    try:
        graph = get_graph()
        output = graph.invoke(state)
        
        final_resp = output.get("final_response") or "I'm having trouble formulating a response right now. Please try again."
        
        # Save this turn to session history in Redis
        save_message(session_id, "user", payload.message)
        save_message(session_id, "assistant", final_resp)

        # Parse sources
        sources = []
        seen_sources = set()
        for chunk in output.get("retrieved_chunks", []):
            meta = chunk.get("metadata", {})
            source_type = chunk.get("source", "unknown")
            section = meta.get("section")
            repo = meta.get("repo_name")
            
            # De-duplicate sources list for UI clarity
            source_key = (source_type, section, repo)
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                sources.append(SourceMetadata(
                    source=source_type,
                    section=section,
                    repo_name=repo
                ))

        return ChatResponse(
            session_id=session_id,
            response=final_resp,
            sources=sources
        )

    except Exception as e:
        print(f"[API Chat] Error processing request: {e}")
        raise HTTPException(status_code=500, detail=f"Internal graph error: {str(e)}")
