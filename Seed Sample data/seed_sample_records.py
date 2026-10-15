#!/usr/bin/env python3
"""
NEPTUNE - sample record loader
==============================
Adds sample records for the Registrar, Accounting and Academic departments, staff
accounts, professors (instructors) and a full-week class schedule for BS5MA.

Usage (stop the Flask app first, then run from the project folder):

    python "Seed Sample data/seed_sample_records.py"                 # uses instance/student_management.db
    python "Seed Sample data/seed_sample_records.py" path/to/student_management.db

* Only the Python standard library is needed.
* Safe to run more than once: every record is looked up by its natural key first
  (username, e-mail, student number, payment reference, schedule slot, ...) and
  skipped when it already exists.
* A timestamped backup of the database is written next to it before anything changes.
* Nothing existing is deleted. The only existing rows that are modified are the
  `course.instructor` names of the subjects the new professors teach (see INSTRUCTOR_COURSES).
"""
import hashlib
import json
import random
import secrets
import shutil
import sqlite3
import string
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent   # this script lives in "Seed Sample data/"
DB_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "instance" / "student_management.db"

PH_OFFSET = timedelta(hours=8)          # the app stores naive UTC; the school is on Asia/Manila (UTC+8)
TODAY = date(2026, 10, 14)              # "today" for the sample data (last day that has records)
CURRENT_SY_START = 2026                 # school year 2026-2027
CURRENT_TERM = "1st Semester"
STAFF_PASSWORD = "Staff@Neptune2026"    # 17 characters (the app requires 12+). CHANGE after first login.
BSCS_NAME = "Bachelor of Science in Computer Science"
BSCS_KEY = "BSCS"


# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------
def utc(local_dt):
    """Local (Manila) datetime -> naive UTC string as stored by the app."""
    return (local_dt - PH_OFFSET).strftime("%Y-%m-%d %H:%M:%S.%f")


def hash_password(password):
    """Same format as werkzeug.security.generate_password_hash (scrypt:32768:8:1)."""
    salt = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=32768, r=8, p=1,
                            maxmem=132 * 1024 * 1024, dklen=64).hex()
    return f"scrypt:32768:8:1${salt}${digest}"


def weekday_between(rng, start, end):
    """A random Monday-Friday date between two dates (inclusive)."""
    while True:
        d = start + timedelta(days=rng.randint(0, (end - start).days))
        if d.weekday() < 5:
            return d


ACTIVITY_TYPES = ["CREATED", "EDITED", "UPDATED", "DELETED", "RECORDED", "CALCULATED", "LOGIN", "LOGOUT", "FAILED_LOGIN"]
MODULES = ["dashboard", "students", "sections", "payments", "courses", "curriculum", "grades", "assessments",
           "attendance", "reports", "instructors", "timetable", "messages", "activity_history", "staff_accounts",
           "security", "concurrency", "account"]


def default_access(role, manages_timetable):
    """Mirror of default_access_for_role() in app.py: what the Staff Accounts page would save."""
    result = {m: [] for m in MODULES}

    def grant(module, *actions):
        result[module] = list(actions)
    if role == "Registrar":
        grant("dashboard", "view"); grant("students", "view", "create", "edit", "delete")
        grant("sections", "view", "create", "edit", "delete"); grant("grades", "view", "create", "edit")
        grant("activity_history", "view"); grant("messages", "view", "create", "edit", "delete")
        grant("account", "view", "edit"); grant("curriculum", "view"); grant("reports", "view")
    elif role == "Accounting":
        grant("dashboard", "view"); grant("payments", "view", "create", "edit"); grant("activity_history", "view")
        grant("messages", "view", "create", "edit", "delete"); grant("account", "view", "edit")
    elif role == "Academic":
        grant("dashboard", "view"); grant("students", "view"); grant("courses", "view", "create", "edit", "delete")
        grant("curriculum", "view"); grant("grades", "view", "create", "edit", "delete")
        grant("assessments", "view", "create", "edit", "delete"); grant("attendance", "view", "create", "edit")
        grant("activity_history", "view"); grant("account", "view", "edit")
        grant("messages", "view", "create", "edit", "delete")
    grant("concurrency", "view")
    if manages_timetable:
        grant("instructors", "view", "create", "edit", "delete"); grant("timetable", "view", "create", "edit", "delete")
    return result


# ----------------------------------------------------------------------------------------------
# sample data
# ----------------------------------------------------------------------------------------------
# username, role, can manage Instructors + Class Timetable
STAFF = [
    ("registrar.reyes",     "Registrar",  False),
    ("registrar.lopez",     "Registrar",  False),
    ("accounting.mercado",  "Accounting", False),
    ("accounting.tolentino", "Accounting", False),
    ("academic.santiago",   "Academic",   True),    # academic head: also manages instructors + timetable
    ("academic.dizon",      "Academic",   False),
]

