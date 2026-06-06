"""
Booking Service — Create GCal interview event.
"""
from backend.calendar.auth import get_calendar_service
from backend.config import settings
from datetime import datetime, timedelta

def book_interview(start_time: datetime, recruiter_name: str, recruiter_email: str, recruiter_company: str = "") -> dict:
    service = get_calendar_service()
    end_time = start_time + timedelta(minutes=30)
    event = {
        "summary": f"Interview: Rehan ↔ {recruiter_name} ({recruiter_company})",
        "description": f"Interview scheduled via Son of Anton AI.\nRecruiter: {recruiter_name}\nEmail: {recruiter_email}\nCompany: {recruiter_company}",
        "start": {"dateTime": start_time.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end_time.isoformat(), "timeZone": "Asia/Kolkata"},
        "attendees": [{"email": recruiter_email}, {"email": settings.REHAN_EMAIL}],
        "conferenceData": {"createRequest": {"requestId": f"anton_{int(start_time.timestamp())}"}},
        "reminders": {"useDefault": False, "overrides": [{"method": "email", "minutes": 60}, {"method": "popup", "minutes": 15}]}
    }
    created = service.events().insert(calendarId="primary", body=event, conferenceDataVersion=1, sendUpdates="all").execute()
    return {
        "event_id": created["id"], "event_link": created.get("htmlLink"), "summary": created["summary"],
        "start": created["start"]["dateTime"], "end": created["end"]["dateTime"],
        "meet_link": created.get("conferenceData", {}).get("entryPoints", [{}])[0].get("uri", "")
    }
