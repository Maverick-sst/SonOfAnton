"""
Knowledge Ingestion Runner

CLI entrypoint: python -m backend.knowledge.ingestion.run_ingestion
Runs all three ingesters in sequence.
"""

import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from backend.knowledge.ingestion.resume_ingester import ingest_resume
from backend.knowledge.ingestion.github_ingester import ingest_github_repos
from backend.knowledge.ingestion.linkedin_ingester import ingest_linkedin


def run_all():
    print("=" * 60)
    print("=== Son of Anton — Knowledge Ingestion ===")
    print("=" * 60)

    # Resume
    resume_path = "resume_x1.pdf"
    if os.path.exists(resume_path):
        n = ingest_resume(resume_path)
        print(f"\n[Resume] ✓ Ingested {n} chunks\n")
    else:
        print(f"\n[Resume] ✗ File not found: {resume_path}")
        print("  Place your resume PDF at the project root as resume_x1.pdf\n")

    # GitHub
    try:
        n = ingest_github_repos()
        print(f"\n[GitHub] ✓ Ingested {n} chunks\n")
    except Exception as e:
        print(f"\n[GitHub] ✗ Error: {e}\n")

    # LinkedIn
    try:
        n = ingest_linkedin()
        print(f"\n[LinkedIn] ✓ Ingested {n} chunks\n")
    except Exception as e:
        print(f"\n[LinkedIn] ✗ Error: {e}\n")

    print("=" * 60)
    print("=== Ingestion Complete ===")
    print("=" * 60)

    # Verify collection count
    from backend.knowledge.vector_store import get_chroma_collection
    collection = get_chroma_collection()
    count = collection.count()
    print(f"\nTotal documents in ChromaDB: {count}")


if __name__ == "__main__":
    run_all()