# name, e-mail, subjects, type, working days, start, end
WEEK = "Monday,Tuesday,Wednesday,Thursday,Friday"
PROFESSORS = [
    ("Rizza Capangyarihan Villanueva", "rizza.villanueva@gmail.com",
     "GE 109 Readings in Rizal's Life and Works; GE core subjects (Understanding the Self, Purposive Communication, "
     "Ethics, Art Appreciation, Science Technology & Society); GE 111 The Entrepreneurial Mind; Entrepreneurship (ENT)",
     "Full-time", WEEK, "07:00", "17:00"),
    ("Xerxes Von Plata", "xerxes.plata@gmail.com",
     "App Development: CS 301 Software Engineering 1; CS 303 Human Computer Interaction; CS 307 CS Elective 1 "
     "(App Development); CS 402 Platform-based Development; IT 105 Mobile Development; IT 119 Web Systems; "
     "IT 127 Application Development and Emerging Technologies",
     "Full-time", WEEK, "07:00", "18:00"),
    ("Marites Dumalagan Ocampo", "marites.ocampo@gmail.com",
     "CS 302 Automata Theory and Formal Languages; CS 101 / CS 202 Discrete Structures",
     "Full-time", "Monday,Tuesday,Wednesday,Thursday", "07:00", "17:00"),
    ("Joseph Emmanuel Tuazon", "joseph.tuazon@gmail.com",
     "CS 304 Information Assurance and Security; CS 209 Networks and Communications",
     "Full-time", "Tuesday,Wednesday,Thursday,Friday", "07:00", "18:00"),
    ("Katrina Alyssa Ventura", "katrina.ventura@gmail.com",
     "CS 305 Intelligent Systems; CS 403 Fundamentals of Data Science",
     "Full-time", WEEK, "07:00", "18:00"),
    ("Ramon Isidro Gatchalian", "ramon.gatchalian@gmail.com",
     "CS 306 Parallel and Distributed Computing; CS 207 Operating Systems",
     "Part-time", "Wednesday,Friday", "13:00", "18:00"),
]
RIZZA, XERXES, OCAMPO, TUAZON, VENTURA, GATCHALIAN = [p[0] for p in PROFESSORS]

# Courses (Course List codes) whose "instructor" becomes the new professor, so report cards,
# grade reports and the timetable all name the same person.
INSTRUCTOR_COURSES = {
    RIZZA: ["ENT 101", "ENT 204", "ENT 301", "ENT 302", "GE 117"],          # + every GE subject of the BSCS plan
    XERXES: ["CS 301", "CS 303", "CS 307", "CS 402", "IT 105", "IT 105 L", "IT 119", "IT 119 L", "IT 127", "IT 127 L"],
    OCAMPO: ["CS 302", "CS 101", "CS 202"],
    TUAZON: ["CS 304", "CS 209"],
    VENTURA: ["CS 305", "CS 403"],
    GATCHALIAN: ["CS 306", "CS 207"],
}

SECTIONS = [("BS3MA", 1), ("BS4MA", 2), ("BS5MA", 3), ("BS6MA", 4)]   # these already exist in the sample DB

# BS5MA = 3rd year BSCS, 1st Semester 2026-2027 (curriculum: GE 109, CS 301 - CS 307), 3 units each = 24 h/week.
# Mon/Thu mornings, Tue/Fri afternoons, Wednesday two 3-hour blocks.  (day, start, end, subject, professor, room)
BS5MA_SCHEDULE = []
for _day in ("Monday", "Thursday"):
    BS5MA_SCHEDULE += [
        (_day, "07:30", "09:00", "CS 301|Software Engineering 1", XERXES, "Computer Lab 1"),
        (_day, "09:00", "10:30", "CS 302|Automata Theory and Formal Languages", OCAMPO, "Room 305"),
        (_day, "10:30", "12:00", "GE 109|Readings in Rizal's Life and Works", RIZZA, "Room 301"),
    ]
for _day in ("Tuesday", "Friday"):
    BS5MA_SCHEDULE += [
        (_day, "13:00", "14:30", "CS 303|Human Computer Interaction", XERXES, "Computer Lab 2"),
        (_day, "14:30", "16:00", "CS 304|Information Assurance and Security", TUAZON, "Room 306"),
        (_day, "16:00", "17:30", "CS 305|Intelligent Systems", VENTURA, "Room 306"),
    ]
BS5MA_SCHEDULE += [
    ("Wednesday", "08:00", "11:00", "CS 307|CS Elective 1", XERXES, "Computer Lab 1"),
    ("Wednesday", "13:00", "16:00", "CS 306|Parallel and Distributed Computing", GATCHALIAN, "Computer Lab 2"),
]

