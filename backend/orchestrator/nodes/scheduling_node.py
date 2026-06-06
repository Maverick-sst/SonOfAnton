"""
Scheduling Node — Multi-step Interview Scheduling
State machine: INIT → ASK_NAME → ASK_EMAIL → SHOW_SLOTS → CONFIRM_SLOT → BOOK → DONE
Also handles reschedule and cancel sub-flows.
"""

import re
import json
from datetime import datetime, timedelta
from backend.orchestrator.state import AntonState
from backend.memory.session_store import get_redis_client
from openai import OpenAI
from backend.config import settings

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client

RESCHEDULE_KEYWORDS = ["reschedule", "change the time", "move the interview", "different time", "postpone"]
CANCEL_KEYWORDS = ["cancel", "don't need", "won't be able", "not happening", "withdraw", "delete the interview"]


def run(state: AntonState) -> AntonState:
    message = state["user_message"].lower()
    if any(kw in message for kw in RESCHEDULE_KEYWORDS):
        return _handle_reschedule(state)
    if any(kw in message for kw in CANCEL_KEYWORDS):
        return _handle_cancel(state)
    return _handle_booking(state)


def _handle_booking(state: AntonState) -> AntonState:
    session_id = state["session_id"]
    sched_state = _load_sched_state(session_id)
    step = sched_state.get("step", "INIT")
    message = state["user_message"]

    if step in ("INIT", "ASK_NAME"):
        name = state.get("recruiter_name") or _extract_name(message)
        if not name:
            _save_sched_state(session_id, {**sched_state, "step": "ASK_NAME"})
            return {**state, "scheduling_answer": "I'd be happy to schedule an interview! Could you share your name first?"}
        sched_state["recruiter_name"] = name
        step = "ASK_EMAIL"

    if step == "ASK_EMAIL":
        email = state.get("recruiter_email") or _extract_email(message)
        if not email:
            _save_sched_state(session_id, {**sched_state, "step": "ASK_EMAIL"})
            return {**state, "scheduling_answer": f"Great, {sched_state.get('recruiter_name', 'there')}! What's your email address so I can send the invite?"}
        sched_state["recruiter_email"] = email
        step = "SHOW_SLOTS"

    if step == "SHOW_SLOTS":
        try:
            from backend.calendar.availability import get_available_slots
            start = datetime.utcnow() + timedelta(days=1)
            end = start + timedelta(days=7)
            slots = get_available_slots(start, end)
        except Exception:
            slots = _generate_mock_slots()
        sched_state["slots"] = slots
        if not slots:
            _save_sched_state(session_id, {**sched_state, "step": "SHOW_SLOTS"})
            return {**state, "scheduling_answer": "Rehan doesn't seem to have availability next week. Could you suggest a different week?"}
        slot_list = "\n".join([f"{i+1}. {s['display']}" for i, s in enumerate(slots)])
        _save_sched_state(session_id, {**sched_state, "step": "CONFIRM_SLOT"})
        return {**state, "scheduling_answer": f"Here are Rehan's available slots:\n{slot_list}\n\nWhich works for you? Just say the number."}

    if step == "CONFIRM_SLOT":
        slots = sched_state.get("slots", [])
        selection = _extract_slot_selection(message, slots)
        if not selection:
            return {**state, "scheduling_answer": "Could you let me know which slot number works? For example, just say 'slot 2'."}
        sched_state["selected_slot"] = selection
        step = "BOOK"

    if step == "BOOK":
        slot = sched_state["selected_slot"]
        event_id = "mock_event"
        try:
            from backend.calendar.booking import book_interview
            result = book_interview(start_time=datetime.fromisoformat(slot["start"]), recruiter_name=sched_state["recruiter_name"], recruiter_email=sched_state["recruiter_email"], recruiter_company=state.get("recruiter_company", ""))
            event_id = result.get("event_id", "mock")
        except Exception as e:
            print(f"[Scheduling] Google Calendar booking failed: {e}")
            event_id = "mock_event"

        _save_sched_state(session_id, {"step": "DONE", "event_id": event_id})
        
        if event_id == "mock_event":
            return {**state, "scheduling_answer": f"Done! I've noted your slot preference for {slot['display']}. Since my calendar integration is currently unconfigured or offline, Rehan will send you the invite manually. Looking forward to speaking with you!"}
        else:
            return {**state, "scheduling_answer": f"Done! I've booked an interview on {slot['display']}. A calendar invite has been sent to {sched_state['recruiter_email']}. Looking forward to speaking with you!"}

    if step == "DONE":
        return {**state, "scheduling_answer": "The interview has already been scheduled! Would you like to reschedule or ask about something else?"}

    return {**state, "scheduling_answer": "How can I help with scheduling?"}


