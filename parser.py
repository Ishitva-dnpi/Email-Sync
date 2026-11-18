"""
Smart local email parser — spaCy NER + academic subcategory + component detection.
Zero API usage. Understands BITS-style course codes, L/P/T components.
"""
import re
import dateparser
from datetime import datetime, timedelta

try:
    import spacy
    try:
        nlp = spacy.load("en_core_web_sm")
        SPACY_OK = True
    except OSError:
        nlp = None
        SPACY_OK = False
except ImportError:
    nlp = None
    SPACY_OK = False

# ── Academic subcategory keywords ─────────────────────────────────────────
EXAM_SUBTYPES = {
    "midsem":  ["midsem", "mid-sem", "mid sem", "midterm", "mid-term",
                "mid term", "midsemester", "mid semester"],
    "endsem":  ["endsem", "end-sem", "end sem", "endsemester",
                "end semester", "final exam", "finals", "end term"],
    "compre":  ["compre", "comprehensive", "comprehensive exam"],
    "quiz":    ["quiz", "class test", "ct1", "ct2", "ct3", "ct4", "ct5",
                "weekly test", "unit test", "pop quiz", "surprise test",
                "class quiz"],
    "labtest": ["lab test", "lab exam", "lab assessment", "practical exam",
                "practical test", "lab viva", "lab evaluation", "lab quiz",
                "lab sessional"],
    "viva":    ["viva", "oral exam", "oral test", "oral examination"],
}

KEYWORDS = {
    "exam":       list(set(sum(EXAM_SUBTYPES.values(), []) +
                   ["exam", "examination", "test on", "scheduled test"])),
    "deadline":   ["deadline", "due date", "last date", "submit by",
                   "submission deadline", "closing date", "expire",
                   "expires on", "last day to", "cutoff", "final date"],
    "assignment": ["assignment", "homework", "project due", "report due",
                   "submit", "submission", "turn in", "hand in", "coursework",
                   "lab report", "problem set", "pset", "tutorial submission"],
    "meeting":    ["meeting", "meet at", "call at", "zoom", "teams meeting",
                   "google meet", "conference", "seminar", "webinar",
                   "session at", "office hours", "sync at"],
    "event":      ["event", "workshop", "hackathon", "fest", "festival",
                   "ceremony", "orientation", "induction", "registration",
                   "open day", "career fair", "placement", "interview",
                   "presentation"],
}

PRIORITY = {
    "compre": 7, "endsem": 7, "midsem": 6, "labtest": 5, "viva": 5,
    "quiz": 4, "exam": 5, "deadline": 4, "assignment": 3,
    "meeting": 2, "event": 1, "other": 1,
}

# ── Course / subject detection ─────────────────────────────────────────────
# BITS codes: MATH F111, CS F111, PHY F110, U103, U104, BIO F111, BITS F112
_COURSE_CODE_RE = re.compile(
    r'\b([A-Z]{2,5}\s+F\s*\d{3,4}[A-Z]?'   # MATH F111, CS F213
    r'|[A-Z]{2,5}F\d{3,4}'                   # CSF213
    r'|[A-Z][a-z]*\s*F\d{3}'                 # PhyF110
    r'|[Uu]\d{3,4}'                           # U103, u104
    r')\b',
    re.IGNORECASE
)

_SUBJECT_ALIASES = {
    "maths":     ["math", "maths", "mathematics", "calculus", "algebra",
                  "statistics", "stat", "linear algebra", "discrete math"],
    "physics":   ["physics", "phy", "mechanics", "quantum", "electro",
                  "thermodynamics for phy"],
    "chemistry": ["chemistry", "chem", "organic", "inorganic", "physical chem"],
    "biology":   ["biology", "bio", "biochem", "microbio", "genetics"],
    "cs":        ["cs", "computer science", "programming", "data structures",
                  "algorithms", "dsa", "oop", "object oriented", "dbms",
                  "database", "os ", "operating system", "networks", "cn",
                  "compiler", "software engineering", "python", "java", "c++"],
    "mgts":      ["mgts", "management", "economics", "econ", "finance",
                  "accounting", "hrm", "marketing", "strategy", "business"],
    "english":   ["english", "communication", "language", "writing", "grammar",
                  "technical writing"],
    "ee":        ["ee", "electrical", "electronics", "circuits", "signals",
                  "control system", "embedded", "vlsi", "microprocessor"],
    "me":        ["mechanical", "thermodynamics", "fluid mechanics",
                  "manufacturing", "machine design"],
    "civil":     ["civil", "structural", "construction", "surveying",
                  "geotechnical"],
    "bits":      ["bits", "bits f", "think and do"],
}

