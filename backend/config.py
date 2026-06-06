"""
Son of Anton — Configuration Module

Loads all environment variables. Never hardcode secrets.
Uses Pydantic BaseSettings for validation and .env loading.
"""

from pydantic_settings import BaseSettings
from typing import List, Optional
import os


class Settings(BaseSettings):
    """
    All configuration loaded from environment variables.
    .env file is loaded automatically.
    """

    # ─── OpenAI ──────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"
    OPENAI_VOICE_MODEL: str = "gpt-4o-mini"

    # ─── GitHub ──────────────────────────────────────────────────────────────
    GITHUB_TOKEN: str
    GITHUB_REPOS: str = "Maverick-sst/Anton,Maverick-sst/odysseus,Maverick-sst/terax-ai,Musharraf1128/Morph,Maverick-sst/Stratum,Maverick-sst/DevForge,Maverick-sst/Doable,Maverick-sst/MisoTTS"

    # ─── Vapi (Voice) ────────────────────────────────────────────────────────
    VAPI_API_KEY: str = ""
    VAPI_PHONE_NUMBER_ID: str = ""
    VAPI_ASSISTANT_ID: str = ""
    VAPI_SERVER_SECRET: str = ""

    # ─── Twilio (Phone number imported into Vapi) ─────────────────────────────
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    # ─── Local dev (ngrok) ────────────────────────────────────────────────────
    # Set to the ngrok https URL during local development.
    # Leave empty in production; the deployed URL is hard-coded into the
    # Vapi assistant when you run backend/scripts/create_vapi_assistant.py.
    BACKEND_PUBLIC_URL: str = ""

    # ─── Redis (Upstash) ─────────────────────────────────────────────────────
    REDIS_URL: str

    # ─── Google Calendar OAuth ───────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_TOKEN_JSON: str = ""  # Serialized token for production

    # ─── PostgreSQL (Supabase) ───────────────────────────────────────────────
    DATABASE_URL: Optional[str] = None
    SUPABASE_CONNECTION_STRING: Optional[str] = None

    # ─── Rehan's email (for calendar invites) ────────────────────────────────
    REHAN_EMAIL: str = "rehan@example.com"

    # ─── ChromaDB ────────────────────────────────────────────────────────────
    CHROMA_PERSIST_PATH: str = "./data/chroma"

    # ─── Retrieval ───────────────────────────────────────────────────────────
    RETRIEVAL_SCORE_THRESHOLD: float = 0.35

    # ─── LangSmith ───────────────────────────────────────────────────────────
    LANGSMITH_API_KEY: str = ""

    # ─── Computed Properties ─────────────────────────────────────────────────
    @property
    def github_repos_list(self) -> List[str]:
        """Parse comma-separated repo list."""
        return [r.strip() for r in self.GITHUB_REPOS.split(",") if r.strip()]

    @property
    def db_url(self) -> Optional[str]:
        """Return whichever DB URL is available, URL-encoding the password if needed."""
        raw_url = self.DATABASE_URL or self.SUPABASE_CONNECTION_STRING
        if not raw_url:
            return None
        try:
            import urllib.parse
            if "://" in raw_url and "@" in raw_url:
                proto, rest = raw_url.split("://", 1)
                user_pass, host_db = rest.rsplit("@", 1)
                if ":" in user_pass:
                    user, password = user_pass.split(":", 1)
                    # Quote special characters in the password
                    password = urllib.parse.quote(password)
                    return f"{proto}://{user}:{password}@{host_db}"
            return raw_url
        except Exception as e:
            print(f"[Config] Error cleaning db_url: {e}")
            return raw_url

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra env vars


# Singleton settings instance
settings = Settings()

# ─── LangSmith auto-setup ────────────────────────────────────────────────────
if settings.LANGSMITH_API_KEY:
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGSMITH_API_KEY
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = "son-of-anton"
