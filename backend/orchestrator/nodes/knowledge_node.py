"""
Knowledge Node — RAG Retrieval + Grounded Answer Generation

Flow: Cache → Vector Store → Build Context → LLM → Cache Result
"""

from backend.orchestrator.state import AntonState
from backend.knowledge.retriever import retrieve
from backend.knowledge.cache import get_cached_answer, set_cached_answer
from backend.orchestrator.prompts import KNOWLEDGE_ANSWER_PROMPT
from backend.config import settings
from openai import OpenAI
import hashlib

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def run(state: AntonState) -> AntonState:
    """Retrieve knowledge and generate grounded answer."""
    question = state["user_message"]

    # Check cache first
    cache_key = hashlib.md5(question.lower().strip().encode()).hexdigest()
    cached = get_cached_answer(cache_key)
    if cached:
        return {**state, "knowledge_answer": cached, "retrieved_chunks": []}

    # Retrieve from vector store
    chunks = retrieve(question, n_results=8, top_k=5)

    if not chunks:
        return {
            **state,
            "retrieved_chunks": [],
            "knowledge_answer": (
                "I don't have enough information to answer that accurately. "
                "Rehan would be better placed to answer this directly."
            )
        }

    # Build context string from chunks
    context = _build_context(chunks)

    # Generate grounded answer
    # Use appropriate model based on channel
    model = settings.OPENAI_VOICE_MODEL if state.get("channel") == "voice" else settings.OPENAI_CHAT_MODEL
    answer = _generate_answer(
        question, context,
        state.get("conversation_history", []),
        state.get("conversation_summary"),
        model
    )

    # Cache the answer (24h TTL)
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
        temperature=0.3,  # Low temp for factual answers
        max_tokens=400
    )
    return resp.choices[0].message.content
