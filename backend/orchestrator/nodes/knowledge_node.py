"""
Knowledge Node — RAG Retrieval + Grounded Answer Generation

Flow: Cache → Vector Store → (Live GitHub Fallback) → Build Context → LLM → Cache Result
"""

from backend.orchestrator.state import AntonState
from backend.knowledge.retriever import retrieve, retrieve_with_github_fallback
from backend.knowledge.cache import get_cached_answer, set_cached_answer
from backend.orchestrator.prompts import KNOWLEDGE_ANSWER_PROMPT
from backend.config import settings
from openai import OpenAI
import hashlib
import re

_client = None

# These patterns identify genuine follow-up queries that need prior context.
# Intentionally narrow — only match clear references to a prior answer.
CONTEXT_DEPENDENT_PATTERNS = [
    r'\b(tell me more about (that|it|this))\b',
    r'\b(go back|earlier you (said|mentioned))\b',
    r'\b(what else (did you|can you) (say|tell)|and also that)\b',
    r'^(why (did|is|was|does) (he|it|that)|how come (he|that))\b',
]


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _is_context_dependent(question: str) -> bool:
    q = question.lower().strip()
    for pattern in CONTEXT_DEPENDENT_PATTERNS:
        if re.search(pattern, q):
            return True
    return False


# Phrases that signal the user wants the freshest data we have, not
# whatever happens to be in the cache. The live GitHub fallback is
# cheap enough to invoke on a soft match here.
_LATEST_WORK_SIGNALS = re.compile(
    r"\b(most recent|latest|newest|recently|just (built|shipped|released)|"
    r"what.*working on|what.*been up to|right now|currently)\b",
    re.IGNORECASE,
)


def _should_fallback_to_live(question: str, chunks: list[dict]) -> bool:
    """
    Decide whether to escalate from cached retrieval to a live GitHub
    API call. Returns True if:

      1. The question matches a "latest work" signal ("most recent
         project", "what is he working on", ...). For these queries
         freshness matters more than the cached answer.
      2. The cached chunks exist but NONE of them are github-sourced
         AND the question is project-related. In that case the cached
         resume/projects chunk is the only signal we have, and it
         may be stale or boilerplate.

    We deliberately do NOT escalate for skills / education / personal
    questions — those don't change between ingests and the cached
    answer is good enough.
    """
    q = question.lower()
    if _LATEST_WORK_SIGNALS.search(q):
        return True
    # Project-related question with no github evidence in the chunks
    # is also a fallback signal — the cached readme may be stale.
    project_signal = any(
        kw in q
        for kw in ("project", "repo", "github", "built", "shipped", "app", "platform")
    )
    if project_signal and not any(c.get("source") == "github" for c in chunks):
        return True
    return False


def run(state: AntonState) -> AntonState:
    """Retrieve knowledge and generate grounded answer."""
    question = state["user_message"]
    channel = state.get("channel", "chat")

    # Check cache first if not context dependent
    is_dependent = _is_context_dependent(question)
    cache_key = None
    if not is_dependent:
        cache_key = hashlib.md5(f"{question.lower().strip()}:{channel}".encode()).hexdigest()
        cached = get_cached_answer(cache_key)
        if cached:
            return {**state, "knowledge_answer": cached, "retrieved_chunks": []}

    # First-pass retrieval from the cached vector store.
    chunks = retrieve(question, n_results=8, top_k=5)

    # If the cached store gave us nothing useful, OR the question is
    # about latest work / a specific project that the cached data
    # doesn't actually describe, fall through to a live GitHub fetch.
    # This is the "last resort" per master_doc §11.
    if not chunks or _should_fallback_to_live(question, chunks):
        try:
            live_chunks = retrieve_with_github_fallback(question)
            if live_chunks and len(live_chunks) > len(chunks):
                chunks = live_chunks
        except Exception as e:
            # Live fallback is best-effort. A failed API call must not
            # break the knowledge flow.
            print(f"[Knowledge] Live GitHub fallback failed (non-fatal): {e}")

    if not chunks:
        return {
            **state,
            "retrieved_chunks": [],
            "knowledge_answer": (
                "I don't have specific enough information to answer that accurately. "
                "Rehan would be better placed to give you the details directly."
            )
        }

    # Build context string from chunks
    context = _build_context(chunks)

    # Generate grounded answer using the appropriate model for the channel
    model = settings.OPENAI_VOICE_MODEL if state.get("channel") == "voice" else settings.OPENAI_CHAT_MODEL
    answer = _generate_answer(
        question, context,
        state.get("conversation_history", []),
        state.get("conversation_summary"),
        model
    )

    # Cache the answer (24h TTL) for non-context-dependent queries
    if cache_key:
        set_cached_answer(cache_key, answer, ttl=86400)

    return {**state, "retrieved_chunks": chunks, "knowledge_answer": answer}


def _build_context(chunks: list[dict]) -> str:
    """Build labeled context string from retrieved chunks."""
    parts = []
    for chunk in chunks:
        source_label = f"[{chunk['source'].upper()}]"
        if chunk["source"] == "github":
            repo_name = chunk.get("metadata", {}).get("repo_name", "unknown")
            source_label = f"[GITHUB: {repo_name}]"
        elif chunk["source"] == "linkedin":
            source_label = "[LINKEDIN]"
        parts.append(f"{source_label}\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def _generate_answer(
    question: str,
    context: str,
    history: list,
    summary: str | None,
    model: str
) -> str:
    """Generate grounded answer using LLM with context + history."""
    c = _get_client()

    messages = [
        {"role": "system", "content": KNOWLEDGE_ANSWER_PROMPT},
    ]

    # Add summary if available
    if summary:
        messages.append({
            "role": "system",
            "content": f"Conversation summary so far: {summary}"
        })

    # Add last 6 turns of history for follow-up context
    for turn in history[-6:]:
        messages.append(turn)

    messages.append({
        "role": "user",
        "content": f"Context:\n{context}\n\nQuestion: {question}"
    })

    resp = c.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,  # was 0.3
        max_tokens=400
    )
    return resp.choices[0].message.content
