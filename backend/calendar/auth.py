"""
Google Calendar Auth — OAuth2 Flow

Production: loads from GOOGLE_TOKEN_JSON env var.
Local dev: runs interactive OAuth flow to generate token.json.
"""

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import json
import os
from backend.config import settings

SCOPES = ['https://www.googleapis.com/auth/calendar']

_service = None


def get_calendar_service():
    """Get or create Google Calendar API service."""
    global _service
    if _service is not None:
        return _service

    creds = None

    # Option 1: Load from env var (production)
    if settings.GOOGLE_TOKEN_JSON:
        try:
            creds_data = json.loads(settings.GOOGLE_TOKEN_JSON)
            creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
        except Exception as e:
            print(f"[Calendar] Token JSON parse error: {e}")

    # Option 2: Load from token.json file (local dev)
    token_path = os.path.join("backend", "data", "token.json")
    if not creds and os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"[Calendar] Token refresh failed: {e}")
            creds = None

    if not creds:
        raise RuntimeError(
            "Google Calendar credentials not configured. "
            "Run 'python -m backend.calendar.auth' locally first, "
            "or set GOOGLE_TOKEN_JSON env var."
        )

    _service = build('calendar', 'v3', credentials=creds)
    return _service


if __name__ == "__main__":
    """Run this locally to generate token.json."""
    creds_path = os.path.join("backend", "data", "credentials.json")
    if not os.path.exists(creds_path):
        print(f"Place credentials.json at {creds_path}")
        print("Get it from Google Cloud Console > APIs > Credentials > OAuth 2.0 Client IDs")
        exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(host='127.0.0.1', port=58401)

    token_path = os.path.join("backend", "data", "token.json")
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, 'w') as f:
        f.write(creds.to_json())
    print(f"Token saved to {token_path}")
    print("Set GOOGLE_TOKEN_JSON env var in production with the contents of this file.")
