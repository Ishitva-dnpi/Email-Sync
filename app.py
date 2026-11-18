import os, json, base64, re
from datetime import datetime, timedelta
from flask import Flask, redirect, url_for, session, jsonify, request, render_template
from authlib.integrations.flask_client import OAuth
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from models import db, User, Event, ScheduleSlot
from parser import extract_events
from schedule import build_schedule

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET"]
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///mailmind.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db.init_app(app)

oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile https://www.googleapis.com/auth/gmail.readonly",
        "access_type": "offline",
        "prompt": "consent",
    },
)

with app.app_context():
    db.create_all()
    # Auto-migrate: add any missing columns without dropping data
    _migrate_cols = [
        ("users",  "onboarded",    "BOOLEAN DEFAULT FALSE"),
        ("users",  "courses_json", "TEXT DEFAULT '[]'"),
        ("events", "subtype",      "VARCHAR(32)"),
        ("events", "subject",      "VARCHAR(64)"),
        ("events", "component",    "VARCHAR(16)"),
        ("events", "source_url",   "VARCHAR(512)"),
        ("events", "confirmed",    "BOOLEAN DEFAULT TRUE"),
    ]
    with db.engine.connect() as _conn:
        for _tbl, _col, _typedef in _migrate_cols:
            try:
                _conn.execute(db.text(
                    f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_typedef}"
                ))
                _conn.commit()
            except Exception:
                _conn.rollback()  # column already exists — that's fine


# ── Helpers ───────────────────────────────────────────────────────────────

def current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None