# number, first, last, gender, birth date, residency, year, section, admission year, type, load, base grade %
STUDENTS = [
    # ---- BS5MA - 3rd year BSCS (admitted 2024-2025)
    ("2024-0001", "Mathew", "Alarcon",   "Male",   date(2005, 3, 18),  "Marikina City",   3, "BS5MA", "2024-2025", "First-time Freshman", "Full-time", 89),
    ("2024-0002", "Angelica Mae", "Fajardo", "Female", date(2005, 7, 2),   "Quezon City",     3, "BS5MA", "2024-2025", "First-time Freshman", "Full-time", 92),
    ("2024-0003", "Carlo Miguel", "Estrella", "Male", date(2004, 11, 23), "Caloocan City",   3, "BS5MA", "2024-2025", "First-time Freshman", "Full-time", 85),
    ("2024-0004", "Jasmine Rose", "Pangilinan", "Female", date(2005, 1, 29), "Pasig City",    3, "BS5MA", "2024-2025", "First-time Freshman", "Full-time", 90),
    ("2024-0005", "Kenneth James", "Salvador", "Male", date(2004, 9, 10),  "Antipolo City",   3, "BS5MA", "2024-2025", "First-time Freshman", "Full-time", 82),
    ("2024-0006", "Bianca Louise", "Ramirez", "Female", date(2005, 5, 14), "San Mateo, Rizal", 3, "BS5MA", "2024-2025", "First-time Freshman", "Full-time", 86),
    # ---- BS6MA - 4th year BSCS (admitted 2023-2024; one transferee)
    ("2023-0001", "Patricia Anne", "Lacson", "Female", date(2003, 12, 5), "Malolos, Bulacan", 4, "BS6MA", "2023-2024", "First-time Freshman", "Full-time", 91),
    ("2023-0002", "Miguel Antonio", "Roxas", "Male",  date(2003, 6, 17),  "Manila",          4, "BS6MA", "2023-2024", "First-time Freshman", "Full-time", 84),
    ("2023-0003", "Sofia Isabel", "Valdez",  "Female", date(2004, 2, 11),  "Imus, Cavite",    4, "BS6MA", "2023-2024", "First-time Freshman", "Full-time", 88),
    ("2025-0001", "Jericho Dominic", "Padilla", "Male", date(2003, 8, 30), "Quezon City",     4, "BS6MA", "2025-2026", "Transfer",            "Full-time", 86),
    # ---- BS4MA - 2nd year BSCS (admitted 2025-2026)
    ("2025-0002", "Lorenzo Matteo", "Aguilar", "Male", date(2006, 4, 9),   "Pasig City",      2, "BS4MA", "2025-2026", "First-time Freshman", "Full-time", 90),
    ("2025-0003", "Danica Joy", "Villar",    "Female", date(2006, 10, 21), "Mandaluyong City", 2, "BS4MA", "2025-2026", "First-time Freshman", "Full-time", 85),
    ("2025-0004", "Rafael Dominic", "Sison", "Male",   date(2006, 2, 14),  "Taguig City",     2, "BS4MA", "2025-2026", "First-time Freshman", "Full-time", 87),
    ("2025-0005", "Alyssa Nicole", "Montano", "Female", date(2006, 8, 3),  "Marikina City",   2, "BS4MA", "2025-2026", "First-time Freshman", "Part-time", 83),
    # ---- BS3MA - 1st year BSCS (admitted 2026-2027)
    ("2026-0004", "Christian Paul", "Domingo", "Male", date(2007, 5, 27),  "Quezon City",     1, "BS3MA", "2026-2027", "First-time Freshman", "Full-time", 88),
    ("2026-0005", "Hannah Grace", "Ilagan",  "Female", date(2007, 9, 12),  "Valenzuela City", 1, "BS3MA", "2026-2027", "First-time Freshman", "Full-time", 91),
    ("2026-0006", "Joshua Emmanuel", "Cabrera", "Male", date(2007, 1, 8),  "Malabon City",    1, "BS3MA", "2026-2027", "First-time Freshman", "Full-time", 84),
    ("2026-0007", "Trisha Mae", "Llamas",    "Female", date(2007, 3, 30),  "Navotas City",    1, "BS3MA", "2026-2027", "First-time Freshman", "Full-time", 86),
]

# Grade exceptions: (student number, course code, semester-term key, percentage, mark)
#   Failures with a passed retake, one authorised withdrawal and one incomplete.
GRADE_OVERRIDES = {
    ("2024-0005", "MATH 102"): (72, None),     # Kenneth failed Calculus 2 ...
    ("2023-0002", "CS 207"): (73, None),       # Miguel failed Operating Systems ...
    ("2025-0003", "GE 107"): (0, "AW"),        # Danica dropped STS (authorised withdrawal)
    ("2023-0003", "CS 404"): (0, "INC"),       # Sofia is incomplete in CS Elective 3
}
RETAKES = [    # (student number, course code, semester label, percentage)
    ("2024-0005", "MATH 102", "Summer 2024-2025", 78),
    ("2023-0002", "CS 207", "Summer 2024-2025", 77),
]