# ── Component detection: L1, P2, T3, L-1, Lecture 1, Lab 2, Tutorial 3 ──
_COMPONENT_RE = re.compile(
    r'\b((?:L|P|T)\s*[-–]?\s*\d+)\b'           # L1, P2, T3, L-1
    r'|\b(Lecture\s+\d+)\b'                      # Lecture 1
    r'|\b(Lab\s+\d+|Practical\s+\d+)\b'          # Lab 2, Practical 2
    r'|\b(Tutorial\s+\d+|Tut\s+\d+)\b',          # Tutorial 3
    re.IGNORECASE
)

_DATE_PATTERNS = [
    r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b',
    r'\b(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{0,4})\b',
    r'\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)\b',
    r'\b((?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s*,\s*\w+\s*\d{1,2})?)\b',
    r'\b(tomorrow|today|next\s+\w+)\b',
    r'\b(\d{1,2}(?:st|nd|rd|th)\s+(?:of\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)\b',
]
_DATE_RE  = re.compile('|'.join(_DATE_PATTERNS), re.IGNORECASE)
_TIME_RE  = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))\b', re.IGNORECASE)
_SENT_RE  = re.compile(r'(?<=[.!?])\s+')


def detect_subject(text: str) -> str | None:
    m = _COURSE_CODE_RE.search(text)
    if m:
        return re.sub(r'\s+', ' ', m.group(0)).strip().upper()
    t = text.lower()
    for subject, aliases in _SUBJECT_ALIASES.items():
        if any(a in t for a in aliases):
            return subject.upper()
    return None


def detect_component(text: str) -> str | None:
    """Detect L1/P2/T3 style components."""
    m = _COMPONENT_RE.search(text)
    if not m:
        return None
    raw = next(g for g in m.groups() if g)
    # Normalise: Lecture 1 -> L1, Lab 2 -> P2, Tutorial 3 -> T3
    raw = raw.strip()
    r = raw.lower()
    if r.startswith("lecture"):
        return "L" + re.search(r'\d+', raw).group()
    if r.startswith("lab") or r.startswith("practical"):
        return "P" + re.search(r'\d+', raw).group()
    if r.startswith("tutorial") or r.startswith("tut"):
        return "T" + re.search(r'\d+', raw).group()
    # Already short form L1/P2/T3
    return re.sub(r'[\s–-]', '', raw).upper()


def detect_exam_subtype(text: str) -> str | None:
    t = text.lower()
    for subtype, kws in EXAM_SUBTYPES.items():
        if any(kw in t for kw in kws):
            return subtype
    return None


def classify(text: str) -> tuple[str, str | None]:
    t = text.lower()
    subtype = detect_exam_subtype(t)
    if subtype:
        if subtype == "quiz":
            return "quiz", subtype
        if subtype == "labtest":
            return "labtest", subtype
        return "exam", subtype
    for typ, kws in KEYWORDS.items():
        if any(kw in t for kw in kws):
            return typ, None
    return "other", None


def has_keyword(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in sum(KEYWORDS.values(), []))


def parse_date(text: str, base: datetime = None) -> datetime | None:
    base = base or datetime.now()
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": base,
        "RETURN_AS_TIMEZONE_AWARE": False,
    }
    try:
        d = dateparser.parse(text, settings=settings)
        if d and abs((d - base).days) < 730:
            return d
    except Exception:
        pass
    return None


def _sentences(text):
    raw = _SENT_RE.split(text.strip())
    return [s.strip() for s in raw if s.strip()] or [text]


def _spacy_dates(text):
    if not SPACY_OK or nlp is None:
        return []
    try:
        doc = nlp(text[:5000])
        return [ent.text for ent in doc.ents if ent.label_ in ("DATE", "TIME")]
    except Exception:
        return []


