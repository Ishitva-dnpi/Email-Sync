"""
MailMind parser — zero heavy dependencies.
Uses dateparser + regex only (no spaCy / no API).
"""
import re
import dateparser
from datetime import datetime, timedelta

# ── Course code patterns ───────────────────────────────────────────────────
_COURSE_RE = re.compile(
    r'\b([A-Z]{2,5}\s*F\s*\d{3,4}[A-Z]?'   # MATH F111, CS F213, ECE F242
    r'|[A-Z][a-z]*\s*F\d{3}'               # MathF111
    r'|[Uu]\d{3,4}'                         # U103, U104
    r'|(?:BITS|bits)\s*F\d{3}'             # BITS F111
    r')\b',
    re.IGNORECASE
)

# Short subject aliases (single words that map to subjects)
_SUBJECT_ALIASES = {
    "maths": "MATHS", "math": "MATH", "mathematics": "MATHS",
    "physics": "PHY", "phy": "PHY",
    "chemistry": "CHEM", "chem": "CHEM",
    "cs": "CS", "computer science": "CS", "computing": "CS",
    "ds": "DS", "data structures": "DS",
    "algo": "ALGO", "algorithms": "ALGO",
    "mgts": "MGTS", "management": "MGTS",
    "eco": "ECO", "economics": "ECO",
    "english": "ENG", "eng": "ENG",
    "bio": "BIO", "biology": "BIO",
    "ee": "EEE", "electrical": "EEE",
    "me": "ME", "mechanical": "ME",
    "chem eng": "CHEME",
    "thermodynamics": "THERMO", "thermo": "THERMO",
    "signals": "SIGNALS", "dsp": "DSP",
    "networking": "NET", "networks": "NET",
    "os": "OS", "operating systems": "OS",
    "dbms": "DBMS", "database": "DBMS",
    "software": "SE", "se": "SE",
    "ai": "AI", "ml": "ML", "machine learning": "ML",
}

# ── Component patterns ─────────────────────────────────────────────────────
_COMP_RE = re.compile(
    r'\b(L\s*[-–]?\s*\d+)\b'           # L1, L-1, L 1
    r'|\b(P\s*[-–]?\s*\d+)\b'          # P2, P-2
    r'|\b(T\s*[-–]?\s*\d+)\b'          # T3
    r'|\b(Lecture\s+\d+)\b'            # Lecture 5
    r'|\b(Lab\s+\d+)\b'                # Lab 3
    r'|\b(Practical\s+\d+)\b'          # Practical 2
    r'|\b(Tutorial\s+\d+|Tut\s+\d+)\b',# Tutorial 2
    re.IGNORECASE
)

# ── Exam / event keywords ──────────────────────────────────────────────────
_EXAM_KW = {
    "compre": ["compre", "comprehensive", "comprehensive exam"],
    "endsem": ["endsem", "end sem", "end-sem", "end semester", "final exam", "finals"],
    "midsem": ["midsem", "mid sem", "mid-sem", "midterm", "mid semester", "mid term"],
    "quiz":   ["quiz", "class test", "unit test", "ct"],
    "labtest":["lab test", "lab exam", "practical exam", "practical test", "lab assessment"],
    "viva":   ["viva", "oral exam", "oral test"],
}
_TYPE_KW = {
    "exam":       ["exam", "test", "assessment", "evaluation"],
    "deadline":   ["deadline", "due date", "submission", "submit by", "last date"],
    "assignment": ["assignment", "homework", "hw", "project submission", "report submission"],
    "meeting":    ["meeting", "lecture", "class", "session", "seminar", "workshop"],
    "event":      ["event", "fest", "competition", "hackathon", "webinar", "symposium", "induction"],
}

# ── Urgency / priority keywords ────────────────────────────────────────────
_URGENT_KW = ["urgent", "important", "reminder", "tomorrow", "today", "last chance",
              "final", "compre", "endsem", "midsem"]


def _norm(text: str) -> str:
    return re.sub(r'\s+', ' ', text.lower().strip())


def detect_component(text: str):
    m = _COMP_RE.search(text)
    if not m:
        return None
    raw = next(g for g in m.groups() if g)
    raw = raw.strip()
    # Normalise to L1/P2/T3 form
    low = raw.lower()
    if low.startswith("lecture"):
        num = re.search(r'\d+', raw).group()
        return f"L{num}"
    if low.startswith("lab"):
        num = re.search(r'\d+', raw).group()
        return f"P{num}"
    if low.startswith("practical"):
        num = re.search(r'\d+', raw).group()
        return f"P{num}"
    if low.startswith("tutorial") or low.startswith("tut"):
        num = re.search(r'\d+', raw).group()
        return f"T{num}"
    # Already L1/P2/T3
    letter = raw[0].upper()
    num = re.search(r'\d+', raw).group()
    return f"{letter}{num}"


def detect_subject(text: str):
    # Try BITS-style course codes first
    m = _COURSE_RE.search(text)
    if m:
        return re.sub(r'\s+', ' ', m.group(0).upper().strip())
    # Try subject aliases (whole-word match)
    low = _norm(text)
    for alias, canon in _SUBJECT_ALIASES.items():
        if re.search(r'\b' + re.escape(alias) + r'\b', low):
            return canon
    return None


def detect_exam_subtype(text: str):
    low = _norm(text)
    for subtype, keywords in _EXAM_KW.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', low):
                return subtype
    return None