# Assessments recorded so far this term for the BS5MA students (course -> performance task)
PERFORMANCE_TASKS = {
    "CS 301": ("Product Output", "Software Requirements Specification"),
    "CS 302": ("Skills Demonstration", "DFA / NFA Construction Exercise"),
    "GE 109": ("Group Presentation", "Rizal Chapter Presentation"),
    "CS 303": ("Product Output", "Low-fidelity Prototype"),
    "CS 304": ("Laboratory Experiment", "Network Security Lab Activity"),
    "CS 305": ("Skills Demonstration", "Search Algorithm Implementation"),
    "CS 306": ("Laboratory Experiment", "Thread Synchronization Lab"),
    "CS 307": ("Product Output", "Mobile App Mockup"),
}

# Tuition 3 equal installments, miscellaneous and laboratory fees (PHP).
TUITION_INSTALLMENT = 7500.00
MISC_FEE = 5850.00
LAB_FEE = 3600.00
# installments paid so far by student number (3 = fully paid); anything not listed has paid 3
PAID_INSTALLMENTS = {"2026-0006": 1, "2025-0004": 2, "2024-0005": 2, "2025-0005": 2}
# payments dated *today* (Oct 14, 2026) so the Payments page shows data by default:
#   student number -> list of (type, amount, local time)
TODAY_PAYMENTS = {
    "2024-0006": [("Tuition", TUITION_INSTALLMENT, time(8, 42))],
    "2024-0004": [("Tuition", TUITION_INSTALLMENT, time(9, 15))],
    "2023-0001": [("Other", 150.00, time(9, 40))],
    "2026-0005": [("Tuition", TUITION_INSTALLMENT, time(10, 5))],
    "2025-0002": [("Tuition", TUITION_INSTALLMENT, time(10, 30)), ("Other", 350.00, time(10, 32))],
    "2026-0007": [("Tuition", TUITION_INSTALLMENT, time(11, 10))],
}

ANNOUNCEMENTS = [
    ("Midterm Examinations: October 26-30, 2026",
     "Midterm examinations for the 1st Semester 2026-2027 will run from October 26 to 30, 2026. Students must be "
     "cleared of the second tuition installment to receive their exam permits from the Accounting Office. Professors "
     "should submit exam questions to the Academic Office one week before the exam week.", "2026-10-12 01:30:00"),
    ("Third Tuition Installment Due October 16",
     "The third installment of the 1st Semester tuition is due on October 16, 2026. Please settle it at the Accounting "
     "Office or with the reference number given at the cashier. Students with unpaid balances may be held from the "
     "midterm examination clearance.", "2026-10-09 02:15:00"),
    ("Grade Submission Guidelines for Professors",
     "Final grades must be encoded by the Academic Office on the Grades page using the percentage rating (0-100), which "
     "the system converts to the 1.00-5.00 scale. Use INC, AW, UW or NCA only when the situation applies. The Registrar "
     "has read-only access to grade records and will verify every submission.", "2026-10-05 03:00:00"),
    ("ID Validation for 1st Semester",
     "Student ID validation stickers are available at the Registrar's Office from Monday to Friday, 8:00 AM to 4:00 PM. "
     "Bring your registration form and proof of payment of the Miscellaneous fee. The validation fee is PHP 150.",
     "2026-09-21 01:00:00"),
    ("Request for TOR, Certifications and Clearances",
     "Students who need a Transcript of Records, Certificate of Enrollment or graduation clearance should file a request "
     "through the Messages page (Registrar inbox) at least five working days before the date needed. 4th-year students "
     "applying for graduation clearance are advised to check the Graduation Clearance report for missing subjects.",
     "2026-09-14 02:20:00"),
    ("Welcome to the 1st Semester 2026-2027",
     "Classes for the 1st Semester 2026-2027 began on August 17, 2026. Section BS3MA (1st Year), BS4MA (2nd Year), BS5MA "
     "(3rd Year) and BS6MA (4th Year) schedules are posted on the Class Timetable page. Please report timetable concerns "
     "to the Academic Office.", "2026-08-14 00:45:00"),
]

