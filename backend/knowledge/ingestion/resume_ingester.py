"""
Resume Ingester

Parses PDF resume using pdfplumber, splits into logical sections,
chunks each section, embeds, and upserts to ChromaDB.

Input: resume_x1.pdf
Output: Chunks in ChromaDB collection anton_knowledge
"""

import pdfplumber
import re
from datetime import datetime
from langchain.text_splitter import RecursiveCharacterTextSplitter
from backend.knowledge.vector_store import get_chroma_collection
from backend.knowledge.embeddings import get_embedder

SECTION_HEADER_PATTERN = re.compile(r'^[A-Z][A-Z\s]{3,}$', re.MULTILINE)


def ingest_resume(pdf_path: str) -> int:
    """
    Parse and ingest a resume PDF into ChromaDB.
    Returns number of chunks ingested.
    """
    print(f"[Resume] Reading {pdf_path}...")

    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            text += page_text + "\n"

    if not text.strip():
        print("[Resume] WARNING: No text extracted from PDF")
        return 0

    sections = _split_into_sections(text)
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)

    collection = get_chroma_collection()
    embedder = get_embedder()

    total = 0
    for section_name, section_text in sections.items():
        if not section_text.strip():
            continue

        # Clean table text (collapse tabs into commas)
        section_text = _clean_table_text(section_text)

        chunks = splitter.split_text(section_text)
        for i, chunk in enumerate(chunks):
            embedding = embedder.embed_query(chunk)
            doc_id = f"resume_{section_name.lower().replace(' ', '_')}_{i}"

            collection.upsert(
                documents=[chunk],
                embeddings=[embedding],
                metadatas=[{
                    "source": "resume",
                    "section": section_name,
                    "domain": _infer_domain(section_name),
                    "chunk_index": i,
                    "ingested_at": datetime.utcnow().isoformat()
                }],
                ids=[doc_id]
            )
            total += 1
            print(f"  [Resume] Section '{section_name}' chunk {i}: {len(chunk)} chars")

    print(f"[Resume] Ingested {total} chunks total")
    return total


def _split_into_sections(text: str) -> dict:
    """
    Split resume text into named sections by detecting ALL-CAPS headers.
    Falls back to a single section if no headers found.
    """
    lines = text.split("\n")
    sections = {}
    current_section = "General"
    current_content = []

    for line in lines:
        stripped = line.strip()
        # Detect section headers: lines that are mostly uppercase, short, and not numbers
        if (stripped
                and len(stripped) > 2
                and len(stripped) < 60
                and stripped.upper() == stripped
                and not stripped.isdigit()
                and any(c.isalpha() for c in stripped)):
            # Save previous section
            if current_content:
                sections[current_section] = "\n".join(current_content)
            current_section = stripped.title()
            current_content = []
        else:
            current_content.append(line)

    # Save last section
    if current_content:
        sections[current_section] = "\n".join(current_content)

    # If only one section and it's GENERAL, try a different approach
    if len(sections) == 1 and "General" in sections:
        # Treat the entire text as a single document
        sections = {"Full Resume": text}

    return sections


def _infer_domain(section_name: str) -> str:
    """Map section name to knowledge domain for trust hierarchy."""
    mapping = {
        "EXPERIENCE": "experience",
        "WORK": "experience",
        "EMPLOYMENT": "experience",
        "EDUCATION": "education",
        "ACADEMIC": "education",
        "PROJECTS": "projects",
        "PROJECT": "projects",
        "SKILLS": "personal",
        "TECHNICAL": "personal",
        "SUMMARY": "personal",
        "PROFILE": "personal",
        "ABOUT": "personal",
        "OBJECTIVE": "personal",
        "CONTACT": "personal",
        "CERTIFICATIONS": "personal",
        "ACHIEVEMENTS": "personal",
        "AWARDS": "personal",
    }
    upper = section_name.upper()
    for key, val in mapping.items():
        if key in upper:
            return val
    return "personal"


def _clean_table_text(text: str) -> str:
    """Collapse tab-separated text (from PDF tables) into comma-separated."""
    text = re.sub(r'\t+', ', ', text)
    text = re.sub(r'  +', ' ', text)
    return text
