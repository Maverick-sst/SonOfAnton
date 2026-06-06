"""
AntonState — LangGraph State Definition

The single state object that flows through all graph nodes.
"""

from typing import TypedDict, Optional, List


class AntonState(TypedDict):
    # ─── Input ────────────────────────────────────────────────────────────────
    session_id: str
    user_message: str
    channel: str               # "voice" | "chat"

    # ─── Router output ────────────────────────────────────────────────────────
    intents: List[str]         # ["knowledge", "scheduling"] — multi-intent supported

    # ─── Knowledge layer output ───────────────────────────────────────────────
    retrieved_chunks: List[dict]   # [{"text": str, "source": str, "score": float}]
    knowledge_answer: Optional[str]

    # ─── Scheduling layer output ──────────────────────────────────────────────
    available_slots: Optional[List[dict]]
    booking_result: Optional[dict]
    scheduling_answer: Optional[str]
    scheduling_intent: Optional[str]  # "book" | "reschedule" | "cancel" | None

    # ─── Memory ──────────────────────────────────────────────────────────────
    conversation_history: List[dict]   # [{"role": str, "content": str}]
    conversation_summary: Optional[str]

    # ─── Recruiter info (captured during scheduling) ─────────────────────────
    recruiter_name: Optional[str]
    recruiter_email: Optional[str]
    recruiter_company: Optional[str]

    # ─── Final ───────────────────────────────────────────────────────────────
    final_response: Optional[str]
    error: Optional[str]