# sender username, recipient (department role or username), category, subject, body, created (local), read?
MESSAGES = [
    ("academic.santiago", "dept:Registrar", "Transcript / Grade History",
     "1st Semester grades of BS5MA are encoded - please verify",
     "Good day, Registrar. The 1st Semester grades of section BS5MA (3rd Year BSCS) have been encoded for CS 301 to CS 307 "
     "and GE 109. Please verify them against the class records before they are used for the grade distribution report.",
     datetime(2026, 10, 12, 14, 10), True),
    ("registrar.reyes", "user:academic.santiago", "Transcript / Grade History",
     "Re: 1st Semester grades of BS5MA",
     "Thank you. We checked all eight subjects for Mathew Alarcon (2024-0001) and his classmates; everything matches. "
     "Kenneth Salvador's retake of MATH 102 is also correctly recorded under Summer 2024-2025.",
     datetime(2026, 10, 13, 9, 30), False),
    ("accounting.mercado", "dept:Registrar", "Payment Clarification",
     "Students with unpaid tuition installments",
     "Accounting has four students with unpaid tuition installments: Joshua Emmanuel Cabrera (2026-0006), Rafael Dominic "
     "Sison (2025-0004), Kenneth James Salvador (2024-0005) and Alyssa Nicole Montano (2025-0005). Please hold their "
     "midterm permit requests until they settle.",
     datetime(2026, 10, 13, 15, 45), False),
    ("registrar.lopez", "dept:Accounting", "Payment History",
     "Payment history needed for graduation clearance",
     "For the graduation clearance of Sofia Isabel Valdez (2023-0003) and Miguel Antonio Roxas (2023-0002), may we get "
     "a copy of their payment history for the past four school years?",
     datetime(2026, 10, 13, 10, 5), True),
    ("registrar.reyes", "dept:Accounting", "Enrollment / Registration",
     "Enrollment list of BS3MA freshmen",
     "The four BS3MA freshmen are now enrolled (2026-0004 to 2026-0007). Please confirm that their Tuition, "
     "Miscellaneous and Laboratory fees are recorded.",
     datetime(2026, 10, 10, 11, 20), True),
    ("academic.dizon", "user:admin", "Request for Information",
     "Request: room assignments for CS 307 and CS 306",
     "Please confirm that Computer Lab 1 (Wednesday 08:00-11:00) and Computer Lab 2 (Wednesday 13:00-16:00) stay reserved "
     "for CS 307 and CS 306 all semester, since both subjects need installed development tools.",
     datetime(2026, 10, 8, 16, 0), True),
    ("admin", "user:academic.santiago", "General",
     "Instructor and timetable access confirmed",
     "Your account can now manage Instructors and the Class Timetable. Please keep every instructor's working days and "
     "availability hours up to date, because the timetable rejects classes outside them.",
     datetime(2026, 8, 12, 9, 0), True),
]


