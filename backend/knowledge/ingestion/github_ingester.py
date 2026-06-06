"""
GitHub Ingester

Fetches READMEs and recent commit messages from configured GitHub repos.
Only ingests relevant knowledge (READMEs + commits), not full codebases.

Input: List of repos from config.GITHUB_REPOS
Output: Chunks in ChromaDB collection anton_knowledge
"""

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
