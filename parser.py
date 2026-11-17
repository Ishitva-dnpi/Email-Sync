"""
Smart local email parser — no AI, no API credits.
Extracts events using keyword matching + dateparser.
"""
import re, dateparser
from datetime import datetime

KEYWORDS = {
    "exam":       ["exam", "test", "quiz", "midterm", "final exam", "viva", "paper", "assessment"],
    "deadline":   ["deadline", "due date", "last date", "submit by", "closes on", "last day to"],
    "assignment": ["assignment due", "homework due", "project due", "report due", "submission due", "essay due"],
    "meeting":    ["meeting at", "call scheduled", "interview", "appointment", "standup", "zoom at"],
    "event":      ["event on", "seminar", "workshop", "webinar", "conference", "orientation", "fest", "ceremony"],
}
ALL_KW = [k for v in KEYWORDS.values() for k in v]

PRIORITY = {"exam": 5, "deadline": 4, "assignment": 3, "meeting": 2, "event": 1, "other": 1}

def classify(text):
    t = text.lower()
    for typ, words in KEYWORDS.items():
        if any(w in t for w in words):
            return typ
    return "other"

def has_keyword(text):
    t = text.lower()
    return any(k in t for k in ALL_KW)

def parse_date(text, base):
    try:
        return dateparser.parse(text, settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": base,
            "RETURN_AS_TIMEZONE_AWARE": False,
        })
    except Exception:
        return None

def extract_events(subject, body, email_date=None):
    base = email_date or datetime.now()
    today = datetime.now()
    events, seen = [], set()

    for seg in re.split(r"(?<=[.!?\n])\s*", f"{subject}\n\n{body}"):
        seg = seg.strip()
        if len(seg) < 8 or len(seg) > 400 or not has_keyword(seg):
            continue
        parsed = parse_date(seg, base)
        if not parsed or parsed <= today:
            continue
        date_key = parsed.date().isoformat()
        typ = classify(seg)
        key = f"{typ}-{date_key}-{subject[:20]}"
        if key in seen:
            continue
        seen.add(key)
        title = subject.strip()[:70]
        events.append({
            "title": title,
            "date": date_key,
            "time": parsed.strftime("%I:%M %p") if parsed.hour else None,
            "type": typ,
            "description": seg[:220],
            "source": subject[:60],
            "priority": PRIORITY.get(typ, 1),
        })
    return events
