"""
PostgreSQL / Supabase Database Manager

Handles database initialization and logging latency/evaluation results.
"""

import psycopg2
from psycopg2.extras import Json
from backend.config import settings
from typing import Optional, List, Dict, Any

_db_initialized = False

def init_db():
    """Create sessions, interview_events, and eval_logs tables if they do not exist."""
    global _db_initialized
    if _db_initialized:
        return
        
    db_url = settings.db_url
    if not db_url:
        print("[Database] Database connection string not set. Skipping DB initialization.")
        return
        
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # Enable gen_random_uuid() extension if needed
        cur.execute("CREATE EXTENSION IF NOT EXISTS \"pgcrypto\";")
        
        # Sessions Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id VARCHAR(255) UNIQUE NOT NULL,
                channel VARCHAR(10) NOT NULL CHECK (channel IN ('voice', 'chat')),
                recruiter_name VARCHAR(255),
                recruiter_email VARCHAR(255),
                recruiter_company VARCHAR(255),
                created_at TIMESTAMP DEFAULT NOW(),
                last_active TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # Interview Events Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS interview_events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id VARCHAR(255) REFERENCES sessions(session_id),
                gcal_event_id VARCHAR(255) UNIQUE NOT NULL,
                recruiter_name VARCHAR(255),
                recruiter_email VARCHAR(255),
                scheduled_at TIMESTAMP NOT NULL,
                duration_minutes INTEGER DEFAULT 30,
                status VARCHAR(20) DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'rescheduled', 'cancelled')),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # Eval Logs Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS eval_logs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id VARCHAR(255),
                question TEXT NOT NULL,
                retrieved_chunks JSONB,
                answer TEXT,
                is_hallucination BOOLEAN,
                judge_verdict JSONB,
                latency_ms INTEGER,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        _db_initialized = True
        print("[Database] Database initialized successfully.")
    except Exception as e:
        print(f"[Database] Error initializing database: {e}")

async def log_latency(path: str, latency_ms: int, session_id: Optional[str] = None):
    """
    Log endpoint request latency to the sessions or eval_logs table.
    Runs asynchronously, failing silently if the DB is down.
    """
    db_url = settings.db_url
    if not db_url:
        return
        
    try:
        # Since this runs in an async task, create a connection
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # If it's a chat session, we can save or update the session
        if session_id:
            cur.execute("""
                INSERT INTO sessions (session_id, channel)
                VALUES (%s, %s)
                ON CONFLICT (session_id) DO UPDATE
                SET last_active = NOW();
            """, (session_id, "voice" if "voice" in path else "chat"))
            
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Database] Error logging latency: {e}")

def log_evaluation(
    session_id: str,
    question: str,
    answer: str,
    retrieved_chunks: List[Dict[str, Any]],
    latency_ms: int,
    is_hallucination: Optional[bool] = None,
    judge_verdict: Optional[Dict[str, Any]] = None
):
    """Log full evaluation/conversation turn to eval_logs table."""
    db_url = settings.db_url
    if not db_url:
        return
        
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO eval_logs (session_id, question, retrieved_chunks, answer, is_hallucination, judge_verdict, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            session_id,
            question,
            Json(retrieved_chunks),
            answer,
            is_hallucination,
            Json(judge_verdict) if judge_verdict else None,
            latency_ms
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Database] Error logging evaluation: {e}")
