"""
Create (or update) the Vapi assistant for Son of Anton.

Idempotent: if an assistant with the same name already exists in the Vapi
account, it is PATCHed in place rather than duplicated.

Run once after:
  1. Importing the Twilio number into Vapi (dashboard)
  2. Exporting VAPI_API_KEY, BACKEND_PUBLIC_URL (ngrok), VAPI_SERVER_SECRET

Usage:
  export VAPI_API_KEY=...
  export BACKEND_PUBLIC_URL=https://xxxx.ngrok-free.app
  export VAPI_SERVER_SECRET=...   # optional
  python -m backend.scripts.create_vapi_assistant
"""

import os
import sys
import httpx

try:
    from dotenv import load_dotenv
    load_dotenv()  # picks up .env at repo root if present
except Exception:
    pass

VAPI_API_KEY = os.environ.get("VAPI_API_KEY", "")
BACKEND_PUBLIC_URL = os.environ.get("BACKEND_PUBLIC_URL", "")

if not VAPI_API_KEY:
    print("ERROR: VAPI_API_KEY is not set.", file=sys.stderr)
    sys.exit(1)

if not BACKEND_PUBLIC_URL:
    print(
        "ERROR: BACKEND_PUBLIC_URL is not set. "
        "Start ngrok (e.g. `ngrok http 8000`) and export its https URL.",
        file=sys.stderr,
    )
    sys.exit(1)

ASSISTANT_NAME = "Anton - Rehan's AI Representative"
base = BACKEND_PUBLIC_URL.rstrip("/")

headers = {"Authorization": f"Bearer {VAPI_API_KEY}"}

payload = {
    "name": ASSISTANT_NAME,
    "model": {
        "provider": "custom-llm",
        "url": f"{base}/vapi/chat",
        "model": "gpt-4o",
        "systemPrompt": "",
    },
    "voice": {
        "provider": "vapi",
        "voiceId": "Elliot",
    },
    "firstMessage": "Hi, I'm Anton — Rehan's AI representative. How can I help you today?",
    "endCallMessage": "It was great talking with you. I'll make sure Rehan is informed. Have a great day!",
    "endCallPhrases": ["goodbye", "bye", "talk to you later", "thanks, bye"],
    "serverUrl": f"{base}/vapi/webhook",
    "serverUrlSecret": os.environ.get("VAPI_SERVER_SECRET", ""),
    "hipaaEnabled": False,
    "recordingEnabled": True,
    "silenceTimeoutSeconds": 30,
    "maxDurationSeconds": 1800,
    "backgroundSound": "off",
    "backchannelingEnabled": True,
    "backgroundDenoisingEnabled": True,
}

print(f"[Vapi] Looking for existing assistant named '{ASSISTANT_NAME}'...")
list_resp = httpx.get(
    "https://api.vapi.ai/assistant",
    headers=headers,
    params={"limit": 100},
)
list_resp.raise_for_status()
existing = next(
    (a for a in list_resp.json() if a.get("name") == ASSISTANT_NAME),
    None,
)

if existing:
    print(f"[Vapi] Updating existing assistant: {existing['id']}")
    resp = httpx.patch(
        f"https://api.vapi.ai/assistant/{existing['id']}",
        headers=headers,
        json=payload,
    )
else:
    print("[Vapi] Creating new assistant...")
    resp = httpx.post(
        "https://api.vapi.ai/assistant",
        headers=headers,
        json=payload,
    )

resp.raise_for_status()
data = resp.json()
print(f"[Vapi] Assistant ready. ID: {data['id']}")
print(f"[Vapi] Set VAPI_ASSISTANT_ID={data['id']}")
