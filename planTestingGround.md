# Focus — Testing Ground
## Flask Edition (1–3 Day Build)

---

## 1. Overview

A fully manual, single-user, locally-run version of Focus built in Flask. Every module from the real app is present — calendar, journal, health, finance, tracks, kanban, and progress — with external APIs and AI replaced by manual input equivalents. The goal is to validate every UX flow and data model before building the production Rails app.

**No auth. No external APIs. No build step. Just run it.**

---

## 2. Stack

| Component | Technology | Why |
|---|---|---|
| Backend | Flask 3.x | Minimal, fast to scaffold |
| Database | SQLite via SQLAlchemy | Zero setup — single file |
| Templates | Jinja2 | Built into Flask |
| Styling | Bootstrap 5 (CDN) | No build step, full component library |
| Interactivity | Vanilla JS | No framework overhead |
| CSV Parsing | Python `csv` module | Built-in, no extra deps |

---

## 3. Simplification Map

Every real feature is present. External automation is replaced with manual equivalents.

| Real App Feature | Testing Ground Equivalent |
|---|---|
| Browser extension usage tracking | Manual "Log Activity" form — pick a block, enter URL/app, duration |
| Real-time Solid Cable discipline toast | Adherence score shown on page load / manual refresh |
| GPT-4o track generation | Manual form — fill in title, checkpoints, frequency yourself |
| Plaid bank sync | Manual transaction entry + CSV upload |
| Terra wearable sync | Manual health entry form |
| Habit Bot AI insights | Rule-based alerts — hardcoded thresholds |
| Journal encryption | Plain text, local SQLite only (local machine, single user) |
| PWA / installable | Runs at localhost in browser |
| Tailwind CSS | Bootstrap 5 via CDN |
| Kanban drag-and-drop | Click-to-move buttons — same columns, same WIP limits enforced |
| MFA / biometric gate | Single password field on journal page (no session, just a gate) |

---

## 4. Data Models

```python
User            # single row — id, name, created_at
CalendarBlock   # id, title, starts_at, ends_at, allowed_apps (comma string), adherence_score
UsageLog        # id, calendar_block_id, app_or_url, active_at, duration_seconds
JournalEntry    # id, body, stress_level, created_at, updated_at
HealthRecord    # id, record_type, source, value (json string), recorded_at
Track           # id, title, status, level, metadata (json string), completed_at, created_at
Goal            # id, track_id (nullable), title, status, due_at, created_at
Transaction     # id, merchant_name, amount, category, transacted_at, notes
```

All IDs are UUIDs (`uuid.uuid4()`) to stay compatible with the production schema.

---

## 5. Module Breakdown

### 5.1 Tracked Calendar
- View: week grid showing all blocks for the current week
- Create / edit / delete time blocks (title, start time, end time, allowed apps list)
- **Log Activity**: form on each block — enter what app/URL you were on and for how many minutes
- Adherence Score displayed per block: `(on-task minutes / block duration) * 100`
- Discipline flag: block turns red if adherence score < 70%

### 5.2 Mental Health Journal
- Simple password gate on the journal route (hardcoded env var — not session auth)
- Create entry with body text + stress level (1–10 slider)
- Sentence stem prompts shown above the text area ("I am proud of...", "Today I achieved...", "It's OK to...")
- View: scrollable feed of entries, newest first
- Calendar archive: click a date, see entries from that day
- Basic keyword search (Python string matching on body)

### 5.3 Physical Health
- Manual entry form: record type (gym visit, vital, sleep, appointment), value, date
- Gym streak counter: consecutive days with a gym_visit record
- Appointment tracker: list of appointments sorted by date, flag if type not seen in 12 months
- Simple table view of all health records, filterable by type

### 5.4 Financial Module
- Manual transaction entry: merchant, amount, category, date, notes
- CSV upload: parse and bulk-insert transactions
- Spending breakdown by category (simple % of total)
- Rule-based alerts:
  - If any single category > 20% of monthly spend → show warning
  - If total spend this month > last month → show flag
- Savings note: free-text field to log savings goals and progress manually

### 5.5 Tracks & Goals
- Create a track manually: title, level (default 1), status (library/current/completed)
- Add checkpoints to a track: title, description, target date
- WIP limit enforced: max 3 tracks in "current" status (form disabled if limit hit, shows message)
- Create goals: title, optional track association, status, due date
- Level Two: when a track is marked complete, a "Start Level 2" button appears — creates a new track with same title + " — Level 2"