def classify(text: str):
    """Returns (type, subtype)."""
    low = _norm(text)
    subtype = detect_exam_subtype(text)
    if subtype in ("compre", "endsem", "midsem", "quiz", "labtest", "viva"):
        return ("exam", subtype)
    for typ, keywords in _TYPE_KW.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', low):
                return (typ, subtype)
    return ("event", subtype)


def _parse_dates(text: str, email_date):
    """Extract all candidate dates from text using dateparser."""
    dates = []
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": email_date or datetime.now(),
        "RETURN_AS_TIMEZONE_AWARE": False,
    }
    # Split on sentence boundaries & look for date-like fragments
    patterns = [
        r'(?:on|by|before|due|scheduled|date)[:\s]+([A-Za-z0-9,\s/:.-]+?)(?:\.|,|$)',
        r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
        r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{0,4})',
        r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:\s*,\s*\d{4})?)',
        r'((?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[,\s]+[A-Za-z0-9\s,]+)',
        r'(\d{1,2}(?:st|nd|rd|th)\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d{0,4})',
    ]
    seen = set()
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            snippet = m.group(1).strip()
            if snippet in seen or len(snippet) < 4:
                continue
            seen.add(snippet)
            parsed = dateparser.parse(snippet, settings=settings)
            if parsed and parsed > (email_date or datetime.now()) - timedelta(days=1):
                dates.append(parsed)
    return dates


def _parse_time(text: str):
    """Extract first time mention like 9:00 AM, 14:00, 2pm."""
    m = re.search(
        r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?'
        r'|\d{1,2}\s*(?:AM|PM|am|pm))\b',
        text
    )
    if not m:
        return None
    raw = m.group(0).strip()
    # Normalise
    try:
        t = datetime.strptime(raw.upper(), "%I:%M %p")
        return t.strftime("%I:%M %p")
    except Exception:
        pass
    try:
        t = datetime.strptime(raw.upper(), "%I %p")
        return t.strftime("%I:%M %p")
    except Exception:
        pass
    try:
        t = datetime.strptime(raw, "%H:%M")
        return t.strftime("%I:%M %p")
    except Exception:
        pass
    return raw


def _priority(text: str, typ: str, subtype) -> int:
    low = _norm(text)
    if subtype in ("compre", "endsem"):
        return 5
    if subtype == "midsem":
        return 4
    if any(kw in low for kw in _URGENT_KW):
        return 3
    if typ == "deadline":
        return 3
    if typ == "exam":
        return 3
    return 1


def _confirmed(subject_code, user_courses) -> bool:
    """True if the email's course matches the user's registered courses."""
    if not user_courses:
        return True  # no courses set → accept everything
    if not subject_code:
        return False  # unrecognised course → needs review
    code_up = subject_code.upper()
    for uc in user_courses:
        uc_up = uc.upper().replace(" ", "")
        c_up  = code_up.replace(" ", "")
        if uc_up in c_up or c_up in uc_up:
            return True
    return False


# ── Main entry point ───────────────────────────────────────────────────────

def extract_events(email_subject: str, email_body: str, email_date, user_courses) -> list:
    """
    Returns list of event dicts from one email.
    Fields: title, date, time, type, subtype, subject, component,
            description, priority, confirmed
    """
    full_text = f"{email_subject}\n{email_body}"
    low = _norm(full_text)

    # Quick skip: if no date-like or event-like keywords, skip
    _EVENT_HINTS = [
        "exam", "quiz", "test", "midsem", "endsem", "compre",
        "deadline", "due", "submit", "assignment", "schedule",
        "date", "jan", "feb", "mar", "apr", "may", "jun",
        "jul", "aug", "sep", "oct", "nov", "dec",
        r'\d{1,2}/\d{1,2}', r'\d{1,2}-\d{1,2}',
    ]
    if not any(re.search(h, low) for h in _EVENT_HINTS):
        return []

    dates = _parse_dates(full_text, email_date)
    if not dates:
        return []

    typ, subtype = classify(full_text)
    subject_code = detect_subject(full_text)
    component    = detect_component(full_text)
    time_str     = _parse_time(full_text)
    priority     = _priority(full_text, typ, subtype)
    is_confirmed = _confirmed(subject_code, user_courses)

    # Build a readable title
    parts = []
    if subtype:
        parts.append(subtype.upper())
    if subject_code:
        parts.append(subject_code)
    if component:
        parts.append(f"[{component}]")
    if not parts:
        parts.append(typ.upper())
    # Append email subject (trimmed)
    subj_clean = re.sub(r'^(re|fwd?|fw):\s*', '', email_subject, flags=re.IGNORECASE).strip()
    if subj_clean:
        parts.append("—")
        parts.append(subj_clean[:60])
    title = " ".join(parts)

    desc = email_body[:200].replace('\n', ' ').strip() if email_body else email_subject

    events = []
    seen_dates = set()
    for dt in dates[:3]:  # max 3 dates per email
        ds = dt.strftime("%Y-%m-%d")
        if ds in seen_dates:
            continue
        seen_dates.add(ds)
        events.append({
            "title":       title,
            "date":        ds,
            "time":        time_str,
            "type":        typ,
            "subtype":     subtype,
            "subject":     subject_code,
            "component":   component,
            "description": desc,
            "priority":    priority,
            "confirmed":   is_confirmed,
        })

    return events
