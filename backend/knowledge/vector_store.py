"""
ChromaDB Vector Store Wrapper

Singleton pattern for ChromaDB client and collection.
Collection: anton_knowledge with cosine similarity.
"""

import chromadb
from backend.config import settings

_client = None
_collection = None


def get_chroma_client():
    """Get or create ChromaDB persistent client."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_PATH)
    return _client


def get_chroma_collection():
    """
    Get or create the anton_knowledge collection.
    Uses cosine distance — appropriate for text embeddings (directional, not magnitude).
    """
    global _collection
    if _collection is None:
        client = get_chroma_client()
        _collection = client.get_or_create_collection(
            name="anton_knowledge",
            metadata={"hnsw:space": "cosine"}
        )
    return _collection