# ----------------------------------------------------------------------------------------------
# loader
# ----------------------------------------------------------------------------------------------
def main():
    if not DB_PATH.exists():
        sys.exit(f"Database not found: {DB_PATH}")
    backup = DB_PATH.with_name(f"{DB_PATH.name}.{datetime.now():%Y%m%d-%H%M%S}.before-sample-records.bak")
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(backup)
    src.backup(dst)
    dst.close(); src.close()
    print(f"Backup saved: {backup}")

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    cur = db.cursor()
    stats = {}

    def bump(name, n=1):
        stats[name] = stats.get(name, 0) + n

    # ---- sections (they already exist in the sample DB; create only if missing)
    section_id = {}
    for name, year in SECTIONS:
        row = cur.execute("SELECT id FROM section WHERE name=?", (name,)).fetchone()
        if not row:
            cur.execute("INSERT INTO section (name, year_level, capacity) VALUES (?,?,30)", (name, year))
            row = cur.execute("SELECT id FROM section WHERE name=?", (name,)).fetchone()
            bump("sections")
        section_id[name] = row["id"]

    # ---- staff accounts
    staff_id = {r["username"]: r["id"] for r in cur.execute("SELECT id, username FROM user")}
    for username, role, manages in STAFF:
        if username in staff_id:
            continue
        cur.execute(
            """INSERT INTO user (username, password_hash, role, activity_visibility, activity_departments,
               access_permissions, can_manage_teachers_timetable, failed_login_count, login_locked,
               security_notifications_enabled) VALUES (?,?,?,?,?,?,?,0,0,1)""",
            (username, hash_password(STAFF_PASSWORD), role, json.dumps(ACTIVITY_TYPES), json.dumps([role]),
             json.dumps(default_access(role, manages)), int(manages)))
        staff_id[username] = cur.lastrowid
        bump("staff accounts")

    # ---- professors
    teacher_id = {}
    for name, email, subjects, emp, days, start, end in PROFESSORS:
        row = cur.execute("SELECT id FROM teacher WHERE lower(email)=?", (email,)).fetchone()
        if not row:
            cur.execute("INSERT INTO teacher (name,email,subjects,employment_type,working_days,available_start,available_end)"
                        " VALUES (?,?,?,?,?,?,?)", (name, email, subjects[:255], emp, days, start, end))
            row = {"id": cur.lastrowid}
            bump("professors")
        teacher_id[name] = row["id"]

    # ---- class schedule for BS5MA (validated with the same rules the Timetable page uses)
    teacher_rows = {r["id"]: r for r in cur.execute("SELECT * FROM teacher")}
    for day, start, end, subject, prof, room in BS5MA_SCHEDULE:
        tid, sid = teacher_id[prof], section_id["BS5MA"]
        if cur.execute("SELECT 1 FROM class_schedule WHERE section_id=? AND day=? AND start_time=?", (sid, day, start)).fetchone():
            continue
        t = teacher_rows[tid]
        assert day in t["working_days"].split(",") and start >= t["available_start"] and end <= t["available_end"], \
            f"{prof} is not available for {day} {start}-{end}"
        for o in cur.execute("SELECT * FROM class_schedule WHERE day=?", (day,)):
            if start < o["end_time"] and end > o["start_time"]:
                assert o["teacher_id"] != tid, f"Instructor conflict {prof} {day} {start}"
                assert o["classroom"].lower() != room.lower(), f"Room conflict {room} {day} {start}"
                assert o["section_id"] != sid, f"Section conflict {day} {start}"
        cur.execute("INSERT INTO class_schedule (day,start_time,end_time,subject,teacher_id,classroom,section_id) VALUES (?,?,?,?,?,?,?)",
                    (day, start, end, subject, tid, room, sid))
        bump("class schedule rows")

    # ---- Course List: keep the instructor name consistent with the new professors
    bscs = cur.execute("SELECT id FROM curriculum_program WHERE key=?", (BSCS_KEY,)).fetchone()
    if not bscs:
        sys.exit("The BSCS curriculum program was not found; cannot create grade history.")
    plan = cur.execute("""SELECT cc.year, cc.term, cc.code, cc.course_id FROM curriculum_course cc
                          WHERE cc.program_id=? AND cc.course_id IS NOT NULL ORDER BY cc.year, cc.term, cc.position""",
                       (bscs["id"],)).fetchall()
    course_by_code = {r["code"]: r["id"] for r in cur.execute("SELECT id, code FROM course")}
    code_of = {r["id"]: r["code"] for r in cur.execute("SELECT id, code FROM course")}
    ge_course_ids = [p["course_id"] for p in plan if p["code"].startswith("GE ")]
    for prof, codes in INSTRUCTOR_COURSES.items():
        ids = [course_by_code[c] for c in codes if c in course_by_code]
        if prof == RIZZA:
            ids += ge_course_ids
        for cid in ids:
            changed = cur.execute("UPDATE course SET instructor=? WHERE id=? AND instructor<>?", (prof, cid, prof)).rowcount
            if changed:
                bump("course instructors updated", changed)

    # ---- students
    student_id = {}
    for (num, first, last, gender, birth, residency, year, sec, adm, stype, load, _base) in STUDENTS:
        row = cur.execute("SELECT id FROM student WHERE student_number=?", (num,)).fetchone()
        if not row:
            email = f"{first.lower().replace(' ', '')}.{last.lower().replace(' ', '')}@gmail.com"
            cur.execute("""INSERT INTO student (student_number, first_name, last_name, email, course, year_level, status,
                           section_id, gender, birth_date, residency, student_type, admission_year, enrollment_load)
                           VALUES (?,?,?,?,?,?, 'Active', ?,?,?,?,?,?,?)""",
                        (num, first, last, email, BSCS_NAME, year, section_id[sec], gender, birth.isoformat(),
                         residency, stype, adm, load))
            row = {"id": cur.lastrowid}
            bump("students")
        student_id[num] = row["id"]

    # ---- grade history: every completed term up to the end of the 1st semester of the student's current year
    def grade_for(rng, base, code, key):
        if key in GRADE_OVERRIDES:
            return GRADE_OVERRIDES[key]
        adj = 4 if code.startswith(("PE", "NSTP")) else 0
        value = round(max(77, min(98, base + adj + rng.gauss(0, 3.2))))
        return value, None

    for (num, *_rest) in STUDENTS:
        year, adm, base = _rest[5], _rest[7], _rest[-1]
        # a student's own first school year: year 1 = 2026 - (current year - 1)
        first_sy = CURRENT_SY_START - (year - 1)
        rng = random.Random(f"grades-{num}")
        for item in plan:
            y, term, code, cid = item["year"], item["term"], item["code"], item["course_id"]
            completed = y < year or (y == year and term == "First Semester")
            if not completed:
                continue
            start = first_sy + (y - 1)
            label = {"First Semester": "1st Semester", "Second Semester": "2nd Semester", "Summer": "Summer"}[term] + f" {start}-{start + 1}"
            pct, mark = grade_for(rng, base, code, (num, code))
            if cur.execute("SELECT 1 FROM grade WHERE student_id=? AND course_id=? AND semester=?",
                           (student_id[num], cid, label)).fetchone():
                continue
            cur.execute("INSERT INTO grade (student_id, course_id, grade, semester, mark) VALUES (?,?,?,?,?)",
                        (student_id[num], cid, float(pct), label, mark))
            bump("grades")
    for num, code, label, pct in RETAKES:
        cid = course_by_code[code]
        if not cur.execute("SELECT 1 FROM grade WHERE student_id=? AND course_id=? AND semester=?", (student_id[num], cid, label)).fetchone():
            cur.execute("INSERT INTO grade (student_id, course_id, grade, semester, mark) VALUES (?,?,?,?,NULL)",
                        (student_id[num], cid, float(pct), label))
            bump("grades")

    # ---- current-term final grade per BS5MA student/course (used to keep assessments consistent with them)
    this_term = f"{CURRENT_TERM} {CURRENT_SY_START}-{CURRENT_SY_START + 1}"
    final = {}
    for r in cur.execute("SELECT student_id, course_id, grade FROM grade WHERE semester=?", (this_term,)):
        final[(r["student_id"], r["course_id"])] = r["grade"]

    # ---- assessments (BS5MA, this term) recorded by the Academic staff
    bs5 = [s for s in STUDENTS if s[7] == "BS5MA"]
    dates = {"ww1": datetime(2026, 9, 11, 10, 0), "ww2": datetime(2026, 9, 25, 10, 0),
             "pt": datetime(2026, 10, 2, 14, 0), "qa": datetime(2026, 10, 8, 9, 0)}
    for (num, *_r) in bs5:
        sid = student_id[num]
        rng = random.Random(f"assess-{num}")
        for index, (code, (pt_type, pt_title)) in enumerate(PERFORMANCE_TASKS.items()):
            cid = course_by_code[code]
            target = final.get((sid, cid), 85)
            recorder = "academic.santiago" if index % 2 == 0 else "academic.dizon"
            rows = [
                ("Written Work", "Long Quiz", "Long Quiz 1", 30, dates["ww1"]),
                ("Written Work", "Unit Test", "Unit Test 1", 50, dates["ww2"]),
                ("Performance Task", pt_type, pt_title, 100, dates["pt"]),
                ("Quarterly Assessment", "Prelims Exam", "Prelims Exam", 100, dates["qa"]),
            ]
            for component, category, title, max_score, when in rows:
                if cur.execute("SELECT 1 FROM assessment_score WHERE student_id=? AND course_id=? AND semester=? AND title=?",
                               (sid, cid, this_term, title)).fetchone():
                    continue
                pct = max(62.0, min(100.0, target + rng.gauss(0, 4.5)))
                score = round(pct / 100 * max_score, 1)
                cur.execute("""INSERT INTO assessment_score (student_id, course_id, semester, category, component, title,
                               score, max_score, weight, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,100.0,?,?)""",
                            (sid, cid, this_term, category, component, title, score, float(max_score), recorder, utc(when)))
                bump("assessment scores")

    # ---- attendance (BS5MA): every class meeting from Sep 14 to Oct 14, 2026 according to the timetable
    meetings = {}   # (code, date) -> end time
    start_day = date(2026, 9, 14)
    for offset in range((TODAY - start_day).days + 1):
        d = start_day + timedelta(days=offset)
        for day, start, end, subject, _prof, _room in BS5MA_SCHEDULE:
            if d.strftime("%A") == day:
                meetings[(subject.split("|")[0], d)] = end
    for (num, *_r) in bs5:
        sid = student_id[num]
        rng = random.Random(f"attend-{num}")
        for (code, d), end in sorted(meetings.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            cid = course_by_code[code]
            roll = rng.random()
            status, note = "Present", None
            if roll > 0.98:
                status, note = "Excused", "Excused: medical certificate submitted"
            elif roll > 0.94:
                status, note = "Absent", rng.choice(["No notice", "Family matter", "Sick"])
            elif roll > 0.88:
                status, note = "Late", rng.choice(["Arrived 10 minutes late", "Traffic delay", "Arrived 15 minutes late"])
            recorder = "academic.santiago" if code in ("CS 301", "CS 302", "CS 306", "CS 307") else "academic.dizon"
            hh, mm = map(int, end.split(":"))
            created = utc(datetime.combine(d, time(hh, mm)))
            try:
                cur.execute("""INSERT INTO attendance (student_id, course_id, attendance_date, status, note, recorded_by, created_at)
                               VALUES (?,?,?,?,?,?,?)""", (sid, cid, d.isoformat(), status, note, recorder, created))
                bump("attendance records")
            except sqlite3.IntegrityError:
                pass

    # ---- payments (Accounting)
    used_refs = {r[0] for r in cur.execute("SELECT reference FROM payment")}
    ref_rng = random.Random("neptune-payment-references")

    def new_ref():
        while True:
            ref = str(ref_rng.randint(10_000_000_000, 99_999_999_999))   # exactly 11 digits, as the app requires
            if ref not in used_refs:
                used_refs.add(ref)
                return ref

    def add_payment(sid, ptype, amount, local_dt):
        # already loaded on an earlier run? (same student, type, amount and timestamp)
        if cur.execute("SELECT 1 FROM payment WHERE student_id=? AND payment_type=? AND amount=? AND payment_date=?",
                       (sid, ptype, amount, utc(local_dt))).fetchone():
            return
        cur.execute("INSERT INTO payment (student_id, amount, payment_type, payment_date, reference) VALUES (?,?,?,?,?)",
                    (sid, amount, ptype, utc(local_dt), new_ref()))
        bump("payments")

    def at(d, rng):
        return datetime.combine(d, time(rng.randint(8, 15), rng.randint(0, 59), rng.randint(0, 59)))

    for (num, *_r) in STUDENTS:
        sid = student_id[num]
        rng = random.Random(f"pay-{num}")
        enroll = weekday_between(rng, date(2026, 7, 27), date(2026, 8, 7))
        add_payment(sid, "Tuition", TUITION_INSTALLMENT, at(enroll, rng))
        add_payment(sid, "Miscellaneous", MISC_FEE, at(enroll, rng))
        add_payment(sid, "Laboratory", LAB_FEE, at(enroll, rng))
        paid = PAID_INSTALLMENTS.get(num, 3)
        today_items = TODAY_PAYMENTS.get(num, [])
        today_tuition = any(t == "Tuition" for t, _a, _t in today_items)
        if paid >= 2:
            add_payment(sid, "Tuition", TUITION_INSTALLMENT, at(weekday_between(rng, date(2026, 9, 8), date(2026, 9, 18)), rng))
        if paid >= 3 and not today_tuition:
            add_payment(sid, "Tuition", TUITION_INSTALLMENT, at(weekday_between(rng, date(2026, 10, 5), date(2026, 10, 13)), rng))
        if num in ("2024-0001", "2024-0002", "2023-0003"):
            add_payment(sid, "Other", 150.00, at(weekday_between(rng, date(2026, 8, 17), date(2026, 8, 28)), rng))
        for ptype, amount, t in today_items:
            add_payment(sid, ptype, amount, datetime.combine(TODAY, t))

    # ---- announcements
    for title, body, created in ANNOUNCEMENTS:
        if not cur.execute("SELECT 1 FROM announcement WHERE title=?", (title,)).fetchone():
            cur.execute("INSERT INTO announcement (title, body, author, created_at, is_published) VALUES (?,?, 'admin', ?, 1)",
                        (title, body, created + ".000000"))
            bump("announcements")

    # ---- department messages
    for sender, target, category, subject, body, created, is_read in MESSAGES:
        if sender not in staff_id:
            continue
        if cur.execute("SELECT 1 FROM department_message WHERE sender_id=? AND subject=?", (staff_id[sender], subject)).fetchone():
            continue
        kind, value = target.split(":")
        if kind == "dept":
            role, user_id = value, None
        else:
            user_id = staff_id[value]
            role = cur.execute("SELECT role FROM user WHERE id=?", (user_id,)).fetchone()["role"]
        cur.execute("""INSERT INTO department_message (sender_id, recipient_role, recipient_user_id, subject, category, body,
                       is_read, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                    (staff_id[sender], role, user_id, subject, category, body, int(is_read), utc(created)))
        bump("messages")

    # ---- activity history (admin level, mirrors what the pages themselves would log)
    admin_entries = [f"CREATED STAFF ACCOUNT: {u}, role {r}" for u, r, _m in STAFF]
    admin_entries += [f"CREATED Instructor: {p[0]}" for p in PROFESSORS]
    admin_entries += ["CREATED CLASS SCHEDULE: BS5MA full-week timetable (14 class meetings, 24 hours, Monday-Friday)",
                      "CREATED sample records: 18 students, grade history, assessments, attendance and payments"]
    for i, action in enumerate(admin_entries):
        if not cur.execute("SELECT 1 FROM activity_log WHERE username='admin' AND action=?", (action,)).fetchone():
            when = datetime(2026, 8, 12, 9, 0) + timedelta(minutes=3 * i)
            cur.execute("INSERT INTO activity_log (username, department, action, notification_cleared, created_at) VALUES ('admin','Admin',?,1,?)",
                        (action, utc(when)))
            bump("activity log entries")

    db.commit()
    problems = db.execute("PRAGMA foreign_key_check").fetchall()
    assert not problems, f"foreign key problems: {[tuple(p) for p in problems]}"
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()

    print("\nAdded:" if stats else "\nNothing to add - the sample records are already present.")
    for key, value in stats.items():
        print(f"  {key:<28}{value:>5}")
    print(f"\nNew staff accounts use the password: {STAFF_PASSWORD}   (change it after first login)")


if __name__ == "__main__":
    main()
