from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response
from models import db, CalendarBlock, UsageLog, JournalEntry, HealthRecord, Track, Checkpoint, Goal, Transaction, AppSetting, Bill, RecurringBlock, Asset, Debt
from datetime import datetime, date, timedelta
from collections import defaultdict
import os
import csv
import io
from dotenv import load_dotenv
from sqlalchemy import text
import calendar as cal_lib

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///focus.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()
    # Migrate: add new columns if they don't exist yet
    with db.engine.connect() as _conn:
        migrations = [
            ("ALTER TABLE goals ADD COLUMN description TEXT DEFAULT ''", "goals description"),
            ("ALTER TABLE checkpoints ADD COLUMN is_goal BOOLEAN DEFAULT 0", "checkpoints is_goal"),
            ("ALTER TABLE tracks ADD COLUMN calendar_block_id VARCHAR(36)", "tracks calendar_block_id"),
            ("ALTER TABLE goals ADD COLUMN checkpoint_id VARCHAR(36)", "goals checkpoint_id"),
            ("ALTER TABLE goals ADD COLUMN calendar_block_id VARCHAR(36)", "goals calendar_block_id"),
        ]
        for migration_sql, name in migrations:
            try:
                _conn.execute(text(migration_sql))
                _conn.commit()
            except Exception:
                pass  # column already exists


# ─── Helpers ────────────────────────────────────────────────────────────────