### 5.6 Kanban Board
- Three columns: Doing Next / Doing / Done
- Each goal card has arrow buttons: move left / move right between columns
- WIP limit of 3 enforced in the model — button disabled + message shown if limit reached
- "Bonus task" pull: button to pull a Doing Next item into Doing if Doing has < 3

### 5.7 User Progress
- List of all tracks ever created, grouped by status
- Completion percentage per track (checkpoints completed / total checkpoints)
- Completed tracks section with completion date
- Total stats: tracks completed, goals done, journal entries written, gym streak

---

## 6. Project Structure

```
FocusTestingGround/
├── app.py
├── models.py
├── requirements.txt
├── .env
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── calendar/
│   │   ├── index.html
│   │   └── block.html
│   ├── journal/
│   │   ├── index.html
│   │   └── entry.html
│   ├── health/
│   │   └── index.html
│   ├── finance/
│   │   └── index.html
│   ├── tracks/
│   │   ├── index.html
│   │   └── track.html
│   ├── kanban/
│   │   └── index.html
│   └── progress/
│       └── index.html
└── static/
    └── focus.css       ← minor overrides on top of Bootstrap
```

---

## 7. Routes

```
GET  /                          → dashboard (today's blocks, streak, recent entry)
GET  /calendar                  → week view
POST /calendar/blocks           → create block
GET  /calendar/blocks/<id>      → block detail + log activity form
POST /calendar/blocks/<id>/log  → submit usage log
POST /calendar/blocks/<id>/delete

GET  /journal                   → feed + search
POST /journal                   → create entry
GET  /journal/<id>/edit
POST /journal/<id>/edit
POST /journal/<id>/delete

GET  /health                    → records + streak + appointment flags
POST /health                    → create health record
POST /health/<id>/delete

GET  /finance                   → transaction list + category breakdown + alerts
POST /finance                   → create transaction
POST /finance/import            → CSV upload
POST /finance/<id>/delete

GET  /tracks                    → library + current + completed
POST /tracks                    → create track
GET  /tracks/<id>               → track detail + checkpoints
POST /tracks/<id>/checkpoints   → add checkpoint
POST /tracks/<id>/complete      → mark complete, unlock Level 2
POST /tracks/<id>/status        → change status (library/current)

GET  /goals                     → all goals
POST /goals                     → create goal
POST /goals/<id>/move           → change kanban status

GET  /kanban                    → kanban board view
GET  /progress                  → full history + stats
```

---

## 8. Build Order (1–3 Days)

### Day 1
- [ ] `flask new` scaffold: `app.py`, `models.py`, `base.html`, Bootstrap CDN wired up
- [ ] SQLAlchemy models + `db.create_all()`
- [ ] Dashboard route with placeholder cards for each module
- [ ] Calendar: week view, create/edit/delete blocks, log activity form, adherence score calculation
- [ ] Journal: create entry, feed view, sentence stem prompts, password gate

### Day 2
- [ ] Health: manual entry form, gym streak counter, appointment interval flags
- [ ] Finance: manual entry, CSV upload, category breakdown, rule-based alerts
- [ ] Tracks: create track, add checkpoints, status changes, 3-track WIP limit
- [ ] Goals: create goal, associate to track

### Day 3
- [ ] Kanban: three-column view, move buttons, WIP enforcement, bonus task pull
- [ ] Progress: full history, completion %, stats summary
- [ ] Level Two logic on track completion
- [ ] Dashboard wired up with real data (streak, today's blocks, last journal entry)
- [ ] Basic styling pass — consistent Bootstrap layout across all pages

---

## 9. Dependencies

```
flask
flask-sqlalchemy
python-dotenv
```

That's it. No other packages needed.

---

## 10. Optional Upgrades

> Add these after the core build if useful for testing.

- [ ] Chart.js CDN — spending pie chart, adherence score bar chart on progress page
- [ ] Simple search on finance transactions (Python string match, same as journal)
- [ ] Export any table to CSV (one route per model, `csv.writer` response)
- [ ] Dark mode toggle (Bootstrap data-bs-theme switch, no extra CSS)
- [ ] HTMX for inline form submissions (removes page reloads on log activity / move goal)