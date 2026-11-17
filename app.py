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
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("PRODUCTION", "0") == "1"
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


# ── Auth ──────────────────────────────────────────────────────────────────────

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
    if not user:
        user = User(email=email, name=info.get("name"), picture=info.get("picture"))
        db.session.add(user)

    user.access_token  = token.get("access_token")
    user.refresh_token = token.get("refresh_token") or user.refresh_token
    db.session.commit()

    session["user_id"] = user.id
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    uid = session.get("user_id")
    if not uid:
        return render_template("landing.html")
    user = User.query.get(uid)
    if not user:
        session.clear(); return redirect("/")
    return render_template("app.html", user=user)


# ── API ───────────────────────────────────────────────────────────────────────

def current_user():
    uid = session.get("user_id")
    return User.query.get(uid) if uid else None

@app.route("/api/scan", methods=["POST"])
def api_scan():
    user = current_user()
    if not user: return jsonify({"error": "Not logged in"}), 401

    days = int(request.json.get("days", 30))
    try:
        creds = Credentials(token=user.access_token, refresh_token=user.refresh_token,
                            token_uri="https://oauth2.googleapis.com/token",
                            client_id=os.environ["GOOGLE_CLIENT_ID"],
                            client_secret=os.environ["GOOGLE_CLIENT_SECRET"])
        service = build("gmail", "v1", credentials=creds)
        results = service.users().messages().list(
            userId="me", maxResults=60, q=f"newer_than:{days}d"
        ).execute()
        msgs = results.get("messages", [])

        # Clear old events
        Event.query.filter_by(user_id=user.id).delete()

        all_events = []
        for m in msgs[:40]:
            try:
                msg     = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
                payload = msg.get("payload", {})
                subject = next((h["value"] for h in payload.get("headers",[]) if h["name"]=="Subject"), "")
                date_str= next((h["value"] for h in payload.get("headers",[]) if h["name"]=="Date"), "")
                body    = _extract_body(payload)
                email_date = None
                try:
                    from email.utils import parsedate_to_datetime
                    email_date = parsedate_to_datetime(date_str).replace(tzinfo=None)
                except Exception: pass
                for ev in extract_events(subject, body, email_date):
                    db.session.add(Event(user_id=user.id, **ev))
                    all_events.append(ev)
            except Exception: continue

        user.access_token = creds.token
        user.last_scan    = datetime.utcnow()
        db.session.commit()

        # Rebuild schedule
        build_schedule(user.id)

        return jsonify({"scanned": len(msgs), "found": len(all_events)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _extract_body(payload):
    if payload.get("mimeType") == "text/plain":
        d = payload.get("body", {}).get("data", "")
        if d: return base64.urlsafe_b64decode(d).decode("utf-8", errors="ignore")[:3000]
    for part in payload.get("parts", []):
        r = _extract_body(part)
        if r: return r
    return ""

@app.route("/api/events")
def api_events():
    user = current_user()
    if not user: return jsonify([])
    evs = Event.query.filter_by(user_id=user.id).filter(
        Event.date >= datetime.now().strftime("%Y-%m-%d")
    ).order_by(Event.date).all()
    return jsonify([e.to_dict() for e in evs])

@app.route("/api/calendar")
def api_calendar():
    """FullCalendar-compatible event feed."""
    user = current_user()
    if not user: return jsonify([])

    TYPE_COLOR = {
        "exam": "#ff6b6b", "deadline": "#ffa559", "assignment": "#ffd43b",
        "meeting": "#69db7c", "event": "#74c0fc", "other": "#a78bfa",
    }
    SLOT_COLOR = {"prep": "#6c63ff88", "review": "#a78bfa88"}

    items = []

    # Real events
    for ev in Event.query.filter_by(user_id=user.id).all():
        items.append({
            "id": f"ev-{ev.id}",
            "title": ev.title,
            "start": ev.date,
            "color": TYPE_COLOR.get(ev.type, "#a78bfa"),
            "extendedProps": {"type": ev.type, "description": ev.description, "kind": "event"},
        })

    # Schedule slots
    for sl in ScheduleSlot.query.filter_by(user_id=user.id).all():
        items.append({
            "id": f"sl-{sl.id}",
            "title": ("✓ " if sl.done else "") + sl.label,
            "start": f"{sl.date}T{sl.start_time}",
            "end":   f"{sl.date}T{sl.end_time}",
            "color": SLOT_COLOR.get(sl.slot_type, "#6c63ff55"),
            "extendedProps": {"kind": "slot", "slot_id": sl.id, "done": sl.done},
        })

    return jsonify(items)

@app.route("/api/schedule")
def api_schedule():
    user = current_user()
    if not user: return jsonify([])
    slots = ScheduleSlot.query.filter_by(user_id=user.id).filter(
        ScheduleSlot.date >= datetime.now().strftime("%Y-%m-%d")
    ).order_by(ScheduleSlot.date, ScheduleSlot.start_time).all()
    return jsonify([s.to_dict() for s in slots])

@app.route("/api/slot/<int:slot_id>/done", methods=["POST"])
def mark_done(slot_id):
    user = current_user()
    if not user: return jsonify({"error": "Not logged in"}), 401
    slot = ScheduleSlot.query.filter_by(id=slot_id, user_id=user.id).first()
    if not slot: return jsonify({"error": "Not found"}), 404
    slot.done = not slot.done
    db.session.commit()
    return jsonify({"done": slot.done})

@app.route("/api/reschedule", methods=["POST"])
def reschedule():
    user = current_user()
    if not user: return jsonify({"error": "Not logged in"}), 401
    build_schedule(user.id)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True)
