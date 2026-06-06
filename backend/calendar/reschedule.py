"""
Reschedule Service — Update existing GCal event to a new time.
"""
from backend.calendar.auth import get_calendar_service
from datetime import datetime, timedelta

def get_event_by_id(event_id: str) -> dict | None:
    service = get_calendar_service()
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        if event.get("status") == "cancelled": return None
        return {"event_id": event["id"], "summary": event.get("summary", ""), "start": event["start"].get("dateTime"), "end": event["end"].get("dateTime"), "attendees": [a["email"] for a in event.get("attendees", [])]}
    except Exception:
        return None

def find_event_by_recruiter_email(recruiter_email: str) -> dict | None:
    service = get_calendar_service()
    now = datetime.utcnow().isoformat() + "Z"
    events_result = service.events().list(calendarId="primary", timeMin=now, maxResults=10, singleEvents=True, orderBy="startTime", q=recruiter_email).execute()
    for event in events_result.get("items", []):
        if "Son of Anton" in event.get("description", ""):
            return {"event_id": event["id"], "summary": event.get("summary", ""), "start": event["start"].get("dateTime"), "attendees": [a["email"] for a in event.get("attendees", [])]}
    return None

def reschedule_interview(event_id: str, new_start_time: datetime, recruiter_email: str) -> dict:
    service = get_calendar_service()
    existing = service.events().get(calendarId="primary", eventId=event_id).execute()
    new_end_time = new_start_time + timedelta(minutes=30)
    existing["start"] = {"dateTime": new_start_time.isoformat(), "timeZone": "Asia/Kolkata"}
    existing["end"] = {"dateTime": new_end_time.isoformat(), "timeZone": "Asia/Kolkata"}
    existing["description"] = existing.get("description", "") + f"\n\n[Rescheduled on {datetime.utcnow().strftime('%Y-%m-%d')} via Anton]"
    updated = service.events().update(calendarId="primary", eventId=event_id, body=existing, sendUpdates="all").execute()
    return {"event_id": updated["id"], "summary": updated["summary"], "new_start": updated["start"]["dateTime"], "new_end": updated["end"]["dateTime"], "event_link": updated.get("htmlLink")}
