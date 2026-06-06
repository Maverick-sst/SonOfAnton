"""
Router Node — Two-stage Hybrid Router

Stage 1: Fast keyword/regex classification
Stage 2: LLM fallback (gpt-4o-mini) when confidence < 0.7

Returns multi-intent list: ["knowledge", "scheduling", "chitchat"]
"""

import json
import re
import time
from backend.orchestrator.state import AntonState
from backend.orchestrator.prompts import ROUTER_PROMPT
from backend.config import settings
from openai import OpenAI

_client = None

# A scheduling wizard state older than this is considered stale — the user
# almost certainly closed the tab and came back, not "interrupted" the
# flow mid-step. The router will ignore stale state and let the message
# be classified fresh.
SCHEDULING_STALE_SECONDS = 30 * 60


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
    "what technologies", "what languages", "qualification",
    # Natural language questions about Rehan's personal/academic background
    "school", "college", "university", "studied", "study", "where did he",
    "where does he", "which school", "which university", "which college",
    "where is he", "where was he", "located", "from", "hometown",
    "work", "works", "working", "knows", "know how", "language",
    "framework", "technology", "technologies", "tool", "tools",
    "rehan", "his", "he is", "he has", "about him"
]


# Compiled word-boundary pattern for KNOWLEDGE_KEYWORDS.
# We use \b so that substring matches inside emails / urls / filenames do NOT
# trigger a knowledge classification. Example: "rehan" must NOT match the
# substring inside "mdrehan05.2006@gmail.com" — otherwise the email turn
# inside a scheduling flow gets wrongly classified as a knowledge question
# and the orchestrator never reaches scheduling_node.
_KNOWLEDGE_KW_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in KNOWLEDGE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# When the user is mid-scheduling, falling through to the keyword
# classifier is too eager. The keyword list includes generic verbs like
# "works" / "knows" / "working" / "is" that fire on completely ordinary
# scheduling-continuation phrases such as "3 works for me", "1 pm works",
# "yes that works", "sounds good". A wizard turn that just answered a
# question should not get yanked into the knowledge layer.
#
# We only allow the fall-through to knowledge when the message carries a
# STRONG knowledge signal: a question mark, a leading wh-/tell-/explain-
# word, or an explicit "tell me about" / "describe" / "explain" phrase.
# Short affirmations ("yes", "1", "3 works for me") are correctly kept on
# the scheduling path.
_STRONG_KNOWLEDGE_RE = re.compile(
    r"(?:"
    r"\?|"
    r"^\s*(what|who|where|when|why|how|which|whose|tell|describe|explain)\b|"
    r"\b(tell me about|tell me more|describe|explain)\b"
    r")",
    re.IGNORECASE,
)


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

                    # Stale-wizard guard. The session_id is persisted in
                    # the browser's localStorage, so if the user closed the
                    # tab mid-flow and came back later, the wizard state
                    # is still in Redis. Treating it as "active" would make
                    # the first "hi" of the new visit get auto-prompted
                    # for the next wizard step. Anything older than
                    # SCHEDULING_STALE_SECONDS is treated as no state at
                    # all and deleted so subsequent turns are also fresh.
                    updated_at = sched_state.get("_updated_at")
                    is_stale = (
                        updated_at is None
                        or (time.time() - float(updated_at)) > SCHEDULING_STALE_SECONDS
                    )
                    if is_stale:
                        try:
                            r.delete(f"session:{session_id}:scheduling")
                        except Exception:
                            pass
                    else:
                        is_active = False
                        if step and step not in ("INIT", "DONE"):
                            is_active = True
                        elif reschedule_step and reschedule_step != "DONE":
                            is_active = True
                        elif cancel_step and cancel_step != "DONE":
                            is_active = True

                        if is_active:
                            # Word-boundary match prevents the keyword
                            # "rehan" from matching inside the user's
                            # email ("mdrehan05.2006@…") or a URL, which
                            # would otherwise yank the conversation out
                            # of the scheduling flow mid-booking.
                            #
                            # The strong-knowledge gate prevents generic
                            # keywords like "works" / "knows" in ordinary
                            # scheduling-continuation phrases (e.g. "3
                            # works for me", "1 pm works") from
                            # redirecting the message to knowledge.
                            if not _STRONG_KNOWLEDGE_RE.search(message):
                                return {**state, "intents": ["scheduling"]}
            except Exception as e:
                print(f"[Router] Active scheduling check failed: {e}")

    # Stage 1: keyword rules
    intents = _keyword_classify(message)
    confidence = 0.9 if len(intents) == 1 and "chitchat" not in intents else 0.0

    # Stage 2: LLM fallback when confidence is low.
    # NOTE: We only call LLM if NOT already in an active scheduling session.
    # The active-session override above already returns early for scheduling turns.
    # LLM is the safety net for natural-language knowledge questions (e.g. "which school did he go to").
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
        return ["chitchat"]   # Fast path — no LLM needed
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