def gmail_link(msg_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{msg_id}"

def _extract_body(payload):
    if payload.get("mimeType") == "text/plain":
        d = payload.get("body", {}).get("data", "")
        if d:
            return base64.urlsafe_b64decode(d).decode("utf-8", errors="ignore")[:3000]
    for part in payload.get("parts", []):
        r = _extract_body(part)
        if r:
            return r
    return ""


# ── Auth ──────────────────────────────────────────────────────────────────

@app.route("/login")
def login():
    redirect_uri = url_for("auth_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/callback")
def auth_callback():
    token = google.authorize_access_token()
    info  = token.get("userinfo") or google.userinfo()
    email = info["email"]

    user = User.query.filter_by(email=email).first()
    is_new = user is None
    if not user:
        user = User(email=email, name=info.get("name"), picture=info.get("picture"))
        db.session.add(user)

    user.access_token  = token.get("access_token")
    user.refresh_token = token.get("refresh_token") or user.refresh_token
    db.session.commit()

    session["user_id"] = user.id

    # First-time users go to onboarding
    if is_new or not user.onboarded:
        return redirect("/onboarding")
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ── Pages ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    uid = session.get("user_id")
    if not uid:
        return render_template("landing.html")
    user = User.query.get(uid)
    if not user:
        session.clear(); return redirect("/")
    if not user.onboarded:
        return redirect("/onboarding")
    return render_template("app.html", user=user)

@app.route("/onboarding", methods=["GET"])
def onboarding():
    user = current_user()
    if not user:
        return redirect("/")
    return render_template("onboarding.html", user=user)

@app.route("/onboarding/save", methods=["POST"])
def onboarding_save():
    user = current_user()
    if not user:
        return redirect("/")
    data = request.json or {}
    courses = [c.strip().upper() for c in data.get("courses", []) if c.strip()]
    user.courses    = courses
    user.onboarded  = True
    db.session.commit()
    return jsonify({"ok": True})


# ── API ───────────────────────────────────────────────────────────────────

@app.route("/api/scan", methods=["POST"])
def api_scan():
    user = current_user()
    if not user:
        return jsonify({"error": "Not logged in"}), 401

    days = int(request.json.get("days", 30))
    try:
        creds = Credentials(
            token=user.access_token, refresh_token=user.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"]
        )
        service = build("gmail", "v1", credentials=creds)
        results = service.users().messages().list(
            userId="me", maxResults=25, q=f"newer_than:{days}d"
        ).execute()
        msgs = results.get("messages", [])

        # Clear old events
        Event.query.filter_by(user_id=user.id).delete()

        all_events = []
        user_courses = user.courses  # list of {code, components} dicts (or legacy strings)

        for m in msgs[:20]:
            try:
                msg      = service.users().messages().get(
                    userId="me", id=m["id"], format="full"
                ).execute()
                payload  = msg.get("payload", {})
                headers  = payload.get("headers", [])
                subject  = next((h["value"] for h in headers if h["name"] == "Subject"), "")
                date_str = next((h["value"] for h in headers if h["name"] == "Date"), "")
                body     = _extract_body(payload)
                msg_link = gmail_link(m["id"])

                email_date = None
                try:
                    from email.utils import parsedate_to_datetime
                    email_date = parsedate_to_datetime(date_str).replace(tzinfo=None)
                except Exception:
                    pass

                for ev in extract_events(subject, body, email_date, user_courses):
                    db.session.add(Event(
                        user_id=user.id,
                        title=ev.get("title"),
                        date=ev.get("date"),
                        time=ev.get("time"),
                        type=ev.get("type"),
                        subtype=ev.get("subtype"),
                        subject=ev.get("subject"),
                        component=ev.get("component"),
                        description=ev.get("description"),
                        source=subject[:256],
                        source_url=msg_link,
                        confirmed=ev.get("confirmed", True),
                        priority=ev.get("priority", 1),
                    ))
                    all_events.append(ev)
            except Exception:
                continue

        user.access_token = creds.token
        user.last_scan    = datetime.utcnow()
        db.session.commit()

        build_schedule(user.id)

        confirmed   = sum(1 for e in all_events if e.get("confirmed", True))
        unconfirmed = len(all_events) - confirmed
        return jsonify({
            "scanned": len(msgs),
            "found": len(all_events),
            "confirmed": confirmed,
            "review": unconfirmed,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/events")
def api_events():
    user = current_user()
    if not user:
        return jsonify([])
    evs = Event.query.filter_by(user_id=user.id).filter(
        Event.date >= datetime.now().strftime("%Y-%m-%d")
    ).order_by(Event.priority.desc(), Event.date).all()
    return jsonify([e.to_dict() for e in evs])


@app.route("/api/event/<int:eid>/confirm", methods=["POST"])
def api_confirm_event(eid):
    user = current_user()
    if not user:
        return jsonify({}), 401
    ev = Event.query.filter_by(id=eid, user_id=user.id).first_or_404()
    data = request.json or {}
    ev.confirmed = data.get("confirmed", True)
    db.session.commit()
    if ev.confirmed:
        build_schedule(user.id)
    return jsonify(ev.to_dict())


@app.route("/api/calendar")
def api_calendar():
    user = current_user()
    if not user:
        return jsonify([])

    TYPE_COLOR = {
        "exam": "#ff6b6b", "quiz": "#ff9f43", "labtest": "#ee5a24",
        "deadline": "#ffa559", "assignment": "#ffd43b",
        "meeting": "#69db7c", "event": "#74c0fc", "other": "#a78bfa",
    }
    SUBTYPE_COLOR = {
        "compre": "#c0392b", "endsem": "#c0392b", "midsem": "#e74c3c",
    }
    SLOT_COLOR = {"prep": "#6c63ff88", "review": "#a78bfa88"}

    items = []

    for ev in Event.query.filter_by(user_id=user.id, confirmed=True).all():
        color = SUBTYPE_COLOR.get(ev.subtype or "", TYPE_COLOR.get(ev.type, "#a78bfa"))
        label_parts = []
        if ev.subtype:
            label_parts.append(ev.subtype.upper())
        if ev.subject:
            label_parts.append(ev.subject)
        if ev.component:
            label_parts.append(f"[{ev.component}]")
        display = f"{' '.join(label_parts)}: {ev.title}" if label_parts else ev.title
        item = {
            "id": f"ev{ev.id}",
            "title": display[:60],
            "start": ev.date,
            "backgroundColor": color,
            "extendedProps": {
                "kind": "event",
                "description": ev.description,
                "source_url": ev.source_url,
                "type": ev.type,
                "subtype": ev.subtype,
            },
        }
        if ev.time:
            item["start"] = f"{ev.date}T{_to_24h(ev.time)}"
        items.append(item)

    for slot in ScheduleSlot.query.filter_by(user_id=user.id).all():
        items.append({
            "id": f"sl{slot.id}",
            "title": ("✓ " if slot.done else "") + slot.label[:40],
            "start": f"{slot.date}T{slot.start_time}:00",
            "end":   f"{slot.date}T{slot.end_time}:00",
            "backgroundColor": SLOT_COLOR.get(slot.slot_type, "#6c63ff55"),
            "extendedProps": {"kind": "slot", "slot_id": slot.id},
        })

    return jsonify(items)


def _to_24h(time_str: str) -> str:
    """Convert '2:00 PM' to '14:00'."""
    try:
        t = datetime.strptime(time_str.strip(), "%I:%M %p")
        return t.strftime("%H:%M")
    except Exception:
        pass
    try:
        t = datetime.strptime(time_str.strip(), "%I %p")
        return t.strftime("%H:%M")
    except Exception:
        pass
    return "09:00"


@app.route("/api/schedule")
def api_schedule():
    user = current_user()
    if not user:
        return jsonify([])
    slots = ScheduleSlot.query.filter_by(user_id=user.id).filter(
        ScheduleSlot.date >= datetime.now().strftime("%Y-%m-%d")
    ).order_by(ScheduleSlot.date, ScheduleSlot.start_time).all()
    return jsonify([s.to_dict() for s in slots])


@app.route("/api/slot/<int:sid>/done", methods=["POST"])
def api_slot_done(sid):
    user = current_user()
    if not user:
        return jsonify({}), 401
    slot = ScheduleSlot.query.filter_by(id=sid, user_id=user.id).first_or_404()
    slot.done = not slot.done
    db.session.commit()
    return jsonify({"done": slot.done})


@app.route("/api/reschedule", methods=["POST"])
def api_reschedule():
    user = current_user()
    if not user:
        return jsonify({}), 401
    build_schedule(user.id)
    return jsonify({"ok": True})


@app.route("/api/event/<int:eid>/dismiss", methods=["POST"])
def api_dismiss_event(eid):
    user = current_user()
    if not user:
        return jsonify({}), 401
    ev = Event.query.filter_by(id=eid, user_id=user.id).first_or_404()
    db.session.delete(ev)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/courses", methods=["GET"])
def api_get_courses():
    user = current_user()
    if not user:
        return jsonify({"courses": []})
    # Normalise legacy plain-string entries for the UI
    courses = []
    for c in user.courses:
        if isinstance(c, dict):
            courses.append(c)
        else:
            courses.append({"code": str(c), "components": ["L","P","T"]})
    return jsonify({"courses": courses})


@app.route("/api/courses", methods=["POST"])
def api_set_courses():
    user = current_user()
    if not user:
        return jsonify({}), 401
    data = request.json or {}
    courses = [c.strip().upper() for c in data.get("courses", []) if c.strip()]
    user.courses = courses
    db.session.commit()
    return jsonify({"ok": True, "courses": user.courses})