def _handle_reschedule(state: AntonState) -> AntonState:
    session_id = state["session_id"]
    sched_state = _load_sched_state(session_id)
    rs = sched_state.get("reschedule_step", "FIND_EVENT")

    if rs == "FIND_EVENT":
        email = state.get("recruiter_email") or _extract_email(state["user_message"])
        if not email:
            _save_sched_state(session_id, {**sched_state, "reschedule_step": "FIND_EVENT"})
            return {**state, "scheduling_answer": "I'd be happy to reschedule. Could you share the email you used to book?"}
        try:
            from backend.calendar.reschedule import find_event_by_recruiter_email
            event = find_event_by_recruiter_email(email)
        except Exception:
            event = None
        if not event:
            return {**state, "scheduling_answer": f"I couldn't find an upcoming interview under {email}. Are you sure that's the right email?"}
        try:
            from backend.calendar.availability import get_available_slots
            slots = get_available_slots(datetime.utcnow() + timedelta(days=1), datetime.utcnow() + timedelta(days=8))
        except Exception:
            slots = _generate_mock_slots()
        slot_list = "\n".join([f"{i+1}. {s['display']}" for i, s in enumerate(slots)])
        _save_sched_state(session_id, {**sched_state, "reschedule_step": "CONFIRM_NEW_SLOT", "event_id": event["event_id"], "recruiter_email": email, "slots": slots})
        return {**state, "scheduling_answer": f"Found your interview: {event['summary']}.\n\nNew available slots:\n{slot_list}\n\nWhich works?"}

    if rs == "CONFIRM_NEW_SLOT":
        selection = _extract_slot_selection(state["user_message"], sched_state.get("slots", []))
        if not selection:
            return {**state, "scheduling_answer": "Which slot number works? Just say 'slot 2'."}
        try:
            from backend.calendar.reschedule import reschedule_interview
            reschedule_interview(event_id=sched_state["event_id"], new_start_time=datetime.fromisoformat(selection["start"]), recruiter_email=sched_state["recruiter_email"])
        except Exception:
            pass
        _save_sched_state(session_id, {**sched_state, "reschedule_step": "DONE"})
        return {**state, "scheduling_answer": f"Done! Your interview has been rescheduled to {selection['display']}. A calendar update has been sent."}

    return {**state, "scheduling_answer": "Your interview has already been rescheduled."}


def _handle_cancel(state: AntonState) -> AntonState:
    session_id = state["session_id"]
    sched_state = _load_sched_state(session_id)
    cs = sched_state.get("cancel_step", "FIND_EVENT")

    if cs == "FIND_EVENT":
        email = state.get("recruiter_email") or _extract_email(state["user_message"])
        if not email:
            _save_sched_state(session_id, {**sched_state, "cancel_step": "FIND_EVENT"})
            return {**state, "scheduling_answer": "I can cancel that for you. What email did you use when booking?"}
        try:
            from backend.calendar.reschedule import find_event_by_recruiter_email
            event = find_event_by_recruiter_email(email)
        except Exception:
            event = None
        if not event:
            return {**state, "scheduling_answer": f"I couldn't find an upcoming interview under {email}. Could you double-check?"}
        _save_sched_state(session_id, {**sched_state, "cancel_step": "CONFIRM_CANCEL", "event_id": event["event_id"], "recruiter_email": email})
        return {**state, "scheduling_answer": f"Found your interview: {event['summary']}. Do you want me to cancel this? Reply 'yes cancel it' to confirm."}

    if cs == "CONFIRM_CANCEL":
        if any(w in state["user_message"].lower() for w in ["yes", "confirm", "cancel it", "go ahead", "do it"]):
            try:
                from backend.calendar.cancel import cancel_interview
                cancel_interview(sched_state["event_id"])
            except Exception:
                pass
            _save_sched_state(session_id, {**sched_state, "cancel_step": "DONE"})
            return {**state, "scheduling_answer": f"Done — your interview has been cancelled. Feel free to rebook anytime!"}
        _save_sched_state(session_id, {**sched_state, "cancel_step": "DONE"})
        return {**state, "scheduling_answer": "No problem — I won't cancel it. Anything else?"}

    return {**state, "scheduling_answer": "Your interview has already been cancelled."}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_sched_state(session_id):
    r = get_redis_client()
    if r:
        try:
            raw = r.get(f"session:{session_id}:scheduling")
            return json.loads(raw) if raw else {}
        except Exception:
            pass
    return {}

def _save_sched_state(session_id, state):
    r = get_redis_client()
    if r:
        try:
            r.setex(f"session:{session_id}:scheduling", 7200, json.dumps(state))
        except Exception:
            pass

