from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(256), unique=True, nullable=False)
    name          = db.Column(db.String(256))
    picture       = db.Column(db.String(512))
    access_token  = db.Column(db.Text)
    refresh_token = db.Column(db.Text)
    last_scan     = db.Column(db.DateTime)
    onboarded     = db.Column(db.Boolean, default=False)
    courses_json  = db.Column(db.Text, default="[]")  # JSON list of course codes
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    events        = db.relationship("Event", backref="user", lazy=True, cascade="all,delete")
    slots         = db.relationship("ScheduleSlot", backref="user", lazy=True, cascade="all,delete")

    @property
    def courses(self):
        """Returns list of dicts: [{code, components}] or plain strings (legacy)."""
        try:
            return json.loads(self.courses_json or "[]")
        except Exception:
            return []

    @courses.setter
    def courses(self, val):
        self.courses_json = json.dumps(val)

    @property
    def course_codes(self):
        """Returns just the code strings for quick matching."""
        result = []
        for c in self.courses:
            if isinstance(c, dict):
                result.append(c.get("code", ""))
            else:
                result.append(str(c))
        return [x for x in result if x]


class Event(db.Model):
    __tablename__ = "events"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title       = db.Column(db.String(256))
    date        = db.Column(db.String(16))    # YYYY-MM-DD
    time        = db.Column(db.String(16))    # HH:MM AM/PM or null
    type        = db.Column(db.String(32))    # exam/quiz/labtest/deadline/assignment/event/meeting
    subtype     = db.Column(db.String(32))    # midsem/endsem/compre/quiz/labtest
    subject     = db.Column(db.String(64))    # detected course/subject
    component   = db.Column(db.String(16))    # L1/P2/T3 etc.
    description = db.Column(db.Text)
    source      = db.Column(db.String(256))   # email subject
    source_url  = db.Column(db.String(512))   # Gmail link
    confirmed   = db.Column(db.Boolean, default=True)   # False = needs user review
    priority    = db.Column(db.Integer, default=1)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return dict(
            id=self.id, title=self.title, date=self.date, time=self.time,
            type=self.type, subtype=self.subtype, subject=self.subject,
            component=self.component, description=self.description,
            source=self.source, source_url=self.source_url,
            confirmed=self.confirmed, priority=self.priority
        )


class ScheduleSlot(db.Model):
    __tablename__ = "schedule_slots"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_id    = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"))
    date        = db.Column(db.String(16))
    start_time  = db.Column(db.String(8))
    end_time    = db.Column(db.String(8))
    label       = db.Column(db.String(256))
    slot_type   = db.Column(db.String(32))   # prep/review/buffer
    done        = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return dict(id=self.id, date=self.date, start_time=self.start_time,
                    end_time=self.end_time, label=self.label,
                    slot_type=self.slot_type, done=self.done, event_id=self.event_id)
