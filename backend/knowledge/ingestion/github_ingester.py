"""
GitHub Ingester

Fetches READMEs and recent commit messages from configured GitHub repos.
Only ingests relevant knowledge (READMEs + commits), not full codebases.

Input: List of repos from config.GITHUB_REPOS
Output: Chunks in ChromaDB collection anton_knowledge
"""

import re
from github import Github, Auth
from datetime import datetime
from langchain.text_splitter import RecursiveCharacterTextSplitter
from backend.knowledge.vector_store import get_chroma_collection
from backend.knowledge.embeddings import get_embedder
from backend.config import settings

README_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)


def ingest_github_repos() -> int:
    """
    Ingest READMEs and commit messages from all configured repos.
    Returns total number of chunks ingested.
    """
    auth = Auth.Token(settings.GITHUB_TOKEN)
    g = Github(auth=auth)
    collection = get_chroma_collection()
    embedder = get_embedder()
    total = 0

    for repo_full_name in settings.github_repos_list:
        print(f"[GitHub] Processing {repo_full_name}...")
        try:
            repo = g.get_repo(repo_full_name)
            total += _ingest_readme(repo, collection, embedder)
            total += _ingest_commits(repo, collection, embedder)
            total += _ingest_repo_metadata(repo, collection, embedder)
        except Exception as e:
            print(f"[GitHub] Error processing {repo_full_name}: {e}")
            continue

    print(f"[GitHub] Ingested {total} chunks total")
    g.close()
    return total


def _ingest_readme(repo, collection, embedder) -> int:
    """Ingest README.md content, chunked for larger docs."""
    try:
        readme = repo.get_readme()
        content = readme.decoded_content.decode("utf-8")

        if not content.strip():
            return 0

        chunks = README_SPLITTER.split_text(content)
        for i, chunk in enumerate(chunks):
            emb = embedder.embed_query(chunk)
            collection.upsert(
                documents=[chunk],
                embeddings=[emb],
                metadatas=[{
                    "source": "github",
                    "section": "readme",
                    "repo_name": repo.name,
                    "domain": "projects",
                    "chunk_index": i,
                    "ingested_at": datetime.utcnow().isoformat()
                }],
                ids=[f"github_{repo.name}_readme_{i}"]
            )
        print(f"  [GitHub] {repo.name} README: {len(chunks)} chunks")
        return len(chunks)
    except Exception as e:
        print(f"  [GitHub] {repo.name} has no README or error: {e}")
        return 0


def _ingest_commits(repo, collection, embedder) -> int:
    """Ingest last 30 commit messages as a single document."""
    try:
        commits = list(repo.get_commits()[:30])
        if not commits:
            return 0

        messages = "\n".join([
            f"- {c.commit.message.split(chr(10))[0]}"
            for c in commits
        ])
        doc = f"Recent work in {repo.name} (last {len(commits)} commits):\n{messages}"

        emb = embedder.embed_query(doc)
        collection.upsert(
            documents=[doc],
            embeddings=[emb],
            metadatas=[{
                "source": "github",
                "section": "commits",
                "repo_name": repo.name,
                "domain": "projects",
                "chunk_index": 0,
                "ingested_at": datetime.utcnow().isoformat()
            }],
            ids=[f"github_{repo.name}_commits"]
        )
        print(f"  [GitHub] {repo.name} commits: 1 chunk ({len(commits)} messages)")
        return 1
    except Exception as e:
        print(f"  [GitHub] {repo.name} commits error: {e}")
        return 0


def _ingest_repo_metadata(repo, collection, embedder) -> int:
    """Ingest repo description and basic metadata as a document."""
    parts = [f"Repository: {repo.full_name}"]
    if repo.description:
        parts.append(f"Description: {repo.description}")
    if repo.language:
        parts.append(f"Primary language: {repo.language}")

    # Get topics/tags if available
    try:
        topics = repo.get_topics()
        if topics:
            parts.append(f"Topics: {', '.join(topics)}")
    except Exception:
        pass

    doc = "\n".join(parts)
    emb = embedder.embed_query(doc)
    collection.upsert(
        documents=[doc],
        embeddings=[emb],
        metadatas=[{
            "source": "github",
            "section": "metadata",
            "repo_name": repo.name,
            "domain": "projects",
            "chunk_index": 0,
            "ingested_at": datetime.utcnow().isoformat()
        }],
        ids=[f"github_{repo.name}_meta"]
    )
    return 1


def fetch_recent_commits_live() -> str:
    """
    Live GitHub fallback for latest_work queries.
    Fetches most recent commits across all repos.
    Only called when cached/vector data is insufficient.
    """
    auth = Auth.Token(settings.GITHUB_TOKEN)
    g = Github(auth=auth)
    all_commits = []

    for repo_full_name in settings.github_repos_list[:5]:  # Limit to 5 repos
        try:
            repo = g.get_repo(repo_full_name)
            commits = list(repo.get_commits()[:5])
            for c in commits:
                all_commits.append(
                    f"[{repo.name}] {c.commit.message.split(chr(10))[0]} "
                    f"({c.commit.author.date.strftime('%Y-%m-%d')})"
                )
        except Exception:
            continue

    g.close()

    if all_commits:
        return "Rehan's most recent work:\n" + "\n".join(all_commits[:15])
    return ""


