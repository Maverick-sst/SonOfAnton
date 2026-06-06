"""
Link the imported Twilio phone number to the configured Vapi assistant.

Run after:
  1. Importing the Twilio number into Vapi (dashboard)  → VAPI_PHONE_NUMBER_ID
  2. Running create_vapi_assistant.py                    → VAPI_ASSISTANT_ID

Usage:
  export VAPI_API_KEY=...
  export VAPI_PHONE_NUMBER_ID=...
  export VAPI_ASSISTANT_ID=...
  python -m backend.scripts.assign_phone_number
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
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID", "")
VAPI_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID", "")

for name, value in (
    ("VAPI_API_KEY", VAPI_API_KEY),
    ("VAPI_PHONE_NUMBER_ID", VAPI_PHONE_NUMBER_ID),
    ("VAPI_ASSISTANT_ID", VAPI_ASSISTANT_ID),
):
    if not value:
        print(f"ERROR: {name} is not set.", file=sys.stderr)
        sys.exit(1)

resp = httpx.patch(
    f"https://api.vapi.ai/phone-number/{VAPI_PHONE_NUMBER_ID}",
    headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
    json={"assistantId": VAPI_ASSISTANT_ID},
)
resp.raise_for_status()
print(
    f"[Vapi] Phone number {VAPI_PHONE_NUMBER_ID} assigned to assistant {VAPI_ASSISTANT_ID}."
)
