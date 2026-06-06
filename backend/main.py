"""
Son of Anton — FastAPI Main Application

Entrypoint for backend server. Runs routes and middlewares.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from backend.api import chat, voice, health
from backend.database import init_db, log_latency
from backend.config import settings
import time
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB and pre-warm Chroma client/Embeddings singleton
    print("[Startup] Initializing Database...")
    init_db()
    
    print("[Startup] Pre-warming Chroma and Embeddings...")
    try:
        from backend.knowledge.vector_store import get_chroma_collection
        from backend.knowledge.embeddings import get_embedder
        # Trigger singletons
        get_chroma_collection()
        get_embedder()
        print("[Startup] Scaffolding complete and warm.")
    except Exception as e:
        print(f"[Startup] WARNING: Pre-warming failed: {e}")
        
    yield
    # Shutdown logic (if any) goes here

app = FastAPI(
    title="Son of Anton API",
    description="Recruiter-facing AI persona representative backend",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Next.js frontend or other clients
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Latency Logging Middleware
@app.middleware("http")
async def latency_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    latency_ms = int((time.time() - start_time) * 1000)
    
    # Log latency to DB asynchronously (non-blocking)
    if request.url.path in ["/chat", "/voice/webhook"]:
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
app.include_router(voice.router)
app.include_router(health.router)

@app.get("/")
def read_root():
    return {
        "app": "Son of Anton Backend",
        "version": "1.0.0",
        "docs_url": "/docs"
    }
