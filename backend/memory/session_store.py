"""
Session Store — Redis Session Read/Write

Handles conversation history and session metadata.
Key patterns:
    session:{session_id}:history  → List of {role, content} dicts
    session:{session_id}:meta     → Recruiter metadata
"""

import redis
import json
from backend.config import settings
from functools import lru_cache
from datetime import timedelta
from typing import Optional

SESSION_TTL = timedelta(hours=2)
MAX_HISTORY_LENGTH = 20


@lru_cache(maxsize=1)
def get_redis_client():
    """Get cached Redis client."""
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        print(f"[SessionStore] Redis connection failed: {e}")
        return None


def get_history(session_id: str) -> list[dict]:
    """Load conversation history from Redis."""
    r = get_redis_client()
    if r is None:
        return []
    try:
        raw = r.get(f"session:{session_id}:history")
        if not raw:
            return []
        return json.loads(raw)
    except Exception as e:
        print(f"[SessionStore] Read error: {e}")
        return []


def save_message(session_id: str, role: str, content: str) -> None:
    """Appends a message and resets TTL."""
    r = get_redis_client()
    if r is None:
        return
    try:
        key = f"session:{session_id}:history"
        history = get_history(session_id)
        history.append({"role": role, "content": content})

        # Keep only last MAX_HISTORY_LENGTH turns
        if len(history) > MAX_HISTORY_LENGTH:
            history = history[-MAX_HISTORY_LENGTH:]

        r.setex(key, SESSION_TTL, json.dumps(history))
    except Exception as e:
        print(f"[SessionStore] Write error: {e}")


def get_session_meta(session_id: str) -> dict:
    """Get session metadata (recruiter info, etc.)."""
    r = get_redis_client()
    if r is None:
        return {}
    try:
        raw = r.get(f"session:{session_id}:meta")
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def save_session_meta(session_id: str, meta: dict) -> None:
    """Save session metadata."""
    r = get_redis_client()
    if r is None:
        return
    try:
        existing = get_session_meta(session_id)
        existing.update(meta)
        r.setex(f"session:{session_id}:meta", SESSION_TTL, json.dumps(existing))
    except Exception as e:
        print(f"[SessionStore] Meta write error: {e}")


def clear_session(session_id: str) -> None:
    """Clear all session data."""
    r = get_redis_client()
    if r is None:
        return
    try:
        r.delete(f"session:{session_id}:history")
        r.delete(f"session:{session_id}:meta")
        r.delete(f"session:{session_id}:scheduling")
        r.delete(f"session:{session_id}:summary")
    except Exception as e:
        print(f"[SessionStore] Clear error: {e}")
