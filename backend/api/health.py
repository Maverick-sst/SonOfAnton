"""
Health Check Router

Verifies system dependencies (ChromaDB, Redis, Supabase connection).
"""

from fastapi import APIRouter
from backend.knowledge.vector_store import get_chroma_collection
from backend.memory.session_store import get_redis_client
import psycopg2
from backend.config import settings
import time

router = APIRouter(prefix="/health", tags=["health"])

@router.get("")
def health_check():
    status = {
        "status": "ok",
        "timestamp": time.time(),
        "services": {
            "chroma": "unknown",
            "redis": "unknown",
            "database": "unknown"
        }
    }
    
    # Chroma Check
    try:
        coll = get_chroma_collection()
        status["services"]["chroma"] = f"ok ({coll.count()} docs)"
    except Exception as e:
        status["status"] = "error"
        status["services"]["chroma"] = f"error: {str(e)}"

    # Redis Check
    try:
        r = get_redis_client()
        if r and r.ping():
            status["services"]["redis"] = "ok"
        else:
            status["services"]["redis"] = "disconnected"
    except Exception as e:
        status["services"]["redis"] = f"error: {str(e)}"

    # DB Check
    db_url = settings.db_url
    if db_url:
        try:
            conn = psycopg2.connect(db_url, connect_timeout=3)
            conn.close()
            status["services"]["database"] = "ok"
        except Exception as e:
            status["services"]["database"] = f"error: {str(e)}"
    else:
        status["services"]["database"] = "not_configured"

    return status
