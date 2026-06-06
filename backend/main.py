"""
Son of Anton — FastAPI Main Application

Entrypoint for backend server. Runs routes and middlewares.
"""

import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from backend.api import chat, vapi, health
from backend.database import init_db, log_latency
from backend.config import settings
import time
import asyncio
from contextlib import asynccontextmanager

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://son-of-anton.vercel.app",
    "https://son-of-anton-git-main.vercel.app",
    "https://son-of-anton-xi.vercel.app",
]
if os.environ.get("VERCEL_PREVIEW_URL"):
    ALLOWED_ORIGINS.append(os.environ["VERCEL_PREVIEW_URL"])
EXTRA_ORIGINS = os.environ.get("EXTRA_CORS_ORIGINS", "")
if EXTRA_ORIGINS:
    ALLOWED_ORIGINS.extend(o.strip() for o in EXTRA_ORIGINS.split(",") if o.strip())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and pre-warm Chroma client/Embeddings singleton
    try:
        init_db()
    except Exception as e:
        print(f"[Startup] DB init skipped: {e}")

    print("[Startup] Pre-warming Chroma and Embeddings...")
    try:
        from backend.knowledge.vector_store import get_chroma_collection
        from backend.knowledge.embeddings import get_embedder
        collection = get_chroma_collection()
        if collection.count() == 0:
            print("[Startup] Chroma is empty — running ingestion (this takes ~1 min)...")
            try:
                from backend.knowledge.ingestion.run_ingestion import run_all
                run_all()
            except Exception as e:
                print(f"[Startup] Ingestion failed: {e}")
        else:
            print(f"[Startup] Chroma has {collection.count()} chunks — skipping ingestion")
        embedder = get_embedder()
        embedder.embed_query("warmup")
        print("[Startup] Scaffolding complete and warm.")
    except Exception as e:
        print(f"[Startup] WARNING: Pre-warming failed: {e}")

    yield


app = FastAPI(
    title="Son of Anton API",
    description="Recruiter-facing AI persona representative backend",
    version="1.0.0",
    lifespan=lifespan
)

# CORS — locked down. Update ALLOWED_ORIGINS above to add more.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Request Latency Logging Middleware
@app.middleware("http")
async def latency_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    latency_ms = int((time.time() - start_time) * 1000)

    # Log latency to DB asynchronously (non-blocking)
    if request.url.path in ["/chat", "/vapi/chat"]:
        session_id = None
        # Try to retrieve session_id from headers/query if present for correlation
        if "session-id" in request.headers:
            session_id = request.headers["session-id"]
        asyncio.create_task(
            log_latency(request.url.path, latency_ms, session_id)
        )

    response.headers["X-Latency-Ms"] = str(latency_ms)
    return response

# Mount routes
app.include_router(chat.router)
app.include_router(vapi.router)
app.include_router(health.router)

@app.get("/")
def read_root():
    return {
        "app": "Son of Anton Backend",
        "version": "1.0.0",
        "docs_url": "/docs"
    }
