# NEPTUNE - Student Management System

A multi-user web application for the **Registrar**, **Accounting** and **Academic** departments (plus an **Admin** role), built with Flask. Several people on different computers can work at the same time the database arbitrates conflicting updates so records stay consistent.

## Documentation

- [Architecture and parallel/distributed design](docs/ARCHITECTURE.md)
- [Database design (ERD)](docs/ERD.md)
- [Testing and concurrency evidence](docs/TESTING.md)
- [Deployment on Render + PostgreSQL](DEPLOYMENT.md)
- [Security notes and production checklist](SECURITY.md)

## Quick start

Requires Python 3.13 or newer.(THIS IMPORT YEAH!) check cmd >>python --version<< if not 3.13 or latest version update it  no?

```powershell
# Windows
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

**Development demo logins** (created automatically on the first run in development mode only): `registrar`, `accounting`, `academic` and `admin`, with passwords `registrar123`, `accounting123`, `academic123` and `admin123`. They are for local testing production mode never creates them (see [SECURITY.md](SECURITY.md)).

## Sample data

All sample-data scripts live in the `Seed Sample data/` folder. Stop the app, then run from the project folder (each script backs up the database first and never overwrites existing records):

```bash
python "Seed Sample data/seed_sample_records.py"                  # staff, students, payments, professors, timetable
python "Seed Sample data/seed_sample_financial_reports.py"        # Financial Reports: statements, budgets, projections, billing statements
python "Seed Sample data/seed_sample_financial_reports.py" --replace   # refresh the rows this script wrote earlier
```

The financial sample figures agree with each other: every balance sheet balances, each year's opening equity is the previous year's closing equity, and the cash-flow change equals the change in cash.

## Run the tests

```bash
python tests/run_concurrency_tests.py --users 20 --load-levels 1,5,10,25,50
```

This starts the app on a temporary database, runs the concurrency and load tests, and stops it. See [docs/TESTING.md](docs/TESTING.md).

## How concurrent use is kept safe

| Risk | Safeguard |
|---|---|
| Two registrars get the same next student number | Unique constraint, rollback and retry with random back-off |
| Same attendance entry saved at the same instant | Unique constraint; the losing request becomes an update |
| Two users edit the same grade | Compare-and-set: the edit is refused with a conflict message if the grade changed meanwhile |
| Payment form double-click or retry | One-time form token consumed in the database before saving |
| Duplicate grade for student, course and semester | Unique constraint and `IntegrityError` handling |
| Payments stored as floating point | Exact `NUMERIC(12,2)` / `Decimal` |
| Repeated wrong passwords | Per-IP throttle, plus a temporary account lock (default 15 minutes) that expires by itself |
| SQLite "database is locked" under bursts | WAL mode and 30 second busy timeout; remaining errors show a friendly 503 page |

## Configuration (environment variables)

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Session signing key (32+ characters) | generated once in `instance/.secret_key` (development only) |
| `DATABASE_URL` | SQLite or PostgreSQL URL | `instance/student_management.db` |
| `APP_ENV` | `production` enforces a strong secret, secure cookies, no demo data | `development` |
| `APP_TIMEZONE` | Timezone for displayed times and daily filters | `Asia/Manila` |
| `LOGIN_LOCKOUT_MINUTES` | How long an account stays locked after too many failed logins | `15` |
| `HOST` / `PORT` | Listen address / port | `127.0.0.1` / `5000` |
| `FLASK_DEBUG` | `1` enables the debugger | on only for localhost |
| `SESSION_COOKIE_SECURE` | `1` when served over HTTPS | off (on in production) |

## Database notes

- Times are stored in UTC and shown in `APP_TIMEZONE`.
- On startup, missing columns and indexes are added automatically on both SQLite and PostgreSQL. For SQLite, a timestamped `.bak` copy is saved first when columns must be added.
- Older databases that stored payment amounts as floats are converted to exact decimals automatically.
- There is no migration tool; schema changes live in `init_database()` in `app.py`.

## Known limitations

- SQLite allows one writer at a time; use PostgreSQL for real multi-user load.
- Message attachments are saved on the server's local disk (`instance/message_attachments`), which is ephemeral on Render.
- The per-IP login throttle is in memory per worker; the account lock is stored in the database and shared.
- Concurrency tests have been run on SQLite with a single server process, not on PostgreSQL or several workers.
- The payment list shows the latest 500 matching rows.
- School-project baseline: add backups, HTTPS and a security review before holding real student data.

## Project layout

```
app.py              Flask application: models, routes, security, startup
templates/          Jinja templates
static/             CSS, JavaScript, logo (uploads/ is git-ignored)
tests/              Concurrency and load tests
Seed Sample data/   Scripts that load sample records and financial reports
docs/               Architecture, ERD, testing evidence
DEPLOYMENT.md       Render + PostgreSQL walkthrough
SECURITY.md         Security notes
```