def week_bounds(anchor=None):
    """Return (monday, sunday) for the week containing anchor (default today)."""
    if anchor is None:
        anchor = date.today()
    monday = anchor - timedelta(days=anchor.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def gym_streak():
    today = date.today()
    streak = 0
    check = today
    while True:
        has = HealthRecord.query.filter(
            HealthRecord.record_type == "gym_visit",
            db.func.date(HealthRecord.recorded_at) == check
        ).first()
        if has:
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    return streak


# ─── Dashboard ───────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    today = date.today()
    today_blocks = CalendarBlock.query.filter(
        db.func.date(CalendarBlock.starts_at) == today
    ).order_by(CalendarBlock.starts_at).all()

    last_entry = JournalEntry.query.order_by(JournalEntry.created_at.desc()).first()
    current_tracks = Track.query.filter_by(status="current").all()
    streak = gym_streak()
    total_goals_done = Goal.query.filter_by(status="done").count()

    return render_template("dashboard.html",
        today_blocks=today_blocks,
        last_entry=last_entry,
        current_tracks=current_tracks,
        streak=streak,
        total_goals_done=total_goals_done,
        today=today
    )


# ─── Calendar ────────────────────────────────────────────────────────────────

PX_PER_HOUR = 48
TOTAL_HEIGHT = PX_PER_HOUR * 24


def materialize_recurring(days):
    """For each day, create CalendarBlock rows for any RecurringBlock that should appear
    and hasn't been materialized yet. Skips if a block already exists for that day+recurring combo."""
    recurring = RecurringBlock.query.filter_by(active=True).all()
    for r in recurring:
        for d in days:
            if not r.occurs_on(d):
                continue
            existing = CalendarBlock.query.filter_by(
                recurring_block_id=r.id
            ).filter(db.func.date(CalendarBlock.starts_at) == d).first()
            if existing:
                continue
            starts_at = datetime.combine(d, datetime.strptime(r.start_time, "%H:%M").time())
            ends_at = datetime.combine(d, datetime.strptime(r.end_time, "%H:%M").time())
            block = CalendarBlock(
                title=r.title,
                starts_at=starts_at,
                ends_at=ends_at,
                allowed_apps=r.allowed_apps,
                recurring_block_id=r.id
            )
            db.session.add(block)
    db.session.commit()


def block_position(block):
    """Return CSS top and height in pixels for a calendar block."""
    start_min = block.starts_at.hour * 60 + block.starts_at.minute
    top = int(start_min * PX_PER_HOUR / 60)
    height = max(int(block.duration_minutes * PX_PER_HOUR / 60), 24)
    return top, height


@app.route("/calendar")
def calendar_index():
    day_str = request.args.get("day")
    if day_str:
        try:
            anchor = date.fromisoformat(day_str)
        except ValueError:
            anchor = date.today()
    else:
        anchor = date.today()

    days = [anchor, anchor + timedelta(days=1)]
    materialize_recurring(days)

    blocks = CalendarBlock.query.filter(
        db.func.date(CalendarBlock.starts_at) >= days[0],
        db.func.date(CalendarBlock.starts_at) <= days[1]
    ).order_by(CalendarBlock.starts_at).all()

    blocks_by_day = defaultdict(list)
    for b in blocks:
        top, height = block_position(b)
        blocks_by_day[b.starts_at.date()].append({
            "block": b, "top": top, "height": height
        })

    prev_day = (anchor - timedelta(days=2)).isoformat()
    next_day = (anchor + timedelta(days=2)).isoformat()
    today_day = date.today().isoformat()

    return render_template("calendar/index.html",
        days=days,
        blocks_by_day=blocks_by_day,
        prev_day=prev_day,
        next_day=next_day,
        today_day=today_day,
        hours=range(24),
        total_height=TOTAL_HEIGHT,
        px_per_hour=PX_PER_HOUR,
        anchor=anchor
    )


@app.route("/calendar/blocks", methods=["POST"])
def create_block():
    title = request.form["title"]
    starts_at = datetime.fromisoformat(request.form["starts_at"])
    ends_at = datetime.fromisoformat(request.form["ends_at"])
    allowed_apps = request.form.get("allowed_apps", "")
    block = CalendarBlock(title=title, starts_at=starts_at, ends_at=ends_at, allowed_apps=allowed_apps)
    db.session.add(block)
    db.session.commit()
    flash("Block created.", "success")
    return redirect(url_for("calendar_index", day=starts_at.date().isoformat()))


@app.route("/calendar/blocks/<id>")
def block_detail(id):
    block = CalendarBlock.query.get_or_404(id)
    return render_template("calendar/block.html", block=block)


@app.route("/calendar/blocks/<id>/edit", methods=["POST"])
def edit_block(id):
    block = CalendarBlock.query.get_or_404(id)
    block.title = request.form["title"]
    block.starts_at = datetime.fromisoformat(request.form["starts_at"])
    block.ends_at = datetime.fromisoformat(request.form["ends_at"])
    block.allowed_apps = request.form.get("allowed_apps", "")
    db.session.commit()
    flash("Block updated.", "success")
    return redirect(url_for("block_detail", id=id))


@app.route("/calendar/blocks/<id>/log", methods=["POST"])
def log_activity(id):
    block = CalendarBlock.query.get_or_404(id)
    app_or_url = request.form["app_or_url"]
    duration_minutes = int(request.form.get("duration_minutes", 0))
    log = UsageLog(
        calendar_block_id=id,
        app_or_url=app_or_url,
        active_at=datetime.utcnow(),
        duration_seconds=duration_minutes * 60
    )
    db.session.add(log)
    db.session.flush()
    block.adherence_score = block.compute_adherence()
    db.session.commit()
    flash("Activity logged.", "success")
    return redirect(url_for("block_detail", id=id))


@app.route("/calendar/blocks/<id>/delete", methods=["POST"])
def delete_block(id):
    block = CalendarBlock.query.get_or_404(id)
    day = block.starts_at.date().isoformat()
    db.session.delete(block)
    db.session.commit()
    flash("Block deleted.", "info")
    return redirect(url_for("calendar_index", day=day))


# ─── Recurring blocks ─────────────────────────────────────────────────────────

@app.route("/calendar/recurring")
def recurring_index():
    recurring = RecurringBlock.query.order_by(RecurringBlock.created_at.desc()).all()
    return render_template("calendar/recurring.html", recurring=recurring)


@app.route("/calendar/recurring", methods=["POST"])
def create_recurring():
    title = request.form["title"].strip()
    start_time = request.form["start_time"]
    end_time = request.form["end_time"]
    allowed_apps = request.form.get("allowed_apps", "")
    recurrence_type = request.form["recurrence_type"]

    days_of_week = ""
    day_of_month = None

    if recurrence_type == "weekly":
        selected = request.form.getlist("days_of_week")  # list of "0".."6"
        days_of_week = ",".join(selected)
    elif recurrence_type == "daily":
        days_of_week = "0,1,2,3,4,5,6"
    elif recurrence_type == "monthly":
        day_of_month = int(request.form.get("day_of_month", 1))

    r = RecurringBlock(
        title=title, start_time=start_time, end_time=end_time,
        allowed_apps=allowed_apps, recurrence_type=recurrence_type,
        days_of_week=days_of_week, day_of_month=day_of_month
    )
    db.session.add(r)
    db.session.commit()
    flash(f"Recurring block '{title}' created.", "success")
    return redirect(url_for("recurring_index"))


@app.route("/calendar/recurring/<id>/toggle", methods=["POST"])
def toggle_recurring(id):
    r = RecurringBlock.query.get_or_404(id)
    r.active = not r.active
    db.session.commit()
    flash(f"'{r.title}' {'activated' if r.active else 'paused'}.", "success")
    return redirect(url_for("recurring_index"))


@app.route("/calendar/recurring/<id>/delete", methods=["POST"])
def delete_recurring(id):
    r = RecurringBlock.query.get_or_404(id)
    # Also remove all future materialized blocks that have no usage logs
    CalendarBlock.query.filter_by(recurring_block_id=id).filter(
        ~CalendarBlock.usage_logs.any()
    ).delete(synchronize_session=False)
    db.session.delete(r)
    db.session.commit()
    flash("Recurring block deleted.", "info")
    return redirect(url_for("recurring_index"))


# ─── Journal ─────────────────────────────────────────────────────────────────

JOURNAL_PASSWORD = os.getenv("JOURNAL_PASSWORD", "focus")

SENTENCE_STEMS = [
    "I am proud of...",
    "Today I achieved...",
    "It's OK to...",
    "I am grateful for...",
    "One thing I want to improve is...",
    "Right now I feel...",
]


def journal_authed():
    return session.get("journal_auth") is True


@app.route("/journal", methods=["GET", "POST"])
def journal_index():
    if request.method == "POST":
        if not journal_authed():
            # Password gate
            if request.form.get("password") == JOURNAL_PASSWORD:
                session["journal_auth"] = True
            else:
                flash("Incorrect password.", "danger")
            return redirect(url_for("journal_index"))
        else:
            # Create entry
            body = request.form.get("body", "").strip()
            stress = request.form.get("stress_level")
            if not body:
                flash("Entry cannot be empty.", "danger")
                return redirect(url_for("journal_index"))
            entry = JournalEntry(body=body, stress_level=int(stress) if stress else None)
            db.session.add(entry)
            db.session.commit()
            flash("Entry saved.", "success")
            return redirect(url_for("journal_index"))

    if not journal_authed():
        return render_template("journal/gate.html")

    q = request.args.get("q", "").strip()
    filter_date = request.args.get("date", "").strip()
    month_str = request.args.get("month", "").strip()

    # Validate filter_date
    if filter_date:
        try:
            date.fromisoformat(filter_date)
        except ValueError:
            filter_date = ""

    entries = JournalEntry.query.order_by(JournalEntry.created_at.desc())
    if q:
        entries = entries.filter(JournalEntry.body.ilike(f"%{q}%"))
    if filter_date:
        entries = entries.filter(
            db.func.date(JournalEntry.created_at) == date.fromisoformat(filter_date)
        )
    entries = entries.all()

    # ── Build calendar data when a date or month is active ──────────
    cal_data = None
    cal_month_date = None
    if filter_date:
        cal_month_date = date.fromisoformat(filter_date).replace(day=1)
    elif month_str:
        try:
            cal_month_date = date.fromisoformat(month_str + "-01")
        except ValueError:
            pass

    if cal_month_date:
        days_in_month = cal_lib.monthrange(cal_month_date.year, cal_month_date.month)[1]
        first_weekday = cal_month_date.weekday()  # 0 = Monday

        prev_m = (cal_month_date.replace(day=1) - timedelta(days=1)).replace(day=1)
        next_m_day = (cal_month_date.replace(day=28) + timedelta(days=4)).replace(day=1)

        # Dates that have at least one entry this month (for dot indicators)
        month_fmt = cal_month_date.strftime("%Y-%m")
        month_entries = JournalEntry.query.filter(
            db.func.strftime("%Y-%m", JournalEntry.created_at) == month_fmt
        ).all()
        entry_dates = {e.created_at.date().isoformat() for e in month_entries}

        # Pre-build (day_number, iso_string) list so template doesn't format dates
        days_list = [
            (d, date(cal_month_date.year, cal_month_date.month, d).isoformat())
            for d in range(1, days_in_month + 1)
        ]

        cal_data = {
            "month_date": cal_month_date,
            "display": cal_month_date.strftime("%B %Y"),
            "prev_month": prev_m.strftime("%Y-%m"),
            "next_month": next_m_day.strftime("%Y-%m"),
            "first_weekday": first_weekday,
            "days_list": days_list,
            "entry_dates": entry_dates,
        }

    return render_template("journal/index.html",
        entries=entries, stems=SENTENCE_STEMS, q=q,
        filter_date=filter_date, cal_data=cal_data
    )


@app.route("/journal/<id>/edit", methods=["GET", "POST"])
def edit_entry(id):
    if not journal_authed():
        return redirect(url_for("journal_index"))
    entry = JournalEntry.query.get_or_404(id)
    if request.method == "POST":
        entry.body = request.form["body"].strip()
        stress = request.form.get("stress_level")
        entry.stress_level = int(stress) if stress else None
        entry.updated_at = datetime.utcnow()
        db.session.commit()
        flash("Entry updated.", "success")
        return redirect(url_for("journal_index"))
    return render_template("journal/edit.html", entry=entry, stems=SENTENCE_STEMS)


@app.route("/journal/<id>/delete", methods=["POST"])
def delete_entry(id):
    if not journal_authed():
        return redirect(url_for("journal_index"))
    entry = JournalEntry.query.get_or_404(id)
    db.session.delete(entry)
    db.session.commit()
    flash("Entry deleted.", "info")
    return redirect(url_for("journal_index"))


# ─── Health ──────────────────────────────────────────────────────────────────

RECORD_TYPES = ["gym_visit", "vital", "sleep", "appointment"]
APPOINTMENT_TYPES = ["optometrist", "general_practitioner", "dentist", "dermatologist"]


@app.route("/health")
def health_index():
    filter_type = request.args.get("type", "")
    records = HealthRecord.query
    if filter_type:
        records = records.filter_by(record_type=filter_type)
    records = records.order_by(HealthRecord.recorded_at.desc()).all()

    streak = gym_streak()

    # Appointment flags: flag if no record of that subtype in 12 months
    overdue = []
    cutoff = datetime.utcnow() - timedelta(days=365)
    for apt_type in APPOINTMENT_TYPES:
        last = HealthRecord.query.filter(
            HealthRecord.record_type == "appointment",
            HealthRecord.notes.ilike(f"%{apt_type}%")
        ).order_by(HealthRecord.recorded_at.desc()).first()
        if not last or last.recorded_at < cutoff:
            overdue.append(apt_type.replace("_", " ").title())

    return render_template("health/index.html",
        records=records, streak=streak, overdue=overdue,
        record_types=RECORD_TYPES, filter_type=filter_type
    )


@app.route("/health", methods=["POST"])
def create_health_record():
    record_type = request.form["record_type"]
    value = request.form.get("value", "")
    notes = request.form.get("notes", "")
    recorded_at = datetime.fromisoformat(request.form["recorded_at"])
    record = HealthRecord(record_type=record_type, value=value, notes=notes, recorded_at=recorded_at)
    db.session.add(record)
    db.session.commit()
    flash("Health record added.", "success")
    return redirect(url_for("health_index"))


@app.route("/health/<id>/delete", methods=["POST"])
def delete_health_record(id):
    record = HealthRecord.query.get_or_404(id)
    db.session.delete(record)
    db.session.commit()
    flash("Record deleted.", "info")
    return redirect(url_for("health_index"))


# ─── Finance ─────────────────────────────────────────────────────────────────

@app.route("/finance")
def finance_index():
    transactions = Transaction.query.order_by(Transaction.transacted_at.desc()).all()
    bills = Bill.query.order_by(Bill.due_day).all()
    assets = Asset.query.order_by(Asset.asset_type, Asset.name).all()
    debts = Debt.query.order_by(Debt.debt_type, Debt.name).all()

    today = date.today()
    this_month = [t for t in transactions if t.transacted_at.month == today.month and t.transacted_at.year == today.year]
    last_month_date = (today.replace(day=1) - timedelta(days=1))
    last_month = [t for t in transactions if t.transacted_at.month == last_month_date.month and t.transacted_at.year == last_month_date.year]

    this_total = sum(t.amount for t in this_month)
    last_total = sum(t.amount for t in last_month)
    bills_total = sum(b.amount for b in bills)

    # Income
    income_setting = AppSetting.query.get("monthly_income")
    monthly_income = float(income_setting.value) if income_setting and income_setting.value else 0.0
    remaining = monthly_income - bills_total - this_total

    # Net worth
    total_assets = sum(a.amount for a in assets)
    total_debt = sum(d.amount for d in debts)
    net_worth = total_assets - total_debt

    # Projected end-of-month net worth
    import calendar as cal_mod
    days_in_month = cal_mod.monthrange(today.year, today.month)[1]
    days_elapsed = today.day
    days_remaining = days_in_month - days_elapsed
    avg_daily_spend = (this_total / days_elapsed) if days_elapsed > 0 else 0
    projected_spend_remaining = avg_daily_spend * days_remaining
    projected_net_worth = net_worth + monthly_income - bills_total - this_total - projected_spend_remaining

    # Category breakdown
    cat_totals = defaultdict(float)
    for t in this_month:
        cat_totals[t.category] += t.amount
    cat_pcts = {}
    if this_total > 0:
        cat_pcts = {k: round((v / this_total) * 100, 1) for k, v in sorted(cat_totals.items(), key=lambda x: -x[1])}

    # Alerts
    alerts = []
    for cat, pct in cat_pcts.items():
        if pct > 20:
            alerts.append(f"{cat} is {pct}% of this month's spending.")
    if last_total > 0 and this_total > last_total:
        alerts.append(f"You've spent ${this_total - last_total:.2f} more this month than last month.")
    if monthly_income > 0 and remaining < 0:
        alerts.append(f"You are ${abs(remaining):.2f} over budget this month.")
    if monthly_income > 0 and bills_total > monthly_income:
        alerts.append(f"Your bills alone (${bills_total:.2f}) exceed your monthly income.")
    if net_worth < 0:
        alerts.append(f"Your net worth is negative (${net_worth:.2f}). Total debt exceeds total assets.")

    savings_note = AppSetting.query.get("savings_note")
    savings_text = savings_note.value if savings_note else ""

    return render_template("finance/index.html",
        transactions=transactions, bills=bills,
        assets=assets, debts=debts,
        this_total=this_total, last_total=last_total, bills_total=bills_total,
        monthly_income=monthly_income, remaining=remaining,
        total_assets=total_assets, total_debt=total_debt,
        net_worth=net_worth, projected_net_worth=projected_net_worth,
        days_remaining=days_remaining,
        cat_pcts=cat_pcts, alerts=alerts, savings_text=savings_text
    )


@app.route("/finance", methods=["POST"])
def create_transaction():
    merchant = request.form["merchant_name"]
    amount = float(request.form["amount"])
    category = request.form.get("category", "Uncategorized")
    transacted_at = date.fromisoformat(request.form["transacted_at"])
    notes = request.form.get("notes", "")
    t = Transaction(merchant_name=merchant, amount=amount, category=category,
                    transacted_at=transacted_at, notes=notes)
    db.session.add(t)
    db.session.commit()
    flash("Transaction added.", "success")
    if transacted_at > date.today():
        flash(f"Note: '{merchant}' is dated in the future ({transacted_at}). Intentional? It won't appear in this month's totals until then.", "warning")
    return redirect(url_for("finance_index"))


@app.route("/finance/import", methods=["POST"])
def import_transactions():
    f = request.files.get("csv_file")
    if not f:
        flash("No file uploaded.", "danger")
        return redirect(url_for("finance_index"))
    stream = io.StringIO(f.stream.read().decode("utf-8"))
    reader = csv.DictReader(stream)
    count = 0
    skipped = 0
    future_count = 0
    today = date.today()
    for row in reader:
        try:
            raw_date = row.get("transacted_at", "").strip()
            if not raw_date:
                skipped += 1
                continue
            transacted_at = date.fromisoformat(raw_date)
            t = Transaction(
                merchant_name=row.get("merchant_name", "Unknown"),
                amount=float(row.get("amount", 0)),
                category=row.get("category", "Uncategorized"),
                transacted_at=transacted_at,
                notes=row.get("notes", "")
            )
            db.session.add(t)
            count += 1
            if transacted_at > today:
                future_count += 1
        except Exception:
            skipped += 1
            continue
    db.session.commit()
    flash(f"Imported {count} transaction{'s' if count != 1 else ''}.", "success")
    if future_count:
        flash(f"{future_count} row{'s' if future_count != 1 else ''} dated in the future — logged as planned.", "warning")
    if skipped:
        flash(f"{skipped} row{'s' if skipped != 1 else ''} skipped (missing or invalid date).", "warning")
    return redirect(url_for("finance_index"))


@app.route("/finance/savings", methods=["POST"])
def save_savings_note():
    text = request.form.get("savings_text", "")
    note = AppSetting.query.get("savings_note")
    if note:
        note.value = text
    else:
        db.session.add(AppSetting(key="savings_note", value=text))
    db.session.commit()
    flash("Savings note saved.", "success")
    return redirect(url_for("finance_index"))


@app.route("/finance/<id>/delete", methods=["POST"])
def delete_transaction(id):
    t = Transaction.query.get_or_404(id)
    db.session.delete(t)
    db.session.commit()
    flash("Transaction deleted.", "info")
    return redirect(url_for("finance_index"))


@app.route("/finance/income", methods=["POST"])
def set_income():
    amount = request.form.get("monthly_income", "0").strip()
    setting = AppSetting.query.get("monthly_income")
    if setting:
        setting.value = amount
    else:
        db.session.add(AppSetting(key="monthly_income", value=amount))
    db.session.commit()
    flash("Income updated.", "success")
    return redirect(url_for("finance_index"))


@app.route("/finance/bills", methods=["POST"])
def create_bill():
    name = request.form["name"].strip()
    amount = float(request.form["amount"])
    due_day = request.form.get("due_day", "").strip()
    category = request.form.get("category", "Bills").strip() or "Bills"
    notes = request.form.get("notes", "")
    bill = Bill(
        name=name, amount=amount,
        due_day=int(due_day) if due_day else None,
        category=category, notes=notes
    )
    db.session.add(bill)
    db.session.commit()
    flash(f"Bill '{name}' added.", "success")
    return redirect(url_for("finance_index"))


@app.route("/finance/bills/<id>/delete", methods=["POST"])
def delete_bill(id):
    bill = Bill.query.get_or_404(id)
    db.session.delete(bill)
    db.session.commit()
    flash("Bill removed.", "info")
    return redirect(url_for("finance_index"))


@app.route("/finance/assets", methods=["POST"])
def create_asset():
    asset = Asset(
        name=request.form["name"].strip(),
        amount=float(request.form["amount"]),
        asset_type=request.form.get("asset_type", "checking"),
        notes=request.form.get("notes", "")
    )
    db.session.add(asset)
    db.session.commit()
    flash(f"Asset '{asset.name}' added.", "success")
    return redirect(url_for("finance_index"))


@app.route("/finance/assets/<id>/edit", methods=["POST"])
def edit_asset(id):
    asset = Asset.query.get_or_404(id)
    asset.name = request.form["name"].strip()
    asset.amount = float(request.form["amount"])
    asset.asset_type = request.form.get("asset_type", "checking")
    asset.notes = request.form.get("notes", "")
    db.session.commit()
    flash(f"Asset '{asset.name}' updated.", "success")
    return redirect(url_for("finance_index"))


@app.route("/finance/assets/<id>/delete", methods=["POST"])
def delete_asset(id):
    asset = Asset.query.get_or_404(id)
    db.session.delete(asset)
    db.session.commit()
    flash("Asset removed.", "info")
    return redirect(url_for("finance_index"))


@app.route("/finance/debts", methods=["POST"])
def create_debt():
    debt = Debt(
        name=request.form["name"].strip(),
        amount=float(request.form["amount"]),
        debt_type=request.form.get("debt_type", "credit_card"),
        notes=request.form.get("notes", "")
    )
    db.session.add(debt)
    db.session.commit()
    flash(f"Debt '{debt.name}' added.", "success")
    return redirect(url_for("finance_index"))


@app.route("/finance/debts/<id>/edit", methods=["POST"])
def edit_debt(id):
    debt = Debt.query.get_or_404(id)
    debt.name = request.form["name"].strip()
    debt.amount = float(request.form["amount"])
    debt.debt_type = request.form.get("debt_type", "credit_card")
    debt.notes = request.form.get("notes", "")
    db.session.commit()
    flash(f"Debt '{debt.name}' updated.", "success")
    return redirect(url_for("finance_index"))


@app.route("/finance/debts/<id>/delete", methods=["POST"])
def delete_debt(id):
    debt = Debt.query.get_or_404(id)
    db.session.delete(debt)
    db.session.commit()
    flash("Debt removed.", "info")
    return redirect(url_for("finance_index"))


# ─── Tracks ──────────────────────────────────────────────────────────────────

@app.route("/tracks")
def tracks_index():
    library = Track.query.filter_by(status="library").order_by(Track.created_at.desc()).all()
    current = Track.query.filter_by(status="current").order_by(Track.created_at.desc()).all()
    completed = Track.query.filter_by(status="completed").order_by(Track.completed_at.desc()).all()
    all_tracks = Track.query.all()
    goals_no_track = Goal.query.filter_by(track_id=None).order_by(Goal.created_at.desc()).all()
    return render_template("tracks/index.html",
        library=library, current=current, completed=completed,
        all_tracks=all_tracks, goals_no_track=goals_no_track,
        current_count=len(current)
    )


@app.route("/tracks", methods=["POST"])
def create_track():
    title = request.form["title"].strip()
    if not title:
        flash("Title required.", "danger")
        return redirect(url_for("tracks_index"))
    calendar_block_id = request.form.get("calendar_block_id") or None
    track = Track(title=title, status="library", calendar_block_id=calendar_block_id)
    db.session.add(track)
    db.session.commit()
    flash("Track created.", "success")
    return redirect(url_for("track_detail", id=track.id))


@app.route("/tracks/<id>")
def track_detail(id):
    track = Track.query.get_or_404(id)
    current_count = Track.query.filter_by(status="current").count()
    all_tracks = Track.query.order_by(Track.title).all()
    return render_template("tracks/track.html", track=track, current_count=current_count, all_tracks=all_tracks)


@app.route("/tracks/<id>/status", methods=["POST"])
def change_track_status(id):
    track = Track.query.get_or_404(id)
    new_status = request.form["status"]
    calendar_block_id = request.form.get("calendar_block_id") or None
    
    if new_status == "current":
        count = Track.query.filter_by(status="current").filter(Track.id != id).count()
        if count >= 3:
            flash("Limit reached — max 3 current tracks.", "danger")
            return redirect(url_for("track_detail", id=id))
    
    track.status = new_status
    if calendar_block_id:
        track.calendar_block_id = calendar_block_id
    db.session.commit()
    flash(f"Track moved to {new_status}.", "success")
    return redirect(url_for("tracks_index"))


@app.route("/tracks/<id>/complete", methods=["POST"])
def complete_track(id):
    track = Track.query.get_or_404(id)
    track.status = "completed"
    track.completed_at = datetime.utcnow()
    db.session.commit()
    flash("Track completed!", "success")
    return redirect(url_for("track_detail", id=id))


@app.route("/tracks/<id>/level-two", methods=["POST"])
def level_two(id):
    track = Track.query.get_or_404(id)
    new_track = Track(title=f"{track.title} — Level {track.level + 1}", status="library", level=track.level + 1)
    db.session.add(new_track)
    db.session.commit()
    flash(f"Level {new_track.level} track created.", "success")
    return redirect(url_for("track_detail", id=new_track.id))


@app.route("/tracks/<id>/checkpoints", methods=["POST"])
def add_checkpoint(id):
    track = Track.query.get_or_404(id)
    title = request.form["title"].strip()
    description = request.form.get("description", "")
    target_date_str = request.form.get("target_date", "")
    target_date = date.fromisoformat(target_date_str) if target_date_str else None
    cp = Checkpoint(track_id=id, title=title, description=description, target_date=target_date)
    db.session.add(cp)
    db.session.commit()
    flash("Checkpoint added.", "success")
    return redirect(url_for("track_detail", id=id))


@app.route("/tracks/<track_id>/checkpoints/<cp_id>/toggle", methods=["POST"])
def toggle_checkpoint(track_id, cp_id):
    cp = Checkpoint.query.get_or_404(cp_id)
    cp.completed = not cp.completed
    
    # If marking as complete and it's equipped as a goal, dequip it
    if cp.completed and cp.is_goal:
        goal = Goal.query.filter_by(checkpoint_id=cp_id).first()
        if goal:
            cp.is_goal = False
            db.session.delete(goal)
            db.session.flush()
            flash(f"Checkpoint completed and dequipped from goals.", "info")
    
    db.session.commit()
    return redirect(url_for("track_detail", id=track_id))


@app.route("/tracks/<track_id>/checkpoints/<cp_id>/edit", methods=["POST"])
def edit_checkpoint(track_id, cp_id):
    cp = Checkpoint.query.get_or_404(cp_id)
    cp.title = request.form["title"].strip()
    cp.description = request.form.get("description", "")
    target_date_str = request.form.get("target_date", "")
    cp.target_date = date.fromisoformat(target_date_str) if target_date_str else None
    db.session.commit()
    flash("Checkpoint updated.", "success")
    return redirect(url_for("track_detail", id=track_id))


@app.route("/tracks/<track_id>/checkpoints/<cp_id>/delete", methods=["POST"])
def delete_checkpoint(track_id, cp_id):
    cp = Checkpoint.query.get_or_404(cp_id)
    db.session.delete(cp)
    db.session.commit()
    flash("Checkpoint deleted.", "info")
    return redirect(url_for("track_detail", id=track_id))


@app.route("/tracks/<track_id>/checkpoints/<cp_id>/equip", methods=["POST"])
def equip_checkpoint_as_goal(track_id, cp_id):
    """Equip a checkpoint as a goal — creates a linked goal or marks is_goal=True"""
    cp = Checkpoint.query.get_or_404(cp_id)
    
    # Check if already equipped (has a linked goal)
    existing_goal = Goal.query.filter_by(checkpoint_id=cp_id).first()
    if existing_goal:
        flash("Checkpoint already equipped as a goal.", "warning")
        return redirect(url_for("track_detail", id=track_id))
    
    # Create a new goal linked to this checkpoint
    goal = Goal(
        checkpoint_id=cp_id,
        track_id=track_id,
        title=f"{cp.title} (from checkpoint)",
        description=cp.description,
        due_at=datetime.combine(cp.target_date, datetime.min.time()) if cp.target_date else None,
        status="doing_next"
    )
    cp.is_goal = True
    db.session.add(goal)
    db.session.commit()
    flash(f"Checkpoint '{cp.title}' equipped as goal.", "success")
    return redirect(url_for("track_detail", id=track_id))


@app.route("/tracks/<track_id>/checkpoints/<cp_id>/dequip", methods=["POST"])
def dequip_checkpoint_as_goal(track_id, cp_id):
    """Dequip a checkpoint from goals — deletes the linked goal"""
    cp = Checkpoint.query.get_or_404(cp_id)
    goal = Goal.query.filter_by(checkpoint_id=cp_id).first()
    
    if not goal:
        flash("Checkpoint is not equipped as a goal.", "warning")
        return redirect(url_for("track_detail", id=track_id))
    
    cp.is_goal = False
    db.session.delete(goal)
    db.session.commit()
    flash(f"Checkpoint '{cp.title}' dequipped from goals.", "success")
    return redirect(url_for("track_detail", id=track_id))


# ─── Goals ───────────────────────────────────────────────────────────────────

@app.route("/goals", methods=["POST"])
def create_goal():
    title = request.form["title"].strip()
    track_id = request.form.get("track_id") or None
    calendar_block_id = request.form.get("calendar_block_id") or None
    due_at_str = request.form.get("due_at", "")
    due_at = datetime.fromisoformat(due_at_str) if due_at_str else None
    description = request.form.get("description", "").strip()
    goal = Goal(
        title=title, 
        description=description, 
        track_id=track_id, 
        calendar_block_id=calendar_block_id,
        due_at=due_at, 
        status="doing_next"
    )
    db.session.add(goal)
    db.session.commit()
    flash("Goal created.", "success")
    return redirect(request.referrer or url_for("tracks_index"))


@app.route("/goals/<id>/move", methods=["POST"])
def move_goal(id):
    goal = Goal.query.get_or_404(id)
    direction = request.form["direction"]
    order = ["doing_next", "doing", "done"]
    idx = order.index(goal.status)
    if direction == "forward" and idx < 2:
        new_status = order[idx + 1]
        if new_status == "doing":
            doing_count = Goal.query.filter_by(status="doing").filter(Goal.id != id).count()
            if doing_count >= 3:
                flash("Doing column is full (max 3).", "danger")
                return redirect(url_for("kanban_index"))
        goal.status = new_status
    elif direction == "back" and idx > 0:
        goal.status = order[idx - 1]
    db.session.commit()
    return redirect(url_for("kanban_index"))


@app.route("/goals/<id>/edit", methods=["POST"])
def edit_goal(id):
    goal = Goal.query.get_or_404(id)
    goal.title = request.form["title"].strip()
    goal.description = request.form.get("description", "").strip()
    track_id = request.form.get("track_id") or None
    calendar_block_id = request.form.get("calendar_block_id") or None
    goal.track_id = track_id
    goal.calendar_block_id = calendar_block_id
    due_at_str = request.form.get("due_at", "")
    goal.due_at = datetime.fromisoformat(due_at_str) if due_at_str else None
    db.session.commit()
    flash("Goal updated.", "success")
    return redirect(request.referrer or url_for("tracks_index"))


@app.route("/goals/<id>/delete", methods=["POST"])
def delete_goal(id):
    goal = Goal.query.get_or_404(id)
    db.session.delete(goal)
    db.session.commit()
    flash("Goal deleted.", "info")
    return redirect(request.referrer or url_for("kanban_index"))


# ─── Kanban ──────────────────────────────────────────────────────────────────

@app.route("/kanban")
def kanban_index():
    doing_next = Goal.query.filter_by(status="doing_next").order_by(Goal.created_at).all()
    doing = Goal.query.filter_by(status="doing").order_by(Goal.created_at).all()
    done = Goal.query.filter_by(status="done").order_by(Goal.created_at.desc()).limit(10).all()
    all_tracks = Track.query.all()
    return render_template("kanban/index.html",
        doing_next=doing_next, doing=doing, done=done,
        all_tracks=all_tracks,
        doing_count=len(doing)
    )


@app.route("/kanban/bonus", methods=["POST"])
def bonus_task():
    doing_count = Goal.query.filter_by(status="doing").count()
    if doing_count >= 3:
        flash("Doing column is full.", "danger")
        return redirect(url_for("kanban_index"))
    next_goal = Goal.query.filter_by(status="doing_next").order_by(Goal.created_at).first()
    if next_goal:
        next_goal.status = "doing"
        db.session.commit()
        flash(f"'{next_goal.title}' pulled into Doing.", "success")
    else:
        flash("No goals in Doing Next.", "info")
    return redirect(url_for("kanban_index"))


# ─── Progress ────────────────────────────────────────────────────────────────

@app.route("/progress")
def progress_index():
    all_tracks = Track.query.order_by(Track.created_at).all()
    total_completed = Track.query.filter_by(status="completed").count()
    done_goals = Goal.query.filter_by(status="done").order_by(Goal.created_at.desc()).all()
    total_goals_done = len(done_goals)
    total_entries = JournalEntry.query.count()
    streak = gym_streak()

    return render_template("progress/index.html",
        all_tracks=all_tracks,
        total_completed=total_completed,
        done_goals=done_goals,
        total_goals_done=total_goals_done,
        total_entries=total_entries,
        streak=streak
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
