"""
LinkedIn Ingester

Parses LinkedIn CSV export files and ingests into ChromaDB.
Handles whatever CSV files are available — gracefully skips missing ones.

Input: CSV files in linkedIn_data/ directory
Output: Chunks in ChromaDB collection anton_knowledge
"""

import csv
import os
from datetime import datetime
from langchain.text_splitter import RecursiveCharacterTextSplitter
from backend.knowledge.vector_store import get_chroma_collection
from backend.knowledge.embeddings import get_embedder

# Path relative to project root
LINKEDIN_DATA_DIR = "linkedIn_data"
SPLITTER = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=50)


def ingest_linkedin() -> int:
    """
    Ingests LinkedIn CSV export files.
    Returns total number of chunks ingested.
    """
    collection = get_chroma_collection()
    embedder = get_embedder()
    total = 0

    total += _ingest_profile_summary(collection, embedder)
    total += _ingest_positions(collection, embedder)
    total += _ingest_education(collection, embedder)
    total += _ingest_certifications(collection, embedder)

    print(f"[LinkedIn] Ingested {total} chunks total")
    return total


def _ingest_profile_summary(collection, embedder) -> int:
    """
    Ingests the LinkedIn headline and summary from Profile.csv.
    """
    path = os.path.join(LINKEDIN_DATA_DIR, "Profile.csv")
    if not os.path.exists(path):
        print(f"[LinkedIn] Profile.csv not found at {path} — skipping")
        return 0

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return 0

    row = rows[0]  # Profile has one row
    first_name = row.get("First Name", "").strip()
    last_name = row.get("Last Name", "").strip()
    summary = row.get("Summary", "").strip()
    headline = row.get("Headline", "").strip()
    industry = row.get("Industry", "").strip()
    location = row.get("Geo Location", "").strip()

    if not summary and not headline:
        print("[LinkedIn] Profile.csv has no summary or headline")
        return 0

    text = f"Mohammed Rehan ({first_name} {last_name})\n"
    if headline:
        text += f"LinkedIn headline: {headline}\n"
    if industry:
        text += f"Industry: {industry}\n"
    if location:
        text += f"Location: {location}\n"
    if summary:
        text += f"\nProfessional summary:\n{summary}"

    emb = embedder.embed_query(text)
    collection.upsert(
        documents=[text],
        embeddings=[emb],
        metadatas=[{
            "source": "linkedin",
            "section": "summary",
            "domain": "personal",
            "chunk_index": 0,
            "ingested_at": datetime.utcnow().isoformat()
        }],
        ids=["linkedin_summary_0"]
    )
    print(f"  [LinkedIn] Profile summary: 1 chunk")
    return 1


def _ingest_positions(collection, embedder) -> int:
    """
    Ingests work experience from Positions.csv.
    """
    path = os.path.join(LINKEDIN_DATA_DIR, "Positions.csv")
    if not os.path.exists(path):
        print(f"[LinkedIn] Positions.csv not found — skipping")
        return 0

    total = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            company = row.get("Company Name", "").strip()
            title = row.get("Title", "").strip()
            description = row.get("Description", "").strip()
            started = row.get("Started On", "").strip()
            finished = row.get("Finished On", "Present").strip()

            if not company and not title:
                continue

            text = (
                f"Mohammed Rehan worked as {title} at {company} "
                f"from {started} to {finished}."
            )
            if description:
                text += f"\n\nRole details:\n{description}"

            chunks = SPLITTER.split_text(text)
            for j, chunk in enumerate(chunks):
                emb = embedder.embed_query(chunk)
                collection.upsert(
                    documents=[chunk],
                    embeddings=[emb],
                    metadatas=[{
                        "source": "linkedin",
                        "section": "experience",
                        "domain": "experience",
                        "company": company,
                        "title": title,
                        "chunk_index": j,
                        "ingested_at": datetime.utcnow().isoformat()
                    }],
                    ids=[f"linkedin_position_{i}_{j}"]
                )
                total += 1
    if total:
        print(f"  [LinkedIn] Positions: {total} chunks")
    return total


def _ingest_education(collection, embedder) -> int:
    """
    Ingests education from Education.csv.
    """
    path = os.path.join(LINKEDIN_DATA_DIR, "Education.csv")
    if not os.path.exists(path):
        print(f"[LinkedIn] Education.csv not found — skipping")
        return 0

    total = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            school = row.get("School Name", "").strip()
            degree = row.get("Degree Name", "").strip()
            start = row.get("Start Date", "").strip()
            end = row.get("End Date", "").strip()
            activities = row.get("Activities", "").strip()

            if not school:
                continue

            text = f"Mohammed Rehan studied at {school}"
            if degree:
                text += f", earning a {degree}"
            if start or end:
                text += f" ({start} – {end})"
            text += "."
            if activities:
                text += f"\n\nActivities: {activities}"

            emb = embedder.embed_query(text)
            collection.upsert(
                documents=[text],
                embeddings=[emb],
                metadatas=[{
                    "source": "linkedin",
                    "section": "education",
                    "domain": "education",
                    "school": school,
                    "chunk_index": 0,
                    "ingested_at": datetime.utcnow().isoformat()
                }],
                ids=[f"linkedin_education_{i}"]
            )
            total += 1
    if total:
        print(f"  [LinkedIn] Education: {total} chunks")
    return total


def _ingest_certifications(collection, embedder) -> int:
    """
    Ingests certifications from Certifications.csv.
    """
    path = os.path.join(LINKEDIN_DATA_DIR, "Certifications.csv")
    if not os.path.exists(path):
        return 0

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return 0

    cert_lines = []
    for row in rows:
        name = row.get("Name", "").strip()
        authority = row.get("Authority", "").strip()
        finished = row.get("Finished On", "").strip()
        if name:
            line = f"- {name}"
            if authority:
                line += f" (issued by {authority})"
            if finished:
                line += f" — {finished}"
            cert_lines.append(line)

    if cert_lines:
        text = "Mohammed Rehan's certifications:\n" + "\n".join(cert_lines)
        emb = embedder.embed_query(text)
        collection.upsert(
            documents=[text],
            embeddings=[emb],
            metadatas=[{
                "source": "linkedin",
                "section": "certifications",
                "domain": "personal",
                "chunk_index": 0,
                "ingested_at": datetime.utcnow().isoformat()
            }],
            ids=["linkedin_certifications_0"]
        )
        print(f"  [LinkedIn] Certifications: 1 chunk")
        return 1
    return 0
