"""
Retriever with Domain Trust Hierarchy

The most critical file in the Knowledge Layer.
Implements trust-weighted reranking per the Master Architecture Document:

| Domain           | Priority Order                    |
|------------------|-----------------------------------|
| Personal         | Resume > LinkedIn > GitHub        |
| Education        | Resume + LinkedIn (equal weight)  |
| Experience       | Resume + LinkedIn (equal weight)  |
| Projects         | GitHub > Resume > LinkedIn        |
| Latest work      | GitHub only                       |
"""

from backend.knowledge.vector_store import get_chroma_collection
from backend.knowledge.embeddings import get_embedder
from backend.knowledge.cache import get_cached_answer, set_cached_answer
from backend.config import settings
import hashlib


# ─── Domain Trust Hierarchy ───────────────────────────────────────────────────
# Format: TRUST_WEIGHTS[domain][source] = multiplier
# Applied to similarity score AFTER retrieval.
# 1.2+ = boost, 1.0 = neutral, <1.0 = penalize
TRUST_WEIGHTS = {
    "personal": {
        "resume": 1.3,
        "linkedin": 1.1,
        "github": 0.8,
    },
    "education": {
        "resume": 1.2,
        "linkedin": 1.2,
        "github": 0.6,
    },
    "experience": {
        "resume": 1.2,
        "linkedin": 1.2,
        "github": 0.7,
    },
    "projects": {
        "resume": 1.0,
        "linkedin": 0.8,
        "github": 1.4,      # GitHub is primary for projects
    },
    "latest_work": {
        "resume": 0.5,      # Resume is stale for latest work
        "linkedin": 0.6,
        "github": 1.5,      # GitHub commits/READMEs are the only reliable source
    },
}

# Default weights when domain is unknown
DEFAULT_TRUST_WEIGHTS = {
    "resume": 1.1,
    "linkedin": 1.0,
    "github": 1.0,
}

# ─── Domain Classifier (keyword-based, fast) ──────────────────────────────────
DOMAIN_KEYWORDS = {
    "education": [
        "university", "college", "degree", "studied", "education",
        "school", "graduate", "gpa", "major", "course", "scaler",
        "academic", "attend"
    ],
    "experience": [
        "worked", "company", "job", "role", "position", "career",
        "employer", "internship", "employment", "hired", "work experience"
    ],
    "projects": [
        "project", "built", "created", "repo", "github", "app",
        "tool", "system", "platform", "tech stack", "architecture",
        "morph", "anton", "stratum", "odysseus", "terax", "devforge",
        "miso", "doable"
    ],
    "latest_work": [
        "recent", "latest", "currently", "right now", "these days",
        "last commit", "recently built", "what are you working on",
        "working on now", "most recent"
    ],
    "personal": [
        "who is", "background", "about rehan", "tell me about",
        "summary", "profile", "himself", "personality", "skills",
        "contact", "email", "phone", "location"
    ],
}


def _detect_domain(query: str) -> str:
    """Detect query domain from keywords. Returns domain string."""
    q = query.lower()
    scores = {domain: 0 for domain in DOMAIN_KEYWORDS}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in q:
                scores[domain] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


def _apply_trust_weights(
    chunks: list[dict],
    domain: str
) -> list[dict]:
    """
    Re-scores chunks using trust weights for the detected domain.
    Modifies each chunk, then re-sorts by adjusted score.
    """
    weights = TRUST_WEIGHTS.get(domain, DEFAULT_TRUST_WEIGHTS)
    for chunk in chunks:
        source = chunk.get("source", "resume")
        multiplier = weights.get(source, 1.0)
        original_score = chunk["score"]
        chunk["trust_adjusted_score"] = round(original_score * multiplier, 3)
        chunk["domain"] = domain

    # Re-sort by trust-adjusted score (descending)
    chunks.sort(key=lambda c: c["trust_adjusted_score"], reverse=True)
    return chunks


# ─── Main Retrieval Function ──────────────────────────────────────────────────

def retrieve(
    query: str,
    n_results: int = 8,           # Fetch more initially, rerank, then slice
    top_k: int = 5,               # Return this many after reranking
    source_filter: str = None     # Optional hard filter: "resume" | "github" | "linkedin"
) -> list[dict]:
    """
    Retrieves relevant chunks for a query with trust-weighted reranking.

    Returns list of dicts:
    [
        {
            "text": str,
            "source": str,
            "score": float,              # Raw similarity score
            "trust_adjusted_score": float,
            "domain": str,               # Detected query domain
            "metadata": dict
        }
    ]
    """
    embedder = get_embedder()
    collection = get_chroma_collection()

    query_embedding = embedder.embed_query(query)

    where_filter = None
    if source_filter:
        where_filter = {"source": {"$eq": source_filter}}

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    if not results["documents"] or not results["documents"][0]:
        return []

    # Build initial chunk list with raw similarity scores
    chunks = []
    for doc, meta, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        score = 1 - distance  # cosine distance → similarity
        if score < settings.RETRIEVAL_SCORE_THRESHOLD:
            continue
        chunks.append({
            "text": doc,
            "source": meta.get("source", "unknown"),
            "score": round(score, 3),
            "trust_adjusted_score": round(score, 3),  # will be overwritten
            "metadata": meta
        })

    if not chunks:
        return []

    # Detect domain and apply trust weights
    domain = _detect_domain(query)
    chunks = _apply_trust_weights(chunks, domain)

    # Return top-K after reranking
    return chunks[:top_k]


def retrieve_with_github_fallback(query: str) -> list[dict]:
    """
    Use when retrieve() returns empty or low-quality results for latest_work queries.
    Falls back to live GitHub API fetch.
    """
    chunks = retrieve(query)

    domain = _detect_domain(query)
    github_chunks = [c for c in chunks if c["source"] == "github"]

    if domain == "latest_work" and not github_chunks:
        # Trigger live GitHub fetch — import here to avoid circular deps
        from backend.knowledge.ingestion.github_ingester import fetch_recent_commits_live
        live_text = fetch_recent_commits_live()
        if live_text:
            return [{
                "text": live_text,
                "source": "github",
                "score": 0.9,
                "trust_adjusted_score": 1.35,
                "domain": "latest_work",
                "metadata": {"source": "github", "section": "live_commits"}
            }]

    return chunks