# Repo-name aliases used by the live fallback. The resume / readme /
# ingestion use one casing; recruiters may type a different one. The
# fallback normalises these so "what is odysseus about" finds the
# `Maverick-sst/odysseus` repo regardless of casing.
_REPO_NAME_ALIASES = {
    "odysseus": "odysseus",
    "morph": "Morph",
    "terax": "terax-ai",
    "terax-ai": "terax-ai",
    "anton": "Anton",
    "stratum": "Stratum",
    "devforge": "DevForge",
    "doable": "Doable",
    "misotts": "MisoTTS",
    "miso": "MisoTTS",
    "forkedup": "ForkedUp",
    "forked-up": "ForkedUp",
}


def _resolve_repo_name(query: str) -> str | None:
    """
    Detect a known repo name in the query (case-insensitive) and
    return the canonical repo name as it appears in GITHUB_REPOS.
    """
    q = query.lower()
    for alias, canonical in _REPO_NAME_ALIASES.items():
        # word-boundary match so 'morph' doesn't fire inside 'metamorph'
        if re.search(rf"\b{re.escape(alias)}\b", q):
            return canonical
    return None


def resolve_repo_name(query: str) -> str | None:
    """Public wrapper around _resolve_repo_name so the retriever can use it."""
    return _resolve_repo_name(query)


def fetch_repo_overview_live(repo_name: str) -> str:
    """
    Live GitHub fallback for a SPECIFIC repo. Returns a multi-line
    description string assembled from the live GitHub API:

        Repository: Maverick-sst/<name>
        Description: <live description>
        Primary language: <live language>
        Topics: <live topics>
        Last push: <YYYY-MM-DD>
        Most recent commit: <message> (<date>)

    The repo's README is NOT included here — `fetch_repo_readme_live`
    covers that. Callers can request both.
    """
    auth = Auth.Token(settings.GITHUB_TOKEN)
    g = Github(auth=auth)
    try:
        # Try each configured repo_full_name whose last segment matches
        target_full = None
        for full in settings.github_repos_list:
            if full.split("/")[-1].lower() == repo_name.lower():
                target_full = full
                break
        if not target_full:
            return ""
        repo = g.get_repo(target_full)
        parts = [f"Repository: {repo.full_name}"]
        if repo.description:
            parts.append(f"Description: {repo.description}")
        if repo.language:
            parts.append(f"Primary language: {repo.language}")
        try:
            topics = repo.get_topics()
            if topics:
                parts.append(f"Topics: {', '.join(topics)}")
        except Exception:
            pass
        if repo.pushed_at:
            parts.append(f"Last push: {repo.pushed_at.strftime('%Y-%m-%d')}")
        try:
            latest = list(repo.get_commits()[:1])
            if latest:
                msg = latest[0].commit.message.split(chr(10))[0]
                date = latest[0].commit.author.date.strftime("%Y-%m-%d")
                parts.append(f"Most recent commit: {msg} ({date})")
        except Exception:
            pass
        return "\n".join(parts)
    except Exception as e:
        print(f"[GitHub] Live repo overview for {repo_name} failed: {e}")
        return ""
    finally:
        g.close()


def fetch_repo_readme_live(repo_name: str, max_chars: int = 2000) -> str:
    """
    Live GitHub fallback: fetch a repo's README, truncated. Used when
    the cached/vector README is missing or stale (e.g. the cached one
    is the default Next.js boilerplate for a freshly-created repo).
    """
    auth = Auth.Token(settings.GITHUB_TOKEN)
    g = Github(auth=auth)
    try:
        target_full = None
        for full in settings.github_repos_list:
            if full.split("/")[-1].lower() == repo_name.lower():
                target_full = full
                break
        if not target_full:
            return ""
        repo = g.get_repo(target_full)
        try:
            readme = repo.get_readme()
        except Exception:
            return ""
        content = readme.decoded_content.decode("utf-8", errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + "\n... (truncated)"
        return f"README for {repo.full_name}:\n{content}"
    except Exception as e:
        print(f"[GitHub] Live README for {repo_name} failed: {e}")
        return ""
    finally:
        g.close()


def fetch_recent_repos_overview_live(max_repos: int = 5) -> str:
    """
    Live GitHub fallback for "most recent project" / "what has he been
    working on lately" queries. Returns a list of the most recently
    pushed repos WITH their live descriptions, primary language, and
    last push date. This is what the recruiter actually wants — not
    just commit hashes.
    """
    auth = Auth.Token(settings.GITHUB_TOKEN)
    g = Github(auth=auth)
    try:
        # Pull all configured repos and sort by pushed_at desc. We use
        # the configured list (not the full user) so the fallback is
        # bounded and predictable.
        repos = []
        for full in settings.github_repos_list:
            try:
                repo = g.get_repo(full)
                repos.append(repo)
            except Exception:
                continue
        repos.sort(key=lambda r: r.pushed_at or datetime(1970, 1, 1), reverse=True)
        repos = repos[:max_repos]

        lines = ["Rehan's most recently active GitHub projects (live):"]
        for r in repos:
            desc = r.description or "(no description on GitHub)"
            lang = r.language or "n/a"
            pushed = r.pushed_at.strftime("%Y-%m-%d") if r.pushed_at else "?"
            lines.append(
                f"- {r.name}: {desc} (language: {lang}, last push: {pushed})"
            )
        return "\n".join(lines)
    except Exception as e:
        print(f"[GitHub] Live recent-repos overview failed: {e}")
        return ""
    finally:
        g.close()
