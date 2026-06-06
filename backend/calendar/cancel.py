"""
Cancel Service — Delete GCal event and notify attendees.
"""
from backend.calendar.auth import get_calendar_service

def cancel_interview(event_id: str) -> dict:
    service = get_calendar_service()
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        summary = event.get("summary", "your interview")
        start = event["start"].get("dateTime", "")
        service.events().delete(calendarId="primary", eventId=event_id, sendUpdates="all").execute()
        return {"cancelled": True, "event_id": event_id, "summary": summary, "was_scheduled_for": start}
    except Exception as e:
        return {"cancelled": False, "event_id": event_id, "error": str(e)}
