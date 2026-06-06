"""
Availability Service — Fetch free slots from Google Calendar.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from backend.calendar.auth import get_calendar_service

INTERVIEW_DURATION_MINUTES = 30
WORKING_HOURS_START = 9
WORKING_HOURS_END = 18
CALENDAR_ID = "primary"
IST = ZoneInfo("Asia/Kolkata")

def get_available_slots(start_date: datetime, end_date: datetime, timezone_str: str = "Asia/Kolkata") -> list[dict]:
    service = get_calendar_service()
    
    # Ensure start_date and end_date are timezone-aware in IST
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc).astimezone(IST)
    else:
        start_date = start_date.astimezone(IST)
        
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc).astimezone(IST)
    else:
        end_date = end_date.astimezone(IST)

    body = {
        "timeMin": start_date.isoformat(),
        "timeMax": end_date.isoformat(),
        "items": [{"id": CALENDAR_ID}],
        "timeZone": timezone_str
    }
    freebusy = service.freebusy().query(body=body).execute()
    busy_periods = freebusy["calendars"][CALENDAR_ID]["busy"]
    slots = _generate_candidate_slots(start_date, end_date)
    available = []
    for slot in slots:
        slot_end = slot + timedelta(minutes=INTERVIEW_DURATION_MINUTES)
        if not _overlaps_with_busy(slot, slot_end, busy_periods):
            available.append({
                "start": slot.isoformat(),
                "end": slot_end.isoformat(),
                "display": slot.strftime("%A, %B %d at %I:%M %p IST")
            })
    return available[:5]

def _generate_candidate_slots(start, end):
    slots = []
    current = start.replace(hour=WORKING_HOURS_START, minute=0, second=0, microsecond=0)
    while current < end:
        if WORKING_HOURS_START <= current.hour < WORKING_HOURS_END and current.weekday() < 5:
            if current >= start:
                slots.append(current)
        current += timedelta(minutes=30)
        if current.hour >= WORKING_HOURS_END:
            current += timedelta(days=1)
            current = current.replace(hour=WORKING_HOURS_START, minute=0)
    return slots

def _overlaps_with_busy(start, end, busy_periods):
    for bp in busy_periods:
        bs = datetime.fromisoformat(bp["start"]).astimezone(IST)
        be = datetime.fromisoformat(bp["end"]).astimezone(IST)
        if start < be and end > bs:
            return True
    return False
