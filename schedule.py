"""
Generates a smart preparation schedule working backwards from each deadline/exam.
No AI needed — pure algorithmic scheduling.
"""
from datetime import datetime, timedelta
from models import db, ScheduleSlot, Event

PREP_DAYS  = {"exam": 5, "deadline": 3, "assignment": 2, "meeting": 1, "event": 1, "other": 1}
SLOT_HOURS = {"exam": 2, "deadline": 1, "assignment": 1, "meeting": 1, "event": 1, "other": 1}
SLOT_TIMES = ["09:00", "11:00", "14:00", "16:00", "19:00", "21:00"]

def _time_add(t, hours):
    h, m = map(int, t.split(":"))
    total = h * 60 + m + hours * 60
    return f"{total//60:02d}:{total%60:02d}"

def build_schedule(user_id):
    """Rebuild the full schedule for a user from their current events."""
    # Clear old slots
    ScheduleSlot.query.filter_by(user_id=user_id).delete()

    events = Event.query.filter_by(user_id=user_id).filter(
        Event.date >= datetime.now().strftime("%Y-%m-%d")
    ).order_by(Event.priority.desc(), Event.date).all()

    today = datetime.now().date()
    # Track used slots per day: date -> list of used start times
    used = {}

    for ev in events:
        try:
            ev_date = datetime.strptime(ev.date, "%Y-%m-%d").date()
        except Exception:
            continue

        prep = PREP_DAYS.get(ev.type, 1)
        duration = SLOT_HOURS.get(ev.type, 1)
        days_until = (ev_date - today).days

        if days_until <= 0:
            continue

        actual_prep = min(prep, days_until)
        slots_needed = actual_prep  # one slot per prep day

        slots_created = 0
        for d in range(actual_prep, 0, -1):
            slot_date = ev_date - timedelta(days=d)
            if slot_date < today:
                continue

            date_key = slot_date.isoformat()
            day_used = used.get(date_key, [])

            # Find a free time slot
            for t in SLOT_TIMES:
                if t not in day_used:
                    end_t = _time_add(t, duration)
                    slot = ScheduleSlot(
                        user_id=user_id,
                        event_id=ev.id,
                        date=date_key,
                        start_time=t,
                        end_time=end_t,
                        label=f"Prep: {ev.title[:50]}",
                        slot_type="prep" if d > 1 else "review",
                        done=False,
                    )
                    db.session.add(slot)
                    day_used.append(t)
                    used[date_key] = day_used
                    slots_created += 1
                    break

            if slots_created >= slots_needed:
                break

    db.session.commit()
