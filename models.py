from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import uuid

db = SQLAlchemy()


def new_uuid():
    return str(uuid.uuid4())


class RecurringBlock(db.Model):
    __tablename__ = "recurring_blocks"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    title = db.Column(db.String(200), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)   # "HH:MM"
    end_time = db.Column(db.String(5), nullable=False)     # "HH:MM"
    allowed_apps = db.Column(db.String(500), default="")
    recurrence_type = db.Column(db.String(10), nullable=False)  # daily, weekly, monthly
    days_of_week = db.Column(db.String(20), default="")    # "0,1,4" Mon=0 Sun=6 (weekly)
    day_of_month = db.Column(db.Integer, nullable=True)    # 1-31 (monthly)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def days_of_week_list(self):
        if not self.days_of_week:
            return []
        return [int(d) for d in self.days_of_week.split(",") if d.strip()]

    @property
    def days_label(self):
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        if self.recurrence_type == "daily":
            return "Every day"
        if self.recurrence_type == "monthly":
            return f"Monthly on day {self.day_of_month}"
        if self.recurrence_type == "weekly":
            return ", ".join(names[d] for d in sorted(self.days_of_week_list))
        return ""

    def occurs_on(self, d):
        """Return True if this recurring block should appear on date d."""
        if not self.active:
            return False
        if self.recurrence_type == "daily":
            return True
        if self.recurrence_type == "weekly":
            return d.weekday() in self.days_of_week_list
        if self.recurrence_type == "monthly":
            return self.day_of_month == d.day
        return False


class CalendarBlock(db.Model):
    __tablename__ = "calendar_blocks"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    title = db.Column(db.String(200), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    allowed_apps = db.Column(db.String(500), default="")  # comma-separated
    adherence_score = db.Column(db.Float, nullable=True)
    recurring_block_id = db.Column(db.String(36), db.ForeignKey("recurring_blocks.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    usage_logs = db.relationship("UsageLog", backref="block", lazy=True, cascade="all, delete-orphan")

    @property
    def duration_minutes(self):
        delta = self.ends_at - self.starts_at
        return max(delta.total_seconds() / 60, 1)

    @property
    def allowed_apps_list(self):
        if not self.allowed_apps:
            return []
        return [a.strip().lower() for a in self.allowed_apps.split(",") if a.strip()]

    def compute_adherence(self):
        if not self.usage_logs:
            return None
        total = sum(l.duration_seconds for l in self.usage_logs)
        if not self.allowed_apps_list:
            return 100.0
        on_task = sum(
            l.duration_seconds for l in self.usage_logs
            if any(token in l.app_or_url.lower() for token in self.allowed_apps_list)
        )
        if total == 0:
            return None
        return round((on_task / total) * 100, 1)

    @property
    def score_color(self):
        s = self.adherence_score
        if s is None:
            return "secondary"
        if s >= 70:
            return "success"
        if s >= 50:
            return "warning"
        return "danger"


class UsageLog(db.Model):
    __tablename__ = "usage_logs"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    calendar_block_id = db.Column(db.String(36), db.ForeignKey("calendar_blocks.id"), nullable=True)
    app_or_url = db.Column(db.String(500), nullable=False)
    active_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    duration_seconds = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class JournalEntry(db.Model):
    __tablename__ = "journal_entries"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    body = db.Column(db.Text, nullable=False)
    stress_level = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HealthRecord(db.Model):
    __tablename__ = "health_records"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    record_type = db.Column(db.String(50), nullable=False)  # gym_visit, vital, sleep, appointment
    source = db.Column(db.String(50), default="manual")
    value = db.Column(db.Text, default="{}")
    notes = db.Column(db.Text, default="")
    recorded_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Track(db.Model):
    __tablename__ = "tracks"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    title = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default="library")  # library, current, completed
    level = db.Column(db.Integer, default=1)
    calendar_block_id = db.Column(db.String(36), db.ForeignKey("calendar_blocks.id"), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    checkpoints = db.relationship("Checkpoint", backref="track", lazy=True, cascade="all, delete-orphan")
    goals = db.relationship("Goal", backref="track", lazy=True)
    calendar_block = db.relationship("CalendarBlock", backref="tracks")

    @property
    def completion_pct(self):
        if not self.checkpoints:
            return 0
        done = sum(1 for c in self.checkpoints if c.completed)
        return round((done / len(self.checkpoints)) * 100)


class Checkpoint(db.Model):
    __tablename__ = "checkpoints"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    track_id = db.Column(db.String(36), db.ForeignKey("tracks.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    target_date = db.Column(db.Date, nullable=True)
    completed = db.Column(db.Boolean, default=False)
    is_goal = db.Column(db.Boolean, default=False)  # True when equipped as a goal
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Goal(db.Model):
    __tablename__ = "goals"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    track_id = db.Column(db.String(36), db.ForeignKey("tracks.id"), nullable=True)
    checkpoint_id = db.Column(db.String(36), db.ForeignKey("checkpoints.id"), nullable=True)
    calendar_block_id = db.Column(db.String(36), db.ForeignKey("calendar_blocks.id"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="doing_next")  # doing_next, doing, done
    due_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    checkpoint = db.relationship("Checkpoint", backref="goal", foreign_keys=[checkpoint_id])
    calendar_block = db.relationship("CalendarBlock", backref="goals")


class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    merchant_name = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), default="Uncategorized")
    transacted_at = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AppSetting(db.Model):
    __tablename__ = "app_settings"
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.Text, default="")


class Bill(db.Model):
    __tablename__ = "bills"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    name = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    due_day = db.Column(db.Integer, nullable=True)   # day of month, 1–31
    category = db.Column(db.String(100), default="Bills")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Asset(db.Model):
    __tablename__ = "assets"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    name = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    asset_type = db.Column(db.String(50), default="checking")  # checking, savings, investment, property, other
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Debt(db.Model):
    __tablename__ = "debts"
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    name = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    debt_type = db.Column(db.String(50), default="credit_card")  # credit_card, loan, mortgage, other
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)