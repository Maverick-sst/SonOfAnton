"""
Embedding Wrapper

Uses OpenAI text-embedding-3-small for cost-effective embeddings.
Singleton via @lru_cache — don't create a new client per request.
"""

from langchain_openai import OpenAIEmbeddings
from backend.config import settings
from functools import lru_cache


@lru_cache(maxsize=1)
def get_embedder() -> OpenAIEmbeddings:
    """Returns a cached OpenAI embeddings client."""
    return OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=settings.OPENAI_API_KEY,
        dimensions=1536
    )
