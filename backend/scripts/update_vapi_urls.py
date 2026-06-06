"""
Re-point an existing Vapi assistant at a new BACKEND_PUBLIC_URL.

Use this every time ngrok restarts and the public URL changes. The assistant
record in Vapi stores the Custom LLM URL and the Server URL — both must be
updated or calls will hit a dead endpoint.

Usage:
  export VAPI_API_KEY=...
  export VAPI_ASSISTANT_ID=...
  export BACKEND_PUBLIC_URL=https://new-subdomain.ngrok-free.app
  python -m backend.scripts.update_vapi_urls
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
VAPI_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID", "")
BACKEND_PUBLIC_URL = os.environ.get("BACKEND_PUBLIC_URL", "")

for name, value in (
    ("VAPI_API_KEY", VAPI_API_KEY),
    ("VAPI_ASSISTANT_ID", VAPI_ASSISTANT_ID),
    ("BACKEND_PUBLIC_URL", BACKEND_PUBLIC_URL),
):
    if not value:
        print(f"ERROR: {name} is not set.", file=sys.stderr)
        sys.exit(1)

base = BACKEND_PUBLIC_URL.rstrip("/")
payload = {
    "model": {
        "provider": "custom-llm",
        "url": f"{base}/vapi/chat",
        "model": "gpt-4o",
        "systemPrompt": "",
    },
    "serverUrl": f"{base}/vapi/webhook",
}

resp = httpx.patch(
    f"https://api.vapi.ai/assistant/{VAPI_ASSISTANT_ID}",
    headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
    json=payload,
)
resp.raise_for_status()
print(f"[Vapi] Assistant {VAPI_ASSISTANT_ID} URLs updated to {base}")
print(f"[Vapi]   model.url   = {base}/vapi/chat")
print(f"[Vapi]   serverUrl   = {base}/vapi/webhook")