def _find_dates(text):
    found = _spacy_dates(text)
    if not found:
        found = [m.group(0) for m in _DATE_RE.finditer(text)]
    seen, out = set(), []
    for d in found:
        key = d.lower().strip()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _context_window(sentences, idx, window=2):
    start = max(0, idx - window)
    end = min(len(sentences), idx + window + 1)
    return " ".join(sentences[start:end])


def _build_title(sentence, subject_line, typ, subtype, course, component):
    parts = []
    if subtype:
        parts.append(subtype.upper())
    elif typ not in ("other", "event", "meeting", "assignment", "deadline"):
        parts.append(typ.upper())
    if course:
        parts.append(course)
    if component:
        parts.append(f"[{component}]")
    base = subject_line.strip()[:80] if subject_line and len(subject_line.strip()) < 80 else sentence[:80]
    return f"{' — '.join(parts)}: {base}" if parts else base


def extract_events(subject: str, body: str, email_date: datetime = None,
                   user_courses: list = None) -> list[dict]:
    base = email_date or datetime.now()
    events = []
    seen_dates: set[str] = set()
    combined = f"{subject}\n{body}"
    sentences = _sentences(combined)

    for idx, sent in enumerate(sentences):
        if not has_keyword(sent):
            continue

        typ, subtype = classify(sent)
        if not subtype:
            _, subtype = classify(subject)
        course    = detect_subject(sent) or detect_subject(subject)
        component = detect_component(sent) or detect_component(subject)
        ctx       = _context_window(sentences, idx)

        # Confidence: if user gave their courses, mark unrecognised as unconfirmed
        confirmed = True
        if user_courses and course:
            # Check if course roughly matches any user course
            confirmed = any(
                course.upper() in uc.upper() or uc.upper() in course.upper()
                for uc in user_courses
            )
        elif user_courses and not course:
            # No course detected at all — needs review
            confirmed = False

        date_strings = _find_dates(ctx)
        if not date_strings:
            date_strings = _find_dates(combined[:3000])

        for ds in date_strings:
            parsed = parse_date(ds, base)
            if not parsed or parsed < datetime.now() - timedelta(days=1):
                continue

            date_key = parsed.strftime("%Y-%m-%d") + (subtype or typ) + subject[:30]
            if date_key in seen_dates:
                continue
            seen_dates.add(date_key)

            time_m  = _TIME_RE.search(ctx)
            eff_typ = subtype if subtype in ("quiz", "labtest") else typ

            events.append({
                "title":     _build_title(sent, subject, typ, subtype, course, component),
                "date":      parsed.strftime("%Y-%m-%d"),
                "time":      time_m.group(0).strip() if time_m else None,
                "type":      eff_typ,
                "subtype":   subtype,
                "subject":   course,
                "component": component,
                "description": ctx[:300].strip(),
                "priority":  PRIORITY.get(subtype or eff_typ, 1),
                "confirmed": confirmed,
            })

        if not date_strings and has_keyword(subject) and idx == 0:
            typ2, sub2 = classify(subject)
            course2    = detect_subject(subject)
            comp2      = detect_component(subject)
            key2 = "tbd" + (sub2 or typ2) + subject[:30]
            if key2 not in seen_dates:
                seen_dates.add(key2)
                for ds in _find_dates(body[:5000]):
                    parsed = parse_date(ds, base)
                    if parsed and parsed >= datetime.now() - timedelta(days=1):
                        time_m = _TIME_RE.search(body[:500])
                        eff2   = sub2 if sub2 in ("quiz", "labtest") else typ2
                        conf2  = True
                        if user_courses and course2:
                            conf2 = any(
                                course2.upper() in uc.upper() or uc.upper() in course2.upper()
                                for uc in user_courses
                            )
                        elif user_courses and not course2:
                            conf2 = False
                        events.append({
                            "title":     _build_title(sent, subject, typ2, sub2, course2, comp2),
                            "date":      parsed.strftime("%Y-%m-%d"),
                            "time":      time_m.group(0).strip() if time_m else None,
                            "type":      eff2,
                            "subtype":   sub2,
                            "subject":   course2,
                            "component": comp2,
                            "description": sent[:300].strip(),
                            "priority":  PRIORITY.get(sub2 or eff2, 1),
                            "confirmed": conf2,
                        })
                        break

    return events
