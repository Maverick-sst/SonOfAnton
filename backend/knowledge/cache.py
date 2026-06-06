"""
Knowledge Cache — Redis Wrapper

Caches retrieval answers to avoid redundant LLM + vector store calls.
Key pattern: knowledge:cache:{question_hash}
TTL: 24 hours (knowledge doesn't change mid-day).
"""

import redis
import json
from backend.config import settings
from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=1)
def _get_redis_client():
    """Get cached Redis client."""
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        print(f"[Cache] Redis connection failed: {e}")
        return None


def get_cached_answer(cache_key: str) -> Optional[str]:
    """
    Get a cached answer by key.
    Returns None if not found or Redis is unavailable.
    """
    r = _get_redis_client()
    if r is None:
        return None
    try:
        result = r.get(f"knowledge:cache:{cache_key}")
        return result
    except Exception as e:
        print(f"[Cache] Read failed: {e}")
        return None


def set_cached_answer(cache_key: str, answer: str, ttl: int = 86400) -> None:
    """
    Cache an answer with TTL (default 24 hours).
    Fails silently if Redis is unavailable.
    """
    r = _get_redis_client()
    if r is None:
        return
    try:
        r.setex(f"knowledge:cache:{cache_key}", ttl, answer)
    except Exception as e:
        print(f"[Cache] Write failed: {e}")
