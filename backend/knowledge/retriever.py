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
from backend.knowledge.cache import get_cached_answer, set_cached_answer, _get_redis_client
from backend.config import settings
import hashlib
import json


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


def _get_or_embed(query: str, embedder) -> list[float]:
    """Get embedding from Redis cache if exists, else call OpenAI embedding API and cache it."""
    r = _get_redis_client()
    cache_key = f"emb:{hashlib.md5(query.lower().strip().encode()).hexdigest()}"
    if r:
        try:
            cached = r.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            print(f"[Retriever] Embedding cache read failed: {e}")

    embedding = embedder.embed_query(query)

    if r:
        try:
            r.setex(cache_key, 3600, json.dumps(embedding))  # 1hr TTL
        except Exception as e:
            print(f"[Retriever] Embedding cache write failed: {e}")
    return embedding


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

    query_embedding = _get_or_embed(query, embedder)

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

    # For project-related queries, force-include the resume's Projects
    # section. The pure-embedding retriever can rank project-describing
    # chunks (resume Projects section) below boilerplate commits and
    # metadata, leaving the LLM without the project description. Pulling
    # these in directly guarantees the LLM has the human-curated
    # one-liner ("Doable | AI App Builder — Clone of Emergent / Lovable")
    # in its context for any project query.
    if domain in ("projects", "latest_work", "personal"):
        projects_section = _get_resume_section_chunks("Projects")
        if projects_section:
            # Inject with a trust score above the median so they survive
            # the top-K slice.
            for c in projects_section:
                c["trust_adjusted_score"] = max(0.6, c["trust_adjusted_score"])
                c["domain"] = domain
            chunks = chunks + projects_section
            chunks.sort(key=lambda c: c["trust_adjusted_score"], reverse=True)
            chunks = chunks[:top_k]

    # Return top-K after reranking
    return chunks[:top_k]


def _get_resume_section_chunks(section_name: str) -> list[dict]:
    """
    Fetch every chunk from the resume whose `section` metadata field
    equals `section_name`. Used as a hard include for sections the
    pure-embedding retriever under-ranks — e.g. the Projects section
    for project-description queries.

    ChromaDB does not support compound `where` filters in this version
    (single operator only), so we filter by `source=resume` in the
    query and narrow by section in Python.
    """
    from backend.knowledge.vector_store import get_chroma_collection
    collection = get_chroma_collection()
    try:
        data = collection.get(
            where={"source": "resume"},
            include=["documents", "metadatas"]
        )
    except Exception as e:
        print(f"[Retriever] _get_resume_section_chunks failed: {e}")
        return []
    out = []
    for doc, meta in zip(data.get("documents") or [], data.get("metadatas") or []):
        if meta.get("section") == section_name:
            out.append({
                "text": doc,
                "source": "resume",
                "score": 0.5,
                "trust_adjusted_score": 0.5,
                "domain": "projects",
                "metadata": meta
            })
    return out


def retrieve_with_github_fallback(query: str) -> list[dict]:
    """
    Use when retrieve() returns empty or low-quality results, or when
    the query is about a specific project / latest work and the cached
    chunks don't actually describe the project. Falls back to live
    GitHub API calls.

    Three trigger paths:
      1. retrieve() returned nothing → live overview of recent repos
      2. domain == "latest_work" and no github chunks → live commits
      3. domain == "projects" and a known repo name is in the query, but
         the retrieved chunks don't actually describe that repo (e.g.
         the README is the default Next.js boilerplate for a brand-new
         project like Doable) → live repo overview + live README
    """
    chunks = retrieve(query)
    domain = _detect_domain(query)
    github_chunks = [c for c in chunks if c["source"] == "github"]

    # Lazy import to avoid circular deps.
    from backend.knowledge.ingestion.github_ingester import (
        fetch_recent_commits_live,
        fetch_recent_repos_overview_live,
        fetch_repo_overview_live,
        fetch_repo_readme_live,
        resolve_repo_name,
    )

    # Path 1: empty retrieval — knowledge base has nothing for this
    # query at all. Pull a live overview of recent repos as a generic
    # "here's what he's been up to" answer.
    if not chunks:
        live_text = fetch_recent_repos_overview_live()
        if live_text:
            return [{
                "text": live_text,
                "source": "github",
                "score": 0.85,
                "trust_adjusted_score": 1.275,
                "domain": "unknown",
                "metadata": {"source": "github", "section": "live_overview", "is_live": True}
            }]
        return chunks

    # Path 2: latest_work query with no github chunks. The cached
    # vector store should already have commit data, but if it doesn't,
    # pull fresh.
    if domain == "latest_work" and not github_chunks:
        live_text = fetch_recent_commits_live()
        if live_text:
            chunks = chunks + [{
                "text": live_text,
                "source": "github",
                "score": 0.9,
                "trust_adjusted_score": 1.35,
                "domain": "latest_work",
                "metadata": {"source": "github", "section": "live_commits", "is_live": True}
            }]

    # Path 3: query mentions a specific repo, but the chunks for that
    # repo don't actually describe it. Heuristic for "doesn't describe
    # it": the only chunks that mention the repo are commits and/or
    # metadata with no description text. In that case, ask the live
    # GitHub API for the actual repo description (and the README if
    # it's not a default-template boilerplate).
    repo_name = resolve_repo_name(query)
    if domain in ("projects", "latest_work") and repo_name:
        repo_lower = repo_name.lower()
        # Did retrieve() return anything that actually DESCRIBES the repo?
        has_meaningful_github = any(
            c["source"] == "github"
            and (
                (c.get("metadata", {}).get("section") in ("readme", "metadata"))
                and c.get("text") and len(c.get("text", "")) > 200
                and "next.js" not in c["text"][:400].lower()  # skip boilerplate
            )
            for c in chunks
        )
        mentioned = any(
            repo_lower in (c.get("text", "").lower())
            for c in chunks
        )
        if mentioned and not has_meaningful_github:
            overview = fetch_repo_overview_live(repo_name)
            readme = fetch_repo_readme_live(repo_name)
            extras = []
            if overview:
                extras.append({
                    "text": overview,
                    "source": "github",
                    "score": 0.92,
                    "trust_adjusted_score": 1.38,
                    "domain": "projects",
                    "metadata": {
                        "source": "github",
                        "section": "live_overview",
                        "repo_name": repo_name,
                        "is_live": True,
                    }
                })
            if readme:
                extras.append({
                    "text": readme,
                    "source": "github",
                    "score": 0.88,
                    "trust_adjusted_score": 1.32,
                    "domain": "projects",
                    "metadata": {
                        "source": "github",
                        "section": "live_readme",
                        "repo_name": repo_name,
                        "is_live": True,
                    }
                })
            if extras:
                chunks = chunks + extras

    return chunks