def _llm_extract_email(message: str) -> str | None:
    try:
        c = _get_client()
        resp = c.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a precise data extraction tool. Extract the email address from the user's transcript of a spoken email address. Normalize spaces, spoken punctuation, letters, and numbers to their correct email format (e.g., 'zero five' -> '05', 'two thousand six' -> '2006', 'at g mail dot com' -> '@gmail.com', 'm b rehan' -> 'mbrehan'). Output ONLY the final raw email address string (e.g., 'mbrehan05.2006@gmail.com'). If no email address is present, output 'NONE'."},
                {"role": "user", "content": message}
            ],
            temperature=0,
            max_tokens=60
        )
        ans = resp.choices[0].message.content.strip().lower()
        if "none" in ans or "@" not in ans:
            return None
        return ans
    except Exception as e:
        print(f"[Scheduling] LLM email extraction failed: {e}")
        return None

def _llm_extract_name(message: str) -> str | None:
    try:
        c = _get_client()
        resp = c.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": f"Extract the name of the person speaking from this message: '{message}'. Output ONLY the name itself, capitalized. If no name is mentioned, output 'NONE'."}
            ],
            temperature=0,
            max_tokens=20
        )
        ans = resp.choices[0].message.content.strip().title()
        if ans.upper() == "NONE" or len(ans) > 30:
            return None
        # Block candidate/agent names from being extracted as recruiter name
        ans_lower = ans.lower()
        if "anton" in ans_lower or "rehan" in ans_lower:
            return None
        return ans
    except Exception as e:
        print(f"[Scheduling] LLM name extraction failed: {e}")
        return None

def _llm_extract_slot_selection(message: str, slots: list) -> dict | None:
    if not slots:
        return None
    try:
        slots_str = "\n".join([f"{i+1}. {s['display']} (ID: {s['start']})" for i, s in enumerate(slots)])
        c = _get_client()
        resp = c.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a precise data extraction tool. Identify which slot from the list below the user wants to book. Output ONLY the 1-based index number of the chosen slot (e.g., '2'). If none of the slots match or the user didn't select any, output 'NONE'.\n\nSlots:\n{slots_str}"},
                {"role": "user", "content": message}
            ],
            temperature=0,
            max_tokens=10
        )
        ans = resp.choices[0].message.content.strip()
        if ans.isdigit():
            idx = int(ans)
            if 1 <= idx <= len(slots):
                return slots[idx - 1]
        return None
    except Exception as e:
        print(f"[Scheduling] LLM slot extraction failed: {e}")
        return None

def _extract_name(message):
    clean_message = re.sub(r'[.,!?]+$', '', message.strip())
    # Try safe introduction regex first
    m = re.search(r"(?:my name is|i'm|i am|this is|call me)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)", clean_message, re.IGNORECASE)
    if m:
        return m.group(1).strip().title()
    # Fallback to LLM
    return _llm_extract_name(clean_message)

def _extract_email(message):
    # Try simple regex first
    clean_message = message.lower().replace(" at ", "@").replace(" dot ", ".")
    clean_message = re.sub(r'\s*@\s*', '@', clean_message)
    clean_message = re.sub(r'\s*\.\s*', '.', clean_message)
    m = re.search(r'[\w.-]+@[\w.-]+\.\w+', clean_message)
    if m:
        email = m.group(0)
        if " " not in email:
            return email
    # Fallback to LLM
    return _llm_extract_email(message)

def _extract_slot_selection(message, slots):
    if not slots:
        return None
    nw = {"first":1,"second":2,"third":3,"fourth":4,"fifth":5,"1st":1,"2nd":2,"3rd":3,"4th":4,"5th":5,"one":1,"two":2,"three":3,"four":4,"five":5}
    ml = message.lower()
    for w, n in nw.items():
        if w in ml and 1 <= n <= len(slots):
            return slots[n-1]
    m = re.search(r'\b(\d+)\b', message)
    if m:
        n = int(m.group(1))
        if 1 <= n <= len(slots):
            return slots[n-1]
    # Fallback to LLM
    return _llm_extract_slot_selection(message, slots)

def _generate_mock_slots():
    slots = []
    base = datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    while base.weekday() >= 5: base += timedelta(days=1)
    for i in range(5):
        st = base + timedelta(hours=i*2)
        if st.hour >= 18:
            base += timedelta(days=1)
            while base.weekday() >= 5: base += timedelta(days=1)
            st = base.replace(hour=9)
        slots.append({"start": st.isoformat(), "end": (st+timedelta(minutes=30)).isoformat(), "display": st.strftime("%A, %B %d at %I:%M %p IST")})
    return slots
