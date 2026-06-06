"""
Router Node — Two-stage Hybrid Router

Stage 1: Fast keyword/regex classification
Stage 2: LLM fallback (gpt-4o-mini) when confidence < 0.7

Returns multi-intent list: ["knowledge", "scheduling", "chitchat"]
"""

import json
from backend.orchestrator.state import AntonState
from backend.orchestrator.prompts import ROUTER_PROMPT
from backend.config import settings
from openai import OpenAI

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


# ─── Keyword Lists ───────────────────────────────────────────────────────────

SCHEDULING_KEYWORDS = [
    "schedule", "book", "interview", "meeting", "calendar",
    "available", "availability", "reschedule", "cancel", "slot",
    "time", "date", "next week", "tomorrow", "monday", "tuesday",
    "wednesday", "thursday", "friday", "when can", "free time",
    "set up a call", "arrange", "change the time", "move the interview",
    "don't need the interview", "withdraw", "postpone"
]

KNOWLEDGE_KEYWORDS = [
    "tell me about", "what is", "what are", "explain", "describe",
    "who is", "background", "experience", "project", "skill",
    "education", "degree", "worked on", "built", "tech stack",
    "what does", "how does", "portfolio", "resume", "github",
    "morph", "anton", "stratum", "odysseus", "terax", "devforge",
    "what technologies", "what languages", "qualification"
]


def run(state: AntonState) -> AntonState:
    """Classify user intent using hybrid routing."""
    message = state["user_message"].lower()

    # Active scheduling session override:
    # If the user is in the middle of a scheduling flow, we force routing to scheduling,
    # unless they explicitly ask a knowledge question (containing KNOWLEDGE_KEYWORDS).
    session_id = state.get("session_id")
    if session_id:
        from backend.memory.session_store import get_redis_client
        r = get_redis_client()
        if r:
            try:
                raw = r.get(f"session:{session_id}:scheduling")
                if raw:
                    sched_state = json.loads(raw)
                    step = sched_state.get("step")
                    reschedule_step = sched_state.get("reschedule_step")
                    cancel_step = sched_state.get("cancel_step")
                    
                    is_active = False
                    if step and step not in ("INIT", "DONE"):
                        is_active = True
                    elif reschedule_step and reschedule_step != "DONE":
                        is_active = True
                    elif cancel_step and cancel_step != "DONE":
                        is_active = True
                        
                    if is_active:
                        if not any(kw in message for kw in KNOWLEDGE_KEYWORDS):
                            return {**state, "intents": ["scheduling"]}
            except Exception as e:
                print(f"[Router] Active scheduling check failed: {e}")

    # Stage 1: keyword rules
    intents = _keyword_classify(message)
    confidence = 0.9 if intents and "chitchat" not in intents else 0.0

    # Stage 2: LLM fallback when low confidence
    if confidence < 0.7:
        intents, confidence = _llm_classify(state["user_message"])

    return {**state, "intents": intents}


def _keyword_classify(message: str) -> list[str]:
    """Fast keyword-based intent classification."""
    intents = []
    if any(kw in message for kw in SCHEDULING_KEYWORDS):
        intents.append("scheduling")
    if any(kw in message for kw in KNOWLEDGE_KEYWORDS):
        intents.append("knowledge")
    if not intents:
        intents.append("chitchat")
    return intents


def _llm_classify(message: str) -> tuple[list[str], float]:
    """LLM-based intent classification (fallback for ambiguous queries)."""
    try:
        c = _get_client()
        resp = c.chat.completions.create(
            model="gpt-4o-mini",  # Use mini for routing — cost optimization
            messages=[{
                "role": "user",
                "content": ROUTER_PROMPT.format(message=message)
            }],
            temperature=0,
            max_tokens=60
        )
        data = json.loads(resp.choices[0].message.content)
        return data["intents"], data.get("confidence", 0.8)
    except Exception as e:
        print(f"[Router] LLM classify error: {e}")
        return ["knowledge"], 0.5  # Safe fallback — knowledge is always useful
