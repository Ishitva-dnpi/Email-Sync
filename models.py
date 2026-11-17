from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

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
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    events        = db.relationship("Event", backref="user", lazy=True, cascade="all,delete")
    slots         = db.relationship("ScheduleSlot", backref="user", lazy=True, cascade="all,delete")

class Event(db.Model):
    __tablename__ = "events"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title       = db.Column(db.String(256))
    date        = db.Column(db.String(16))   # YYYY-MM-DD
    time        = db.Column(db.String(16))   # HH:MM AM/PM or null
    type        = db.Column(db.String(32))   # exam/deadline/assignment/event/meeting
    description = db.Column(db.Text)
    source      = db.Column(db.String(256))
    priority    = db.Column(db.Integer, default=1)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return dict(id=self.id, title=self.title, date=self.date,
                    time=self.time, type=self.type,
                    description=self.description, source=self.source,
                    priority=self.priority)

class ScheduleSlot(db.Model):
    __tablename__ = "schedule_slots"
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_id    = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"))
    date        = db.Column(db.String(16))
    start_time  = db.Column(db.String(8))   # HH:MM
    end_time    = db.Column(db.String(8))
    label       = db.Column(db.String(256))
    slot_type   = db.Column(db.String(32))  # prep/review/buffer
    done        = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return dict(id=self.id, date=self.date, start_time=self.start_time,
                    end_time=self.end_time, label=self.label,
                    slot_type=self.slot_type, done=self.done, event_id=self.event_id)
