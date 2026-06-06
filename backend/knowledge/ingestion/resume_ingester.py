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


# Curated list of common resume section headers. The original splitter only
# recognised ALL-CAPS lines, which meant a header like "Technical Skills"
# (Title Case) was never detected — and the skills list ended up merged into
# the previous section (typically Education). Adding this allowlist lets the
# splitter recognise the headers that real resumes actually use.
KNOWN_SECTION_HEADERS = {
    "about", "summary", "profile", "objective", "contact", "contacts",
    "education", "academic", "academics", "qualifications",
    "experience", "work experience", "employment",
    "professional experience", "work history", "career",
    "projects", "personal projects", "academic projects", "key projects",
    "skills", "technical skills", "skills & tools", "skills and tools",
    "core competencies", "tech stack", "technologies", "tech",
    "certifications", "certificates", "licenses",
    "achievements", "awards", "honors", "honors and awards",
    "publications", "research", "patents",
    "interests", "hobbies", "activities",
    "references", "volunteer", "volunteering",
    "extracurricular", "extracurriculars",
}


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

    # Wipe stale resume chunks before re-ingesting. The doc_id format
    # changed (sections are now first-class) so re-running without a wipe
    # would leave orphan chunks with the old "resume_general_*" ids that
    # are no longer referenced by any section name. Those orphans would
    # pollute retrieval with stale, un-sectioned content.
    try:
        existing = collection.get(where={"source": "resume"}, include=[])
        if existing and existing.get("ids"):
            collection.delete(ids=existing["ids"])
            print(f"[Resume] Wiped {len(existing['ids'])} stale resume chunks")
    except Exception as e:
        print(f"[Resume] WARNING: failed to wipe stale chunks: {e}")

    total = 0
    for section_name, section_text in sections.items():
        if not section_text.strip():
            continue

        # Clean table text (collapse tabs into commas)
        section_text = _clean_table_text(section_text)

        chunks = splitter.split_text(section_text)
        for i, chunk in enumerate(chunks):
            # Prefix the chunk with its section name. Without this, a chunk
            # in the "Technical Skills" section that starts with
            # "Languages: Java, JavaScript, ..." has poor semantic overlap
            # with a query like "what are rehan's skills" — the section
            # name never appears in the chunk text. Prepending the section
            # name keeps the LLM grounded AND raises the chunk's embedding
            # similarity to skills/tech/stack queries.
            header = f"[Section: {section_name}]\n"
            chunk_with_header = header + chunk
            embedding = embedder.embed_query(chunk_with_header)
            doc_id = f"resume_{section_name.lower().replace(' ', '_')}_{i}"

            collection.upsert(
                documents=[chunk_with_header],
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

        # Skills meta-chunk. The raw Technical Skills chunks are dominated
        # by concrete tech terms ("Java", "TypeScript", "MERN", ...) which
        # have weak semantic overlap with short generic queries like
        # "what are rehan's skills" or "his tech stack" — those queries
        # never share embeddings with the tech terms, so the chunk ranks
        # below the retrieval threshold. To fix this, we emit one extra
        # dense-summary chunk whose text is tuned to match the kinds of
        # phrasings recruiters actually use. The summary content is
        # assembled from the section text, not invented, so it remains
        # grounded.
        if section_name.lower() in {"technical skills", "skills", "skills & tools", "skills and tools"}:
            summary_text = (
                f"[Section: {section_name}]\n"
                f"Rehan's technical skills, technologies, languages, frameworks, "
                f"and developer tools.\n\n{section_text.strip()}"
            )
            summary_id = f"resume_{section_name.lower().replace(' ', '_')}_summary"
            summary_emb = embedder.embed_query(summary_text)
            collection.upsert(
                documents=[summary_text],
                embeddings=[summary_emb],
                metadatas=[{
                    "source": "resume",
                    "section": section_name,
                    "domain": _infer_domain(section_name),
                    "chunk_index": -1,           # -1 marks this as the meta-summary
                    "is_summary": True,
                    "ingested_at": datetime.utcnow().isoformat()
                }],
                ids=[summary_id]
            )
            total += 1
            print(f"  [Resume] Section '{section_name}' skills-summary chunk: {len(summary_text)} chars")

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
        # Detect section headers. A line is a header if any of:
        #   1. ALL-CAPS short line (e.g. "EDUCATION")
        #   2. Lowercased form matches a known resume section name
        #      (e.g. "Technical Skills", "Work Experience")
        # It is NOT a header if it ends with ':' — those are sub-bullets
        # like "Languages: Java, Python" that should stay inside the
        # parent section.
        is_all_caps = (
            len(stripped) > 2
            and len(stripped) < 60
            and stripped.upper() == stripped
            and not stripped.isdigit()
            and any(c.isalpha() for c in stripped)
        )
        is_known_header = (
            len(stripped) > 2
            and len(stripped) < 60
            and stripped.lower() in KNOWN_SECTION_HEADERS
        )
        if stripped and not stripped.endswith(":") and (is_all_caps or is_known_header):
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
