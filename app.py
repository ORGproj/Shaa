"""Student Management System - Flask application.

Roles: Registrar (students/sections), Accounting (payments), Academic
(courses/grades/assessments/attendance) and Admin (everything + staff accounts).
"""
import hmac
import json
import math
import os
import random
import re
import secrets
import sqlite3
import threading
import time
import uuid
import zlib
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from markupsafe import Markup
from sqlalchemy import Float, UniqueConstraint, event, false, func, inspect, or_, text, true
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import contains_eager, joinedload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import financial_reports as fr
from curriculum_data import DEFAULT_PROGRAM, PROGRAMS, YEAR_LABELS  # PROGRAMS only seeds the database on first run

# SQLite has no native DECIMAL type: SQLAlchemy keeps NUMERIC values as floats there and rounds
# them back to two places when reading. PostgreSQL (the deployed database) stores exact NUMERIC.
warnings.filterwarnings("ignore", message=r"Dialect .* does \*not\* support Decimal objects natively")

app = Flask(__name__)


# -------------------------
# Configuration
# -------------------------

def _load_secret_key():
    """Load a strong secret; production must configure it explicitly."""
    key = os.environ.get("SECRET_KEY")
    if key:
        if len(key) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 characters.")
        return key
    if os.environ.get("APP_ENV", "development").lower() == "production":
        raise RuntimeError("Set a strong SECRET_KEY environment variable before starting in production.")
    key_file = Path(app.instance_path) / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


database_url = os.environ.get("DATABASE_URL", "sqlite:///student_management.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

# An explicit SESSION_COOKIE_SECURE setting takes precedence over APP_ENV.
# This matters when a developer runs locally over plain HTTP while APP_ENV is
# accidentally set to "production": Secure cookies are never sent over HTTP,
# so Flask would lose the session and reject every CSRF-protected form.
_secure_cookie_override = os.environ.get("SESSION_COOKIE_SECURE")
if _secure_cookie_override is not None:
    _session_cookie_secure = _secure_cookie_override.strip().lower() in {"1", "true", "yes", "on"}
else:
    _session_cookie_secure = os.environ.get("APP_ENV", "development").lower() == "production"

app.config.update(
    SECRET_KEY=_load_secret_key(),
    SQLALCHEMY_DATABASE_URI=database_url,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=str(Path(app.root_path) / "static" / "uploads"),
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_session_cookie_secure,
    SESSION_COOKIE_DOMAIN=None,
    SESSION_COOKIE_PATH="/",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
STUDENT_STATUSES = ("Active", "Inactive", "Graduated")
PAYMENT_TYPES = ("Tuition", "Miscellaneous", "Laboratory", "Other")
ROLES = ("Registrar", "Accounting", "Academic", "Admin")
# Registrar reports: optional demographic / enrollment fields kept on each student record.
GENDERS = ("Female", "Male", "Other / Prefer not to say")
STUDENT_TYPES = ("First-time Freshman", "Transfer")
ENROLLMENT_LOADS = ("Full-time", "Part-time")
PART_TIME_FTE_WEIGHT = 1 / 3          # one part-time student counts as one third of a full-time equivalent
DEFAULT_SECTION_CAPACITY = 40
HIGH_FAIL_RATE = 20.0                 # % failed in a course that gets flagged on the grade distribution report
INFLATION_AVERAGE = 1.50              # a course average at or better than this (with 5+ graded) is flagged for review
ATTENDANCE_STATUSES = ("Present", "Absent", "Late", "Excused")
# Project-configured weighting; confirm institutional policy before official use.
ASSESSMENT_WEIGHTS = {"Written Work": 10.0, "Performance Task": 20.0, "Quarterly Assessment": 70.0}
# The Assessment Type list depends on the chosen component.
ASSESSMENT_TYPES = {
    "Written Work": ("Long Quiz", "Unit Test", "Written Homework", "Essay"),
    "Performance Task": ("Skills Demonstration", "Group Presentation", "Role-Playing", "Laboratory Experiment",
                         "Multimedia Project", "Product Output"),
    "Quarterly Assessment": ("Prelims Exam", "Midterm Exam", "Final Exam"),
}
ASSESSMENT_CATEGORIES = tuple(t for types in ASSESSMENT_TYPES.values() for t in types)

# Grading system (percentage rating -> grade equivalent), from the school's Grade Report Form.
# Each row: (lowest whole-number percentage, grade, description). Below the last row = 5.00 Failed.
GRADING_SCALE = (
    (98, 1.00, "Excellent"), (95, 1.25, "Superior"), (92, 1.50, "Very Good"), (89, 1.75, "Good"),
    (86, 2.00, "Meritorious"), (83, 2.25, "Very Satisfactory"), (80, 2.50, "Satisfactory"),
    (77, 2.75, "Fairly Satisfactory"), (75, 3.00, "Passed"),
)
GRADING_SCALE_LABELS = ("98-100", "95-97", "92-94", "89-91", "86-88", "83-85", "80-82", "77-79", "75-76")
FAILING_GRADE_EQUIVALENT = 5.00
# Special marks that replace a numeric grade. counts = included in averages (as 5.00); the others are not graded.
SPECIAL_MARKS = {
    "INC": ("Incomplete", False, "INCOMPLETE"),
    "AW": ("Authorized Withdrawal / Dropped", False, "DROPPED"),
    "UW": ("Unauthorized Withdrawal", True, "FAILED (UW)"),
    "NCA": ("No Credit Due to Absences", True, "FAILED (NCA)"),
}
TERM_OPTIONS = ["1st Semester", "2nd Semester", "Summer", "Quarter 1", "Quarter 2", "Quarter 3", "Quarter 4"]
USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{3,50}")
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

db = SQLAlchemy(app)


@event.listens_for(Engine, "connect")
def _tune_sqlite(dbapi_connection, _record):
    """SQLite only: let readers and one writer overlap (WAL) and make writers wait
    for the lock instead of failing at once with 'database is locked'."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


# -------------------------
# Time handling
# -------------------------
# Timestamps are stored in UTC and converted to the school's local time for
# display and for "today" / date-range filters.

try:
    LOCAL_TZ = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Manila"))
except ZoneInfoNotFoundError:  # tzdata missing or bad APP_TIMEZONE
    app.logger.warning("Timezone not found; falling back to UTC. Install 'tzdata' or fix APP_TIMEZONE.")
    LOCAL_TZ = timezone.utc


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_today():
    return datetime.now(LOCAL_TZ).date()


def local_day_range_utc(day):
    """Return the naive-UTC [start, end) bounds of a local calendar day."""
    def to_utc(d):
        return datetime.combine(d, dtime.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
    return to_utc(day), to_utc(day + timedelta(days=1))


def school_year_start():
    """School years start around June: Oct 2026 -> 2026, Mar 2027 -> 2026."""
    today = local_today()
    return today.year if today.month >= 6 else today.year - 1


@app.template_filter("localdt")
def localdt(value, fmt="%b %d, %Y · %I:%M %p"):
    if not value:
        return "-"
    if value.tzinfo is None:  # SQLite and our own columns store naive UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).strftime(fmt)


# -------------------------
# Database models
# -------------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    profile_image = db.Column(db.String(255), nullable=True)
    # JSON-encoded action categories this account may view in System Activity History.
    activity_visibility = db.Column(db.Text, nullable=True)
    # JSON list of departments this non-admin account may audit.
    activity_departments = db.Column(db.Text, nullable=True)
    # JSON map of module -> allowed actions. NULL preserves legacy role permissions.
    access_permissions = db.Column(db.Text, nullable=True)
    can_manage_teachers_timetable = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    failed_login_count = db.Column(db.Integer, nullable=False, default=0, server_default=text("0"))
    login_locked = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    locked_until = db.Column(db.DateTime, nullable=True)          # temporary lock expiry (UTC)
    last_failed_login_at = db.Column(db.DateTime, nullable=True)  # start of the current failure window (UTC)
    security_notifications_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=true())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    subjects = db.Column(db.String(255), nullable=False)
    employment_type = db.Column(db.String(20), nullable=False, default="Full-time")
    working_days = db.Column(db.String(100), nullable=False, default="Monday,Tuesday,Wednesday,Thursday,Friday")
    available_start = db.Column(db.String(5), nullable=False, default="07:00")
    available_end = db.Column(db.String(5), nullable=False, default="17:00")


class ClassSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    subject = db.Column(db.String(120), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("teacher.id", ondelete="RESTRICT"), nullable=False)
    classroom = db.Column(db.String(80), nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id", ondelete="RESTRICT"), nullable=False)
    teacher = db.relationship("Teacher")
    section = db.relationship("Section")


class ScheduleLock(db.Model):
    """A single row that every timetable write locks before it checks for clashes.

    Overlapping time ranges cannot be expressed as a plain UNIQUE constraint, so two requests that
    both pass the clash check could otherwise both insert and double-book a room, instructor or
    section. Updating this one row takes a write lock (SQLite) / row lock (PostgreSQL) that is held
    until commit or rollback, so timetable writes run one at a time, across threads and workers."""
    id = db.Column(db.Integer, primary_key=True)
    version = db.Column(db.Integer, nullable=False, default=0)


class Section(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    year_level = db.Column(db.Integer, nullable=False, default=1)
    capacity = db.Column(db.Integer, nullable=False, default=DEFAULT_SECTION_CAPACITY, server_default=text(str(DEFAULT_SECTION_CAPACITY)))


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_number = db.Column(db.String(30), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    course = db.Column(db.String(100), nullable=False)
    year_level = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), default="Active", nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)
    section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=True)
    # Optional fields used by the Registrar's enrollment and statistical reports.
    gender = db.Column(db.String(30), nullable=True)
    birth_date = db.Column(db.Date, nullable=True)
    residency = db.Column(db.String(100), nullable=True)  # province / city / state the student lives in
    student_type = db.Column(db.String(30), nullable=False, default="First-time Freshman", server_default="First-time Freshman")
    admission_year = db.Column(db.String(9), nullable=True)  # school year first enrolled, e.g. 2026-2027
    enrollment_load = db.Column(db.String(20), nullable=False, default="Full-time", server_default="Full-time")

    section = db.relationship("Section")
    payments = db.relationship("Payment", backref="student", lazy=True, cascade="all, delete-orphan")
    grades = db.relationship("Grade", backref="student", lazy=True, cascade="all, delete-orphan")
    assessment_scores = db.relationship("AssessmentScore", back_populates="student", lazy=True, cascade="all, delete-orphan")
    attendance_records = db.relationship("Attendance", back_populates="student", lazy=True, cascade="all, delete-orphan")


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    units = db.Column(db.Integer, nullable=False)
    instructor = db.Column(db.String(120), nullable=False)


class CurriculumProgram(db.Model):
    """A degree program whose curriculum plan is shown (and edited) on the Curriculum page."""
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False)
    short = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    reference = db.Column(db.String(300), nullable=False, default="")
    draft_all = db.Column(db.Boolean, nullable=False, default=False)
    draft_note = db.Column(db.Text, nullable=False, default="")
    position = db.Column(db.Integer, nullable=False, default=0)
    courses = db.relationship("CurriculumCourse", backref="program", lazy=True, cascade="all, delete-orphan",
                              order_by="CurriculumCourse.position")


class CurriculumCourse(db.Model):
    """One row of a curriculum plan: a course placed in a year and term of a program."""
    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey("curriculum_program.id", ondelete="CASCADE"), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False)
    term = db.Column(db.String(30), nullable=False)
    code = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    units = db.Column(db.Integer, nullable=False)
    prereq = db.Column(db.String(200), nullable=False, default="NONE")
    draft = db.Column(db.Boolean, nullable=False, default=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    # The Course List entry this curriculum row is linked to (used to filter courses in Grades / Assessments).
    course_id = db.Column(db.Integer, db.ForeignKey("course.id", ondelete="SET NULL"), nullable=True, index=True)
    course = db.relationship("Course")


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)  # exact money, never a float
    payment_type = db.Column(db.String(50), nullable=False)
    payment_date = db.Column(db.DateTime, default=utcnow, nullable=False)
    reference = db.Column(db.String(32), unique=True, nullable=False)


class FinancialReport(db.Model):
    """A saved Accounting report for one period (a year), or one student's billing statement.
    ``data`` holds the editable lines as JSON; totals are always recalculated, never stored."""
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(30), nullable=False)
    period = db.Column(db.String(30), nullable=False)  # "2026", or a student number for billing statements
    data = db.Column(db.Text, nullable=False, default="{}")
    updated_by = db.Column(db.String(50), nullable=False, default="system")
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("kind", "period", name="uq_financial_report_kind_period"),)


class Grade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    grade = db.Column(db.Float, nullable=False)  # percentage rating 0-100 (0 when a special mark is used)
    semester = db.Column(db.String(50), nullable=False)
    mark = db.Column(db.String(5))  # INC / AW / UW / NCA, or NULL for a normal numeric grade

    # The route-level duplicate check improves the user experience, but only a
    # database constraint can reliably close the race where two requests both
    # pass that check before either transaction commits.
    __table_args__ = (UniqueConstraint(
        "student_id", "course_id", "semester",
        name="uq_grade_student_course_semester",
    ),)

    course = db.relationship("Course")

    @property
    def equivalent(self):
        """Grade on the 1.00-5.00 scale, or None when the record is not graded (INC / AW)."""
        return grade_equivalent(self.grade, self.mark)

    @property
    def shown(self):
        """What to print in a Grade column: '1.50', 'INC', 'UW' ..."""
        return self.mark or (f"{self.equivalent:.2f}" if self.equivalent is not None else "-")

    @property
    def description(self):
        return grade_description(self.grade, self.mark)

    @property
    def remark(self):
        return grade_remark(self.grade, self.mark)


class AssessmentScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    semester = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # Quiz / Exam / Project / Assignment
    component = db.Column(db.String(30), nullable=False, default="Written Work")
    title = db.Column(db.String(120), nullable=False)
    score = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, nullable=False)
    weight = db.Column(db.Float, nullable=False, default=100.0)  # legacy column, no longer used
    created_by = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    student = db.relationship("Student", back_populates="assessment_scores")
    course = db.relationship("Course")


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id", ondelete="CASCADE"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id", ondelete="CASCADE"), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False, default=local_today)
    status = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(250), nullable=True)
    recorded_by = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    student = db.relationship("Student", back_populates="attendance_records")
    course = db.relationship("Course")
    __table_args__ = (UniqueConstraint("student_id", "course_id", "attendance_date", name="uq_attendance_student_course_date"),)


class FormToken(db.Model):
    """One-time token issued with a form. The primary key makes the database reject a
    second submission of the same form, even when both requests arrive at the same instant
    (double-click, retry, or two browser tabs)."""
    token = db.Column(db.String(64), primary_key=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class DepartmentMessage(db.Model):
    """Internal requests/messages routed to a department inbox."""
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_role = db.Column(db.String(30), nullable=False, index=True)
    # When set, this is a private message visible only to this account and its sender.
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True)
    attachments = db.Column(db.Text, nullable=True)  # JSON list of private attachment metadata
    recipient_user = db.relationship("User", foreign_keys=[recipient_user_id])
    subject = db.Column(db.String(140), nullable=False)
    category = db.Column(db.String(40), nullable=False, default="General")
    body = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    archived_by_sender = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    archived_by_recipient = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    deleted_by_sender = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    deleted_by_recipient = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    sender = db.relationship("User", foreign_keys=[sender_id])


class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    is_published = db.Column(db.Boolean, nullable=False, default=True, server_default=true())


class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False)
    # Snapshot the department at the time of the event so department history stays isolated.
    department = db.Column(db.String(30), nullable=True, index=True)
    action = db.Column(db.String(255), nullable=False)
    notification_cleared = db.Column(db.Boolean, nullable=False, default=False, server_default=false())
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


# -------------------------
# Helpers: authentication, CSRF, validation
# -------------------------

def current_user():
    if "_user" not in g:
        user_id = session.get("user_id")
        g._user = db.session.get(User, user_id) if user_id else None
    return g._user


@app.context_processor
def inject_current_user():
    failed_alert_count = 0
    user = current_user()
    if user and user.role == "Admin":
        try:
            failed_alert_count = ActivityLog.query.filter(
                ActivityLog.action.ilike("%FAILED_LOGIN%"),
                ActivityLog.notification_cleared.is_(False),
                ActivityLog.created_at >= utcnow() - timedelta(hours=24)
            ).count()
        except Exception:
            db.session.rollback()
    unread_messages = 0
    if user:
        try:
            unread_messages = DepartmentMessage.query.filter(
                DepartmentMessage.is_read.is_(False),
                DepartmentMessage.deleted_by_recipient.is_(False),
                DepartmentMessage.archived_by_recipient.is_(False),
                or_(DepartmentMessage.recipient_user_id == user.id,
                    (DepartmentMessage.recipient_user_id.is_(None)) & (DepartmentMessage.recipient_role == user.role))
            ).count()
        except Exception:
            db.session.rollback()
    return {"current_user": user, "failed_alert_count": failed_alert_count,
            "security_notifications_enabled": bool(user and user.security_notifications_enabled),
            "unread_messages": unread_messages}


def is_logged_in():
    return current_user() is not None


ACCESS_MODULES = {
    "dashboard": "dashboard", "activity_report": "activity_history",
    "sections": "sections", "delete_section": "sections",
    "students": "students", "add_student": "students", "student_detail": "students",
    "edit_student": "students", "delete_student": "students",
    "payments": "payments", "financial_reports": "financial_reports", "financial_report": "financial_reports",
    "delete_financial_report": "financial_reports", "billing_statement": "financial_reports", "courses": "courses", "delete_course": "courses",
    "grades": "grades", "delete_grade": "grades", "report_card": "grades",
    "reports": "reports", "report_enrollment": "reports", "report_schedule": "reports",
    "report_grades": "reports", "report_clearance": "reports",
    "curriculum": "curriculum", "add_curriculum_course": "curriculum", "edit_curriculum_course": "curriculum",
    "delete_curriculum_course": "curriculum", "add_curriculum_program": "curriculum",
    "edit_curriculum_program": "curriculum", "delete_curriculum_program": "curriculum",
    "assessments": "assessments",
    "delete_assessment": "assessments", "attendance": "attendance",
    "teachers": "instructors", "delete_teacher": "instructors",
    "timetable": "timetable", "delete_schedule": "timetable",
    "messages": "messages", "open_message": "messages", "manage_message": "messages", "download_message_attachment": "messages",
    "concurrency": "concurrency", "manage_account": "account",
    "login_security": "security", "toggle_security_notifications": "security",
    "staff_management": "staff_accounts", "delete_staff": "staff_accounts",
}
ACCESS_ACTIONS = ("view", "create", "edit", "delete")
ACCESS_MODULE_LABELS = {
    "dashboard": "Dashboard", "students": "Students", "sections": "Sections",
    "payments": "Payments", "financial_reports": "Financial Reports", "courses": "Courses", "curriculum": "Curriculum", "grades": "Grades",
    "assessments": "Assessments", "attendance": "Attendance", "reports": "Registrar Reports",
    "instructors": "Instructors", "timetable": "Class Timetable",
    "messages": "Department Messages", "activity_history": "System Activity History",
    "staff_accounts": "Staff Accounts", "security": "Login & Security",
    "concurrency": "Concurrency Demo", "account": "Account Settings",
}

def default_access_for_role(role, user=None):
    """Return a least-surprise permission matrix matching the existing role model."""
    result = {module: [] for module in ACCESS_MODULE_LABELS}
    def grant(module, *actions): result[module] = list(actions)
    if role == "Admin":
        return {module: list(ACCESS_ACTIONS) for module in ACCESS_MODULES.values()}
    if role == "Registrar":
        grant("dashboard", "view"); grant("students", "view", "create", "edit", "delete")
        grant("sections", "view", "create", "edit", "delete"); grant("grades", "view")  # read-only: grade changes belong to Academic
        grant("courses", "view")  # read-only course list, as the navigation has always shown
        grant("activity_history", "view"); grant("messages", "view", "create", "edit", "delete"); grant("account", "view", "edit")
        grant("curriculum", "view"); grant("reports", "view")
    elif role == "Accounting":
        grant("dashboard", "view"); grant("payments", "view", "create", "edit"); grant("activity_history", "view")
        grant("financial_reports", "view", "create", "edit", "delete")
        grant("messages", "view", "create", "edit", "delete"); grant("account", "view", "edit")
    elif role == "Academic":
        grant("dashboard", "view"); grant("students", "view"); grant("courses", "view", "create", "edit", "delete")
        grant("curriculum", "view")
        grant("grades", "view", "create", "edit", "delete"); grant("assessments", "view", "create", "edit", "delete")
        grant("attendance", "view", "create", "edit"); grant("activity_history", "view"); grant("account", "view", "edit")
        grant("messages", "view", "create", "edit", "delete")  # any role could already send and manage its own messages
    grant("concurrency", "view")  # the demo page has always been open to every signed-in account
    if user and user.can_manage_teachers_timetable:
        grant("instructors", "view", "create", "edit", "delete"); grant("timetable", "view", "create", "edit", "delete")
    return result

def get_access_permissions(user):
    if not user or not user.access_permissions:
        return None
    try:
        value = json.loads(user.access_permissions)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


# Modules that can never be delegated: whoever holds them could grant themselves Admin.
ADMIN_ONLY_MODULES = frozenset({"staff_accounts", "security"})


def effective_permissions(user):
    """The permission matrix that actually applies to this user.

    A saved matrix always wins. Accounts without one (created before the matrix existed) fall back to
    their role's defaults, so the navigation, the pages and the server checks all agree.
    """
    if not user:
        return {}
    saved = get_access_permissions(user)
    return saved if saved is not None else default_access_for_role(user.role, user)

# The form field that carries the ID of the record being EDITED on each route. Foreign-key fields such
# as course_id or section_id on other forms (grades, attendance, students, timetable) are references,
# not record IDs, so they must not make a "create" look like an "edit".
ACCESS_RECORD_KEYS = {
    "sections": "section_id", "courses": "course_id", "grades": "grade_id", "assessments": "score_id",
    "teachers": "teacher_id", "timetable": "schedule_id", "staff_management": "user_id",
    "financial_report": "report_id", "billing_statement": "report_id",
}
# POST routes whose action is fixed by what they do, not by their fields.
ACCESS_POST_ACTIONS = {"manage_account": "edit", "toggle_security_notifications": "edit", "open_message": "view"}


def required_access_action(endpoint=None):
    endpoint = endpoint or request.endpoint or ""
    if endpoint.startswith("add_"):
        return "create"  # the add form itself needs create access, not just view
    if endpoint.startswith(("edit_", "update_")):
        return "edit"
    if request.method == "GET":
        return "edit" if request.args.get("edit") else "view"
    if endpoint.startswith("delete_"):
        return "delete"
    if endpoint == "manage_message":
        return "delete" if (request.view_args or {}).get("action") == "delete" else "edit"
    if endpoint in ACCESS_POST_ACTIONS:
        return ACCESS_POST_ACTIONS[endpoint]
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if endpoint.startswith(("edit_", "update_")):
            return "edit"
        record_key = ACCESS_RECORD_KEYS.get(endpoint)
        return "edit" if record_key and request.form.get(record_key) else "create"
    return "view"


def has_module_access(user, module, action):
    if not user:
        return False
    if user.role == "Admin":
        return True
    if module in ADMIN_ONLY_MODULES:
        return False
    permissions = effective_permissions(user)
    if module == "curriculum" and "curriculum" not in permissions:
        # Matrices saved before the Curriculum module existed: keep read access from Courses, never write access.
        return action == "view" and has_module_access(user, "courses", "view")
    if module == "reports" and "reports" not in permissions:
        # Matrices saved before Registrar Reports existed: Registrar accounts keep view access.
        return action == "view" and user.role == "Registrar"
    actions = permissions.get(module, [])
    if actions is True or actions == "all":
        return True
    if isinstance(actions, dict):
        return bool(actions.get(action) or actions.get("all"))
    return isinstance(actions, list) and (action in actions or "all" in actions)

def roles_required(*roles):
    """Gate a view on the Admin-granted module permission matrix.

    `roles` lists the departments that normally own the page. A user from any department is let in
    when the matrix grants the action this request needs (view / create / edit / delete). Routes
    declared Admin-only stay Admin-only unless their module is delegable (see ADMIN_ONLY_MODULES).
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please sign in to continue.", "warning")
                target = request.full_path.rstrip("?") if request.method == "GET" else None
                return redirect(url_for("login", next=target))
            if user.role == "Admin":
                return view(*args, **kwargs)
            endpoint = request.endpoint or view.__name__
            module = ACCESS_MODULES.get(endpoint)
            if roles == ("Admin",) and (not module or module in ADMIN_ONLY_MODULES):
                flash("Only an Admin can access that page.", "danger")
                return _error_page(403, "Access Denied", "Your account does not have the required module permission.")
            if module:
                action = required_access_action(endpoint)
                if not has_module_access(user, module, action):
                    return _error_page(403, "Access Denied", f"Your account does not have {action} access to this module.")
            elif roles and user.role not in roles:
                return _error_page(403, "Access Denied", "Your account does not have the required module permission.")
            return view(*args, **kwargs)
        return wrapped
    return decorator


def can(module, action="view"):
    """Template helper: may the signed-in user perform `action` in `module`?"""
    return has_module_access(current_user(), module, action)


app.jinja_env.globals["can"] = can


def log_activity(action):
    user = current_user()
    if user:
        db.session.add(ActivityLog(username=user.username, department=user.role, action=action[:255]))
        db.session.commit()


def log_auth_attempt(username, action, department="Security"):
    """Record authentication events without storing passwords or other secrets."""
    try:
        db.session.add(ActivityLog(username=(username or "unknown")[:50], department=department,
                                   action=action[:255]))
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Could not save authentication audit event")


def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = session["_csrf"] = secrets.token_urlsafe(32)
    return token


app.jinja_env.globals["csrf_input"] = lambda: Markup(f'<input type="hidden" name="csrf_token" value="{csrf_token()}">')


@app.before_request
def protect_against_csrf():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken") or ""
        expected = session.get("_csrf", "")
        if not expected or not sent or not hmac.compare_digest(sent, expected):
            # Log only presence/route metadata, never the token itself. This makes
            # session-cookie problems diagnosable without exposing CSRF secrets.
            app.logger.warning(
                "CSRF rejected method=%s path=%s form_token_present=%s session_token_present=%s "
                "session_cookie_present=%s secure_cookie=%s host=%s",
                request.method, request.path, bool(sent), bool(expected),
                bool(request.cookies.get(app.config.get("SESSION_COOKIE_NAME", "session"))),
                app.config.get("SESSION_COOKIE_SECURE"), request.host,
            )
            # Keep CSRF protection enabled. Reloading cannot fix a cookie that the
            # browser refuses to send (for example Secure cookie over local HTTP).
            return render_template(
                "error.html", code=400, title="Session Expired",
                message=("Your form security token could not be verified. For local development, "
                         "open the app using the same address you used to log in (for example, "
                         "always use http://127.0.0.1:5000, not a mix of localhost and 127.0.0.1). "
                         "If you run over plain HTTP, set SESSION_COOKIE_SECURE=0 and restart the app. "
                         "Then log in again and retry. Your request was not processed."),
            ), 400


# Simple in-memory login throttle (per IP + username). Per-process only, which is
# fine for a school project; use a shared store if you run several workers.
_failed_logins = {}
_failed_lock = threading.Lock()
MAX_LOGIN_FAILURES = 5          # per IP + username before that IP has to wait (in memory)
LOGIN_WINDOW_SECONDS = 300
# Account-wide lock (stored in the database, so it works across workers and restarts). It is
# deliberately higher than the per-IP limit: one attacker address is slowed down first and
# cannot lock a victim out on its own, and the lock expires by itself instead of being permanent.
ACCOUNT_LOCK_THRESHOLD = 10
try:
    LOGIN_LOCKOUT_MINUTES = max(1, int(os.environ.get("LOGIN_LOCKOUT_MINUTES", "15")))
except ValueError:
    LOGIN_LOCKOUT_MINUTES = 15


def _throttle_key(username):
    return (request.remote_addr or "?", username.lower())


def login_wait_seconds(key):
    now = time.time()
    with _failed_lock:
        recent = [t for t in _failed_logins.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
        _failed_logins[key] = recent
        if len(recent) >= MAX_LOGIN_FAILURES:
            return int(LOGIN_WINDOW_SECONDS - (now - recent[0])) + 1
    return 0


def record_login_failure(key):
    with _failed_lock:
        _failed_logins.setdefault(key, []).append(time.time())


def clear_login_failures(key):
    with _failed_lock:
        _failed_logins.pop(key, None)


def safe_next_url(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


@app.after_request
def set_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    # HSTS is only sent in production, where HTTPS is required by the hosting platform.
    if os.environ.get("APP_ENV", "development").lower() == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"  # don't show cached pages after logout
    return response


def clean_text(value):
    return (value or "").strip()


def parse_float(value, minimum=None, maximum=None):
    number = float(clean_text(value).replace(",", ""))
    if not math.isfinite(number):
        raise ValueError("Enter a valid number.")
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        raise ValueError("Number is out of range.")
    return number


def parse_money(value, minimum=Decimal("0.01"), maximum=Decimal("100000000")):
    """Parse a peso amount into an exact two-decimal Decimal (never a float)."""
    raw = clean_text(value).replace(",", "").replace("₱", "").strip()
    try:
        amount = Decimal(raw)
        if not amount.is_finite():
            raise InvalidOperation
        if amount < minimum or amount > maximum:
            raise ValueError("Number is out of range.")
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError("Enter a valid number.") from None


def parse_year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise ValueError("Choose a valid year level.") from None
    if year not in range(1, 5):
        raise ValueError("Choose a valid year level.")
    return year


def get_or_none(model, raw_id):
    try:
        return db.session.get(model, int(raw_id)) if raw_id not in (None, "") else None
    except (TypeError, ValueError):
        return None


def commit_with_retry(make_object, attempts=8):
    """Add a freshly built object, retrying if a generated unique value collides.

    Under a burst of simultaneous requests several of them can pick the same "next"
    number. Each loser rolls back, waits a short random time (so the retries do not
    collide again in lock-step) and rebuilds the object with a fresh number.
    """
    for attempt in range(attempts):
        obj = make_object()
        db.session.add(obj)
        try:
            db.session.commit()
            return obj
        except IntegrityError:
            db.session.rollback()
            time.sleep(random.uniform(0.01, 0.05) * (attempt + 1))
    raise ValueError("Could not save the record because a unique number was already taken. Please try again.")


# -------------------------
# Helpers: uploads and identifiers
# -------------------------

_IMAGE_SIGNATURES = {
    "png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    "jpg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
}


def save_image(file, prefix):
    """Validate (extension + file signature) and store an uploaded image."""
    if not file or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower().lstrip(".")
    kind = "jpg" if ext == "jpeg" else ext
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Upload a PNG, JPG, JPEG, or WEBP image.")
    head = file.stream.read(16)
    file.stream.seek(0)
    if not _IMAGE_SIGNATURES[kind](head):
        raise ValueError("That file does not look like a valid image.")
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    name = f"{prefix}_{uuid.uuid4().hex[:16]}.{ext}"
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], name))
    return name


def delete_upload(filename):
    """Remove an uploaded image if no student/user record still uses it."""
    if not filename:
        return
    in_use = (Student.query.filter_by(image_filename=filename).first()
              or User.query.filter_by(profile_image=filename).first())
    if in_use:
        return
    try:
        (Path(app.config["UPLOAD_FOLDER"]) / Path(filename).name).unlink(missing_ok=True)
    except OSError:
        app.logger.warning("Could not delete upload %s", filename)


def new_form_token():
    return secrets.token_urlsafe(16)


def consume_form_token(token):
    """Atomically use up a form token; raise ValueError if it was already used."""
    token = (token or "").strip()
    if not token or len(token) > 64:
        raise ValueError("This form has expired. Reload the page and try again.")
    try:
        db.session.add(FormToken(token=token))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError("This payment was already submitted. Check the transaction history before trying again.") from None
    # Housekeeping: drop tokens older than two days (cheap, keeps the table tiny).
    try:
        FormToken.query.filter(FormToken.created_at < utcnow() - timedelta(days=2)).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()


def generate_student_number():
    prefix = f"{local_today().year}-"
    numbers = []
    for (value,) in db.session.query(Student.student_number).filter(Student.student_number.like(f"{prefix}%")):
        try:
            numbers.append(int(value.split("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}{max(numbers, default=0) + 1:04d}"


def generate_payment_reference():
    """Generate a unique, exactly 11-digit numeric payment reference."""
    for _ in range(100):
        # 10-digit range with a non-zero leading digit => exactly 11 digits.
        reference = str(secrets.randbelow(90_000_000_000) + 10_000_000_000)
        if not Payment.query.filter_by(reference=reference).first():
            return reference
    raise ValueError("Could not generate a unique payment reference. Please try again.")


def normalize_payment_references():
    """Convert legacy references to unique 11-digit numeric references."""
    used = set()
    payments = Payment.query.order_by(Payment.id.asc()).all()
    for payment in payments:
        current = str(payment.reference or "")
        if re.fullmatch(r"[1-9][0-9]{10}", current) and current not in used:
            used.add(current)
            continue
        for _ in range(100):
            candidate = str(secrets.randbelow(90_000_000_000) + 10_000_000_000)
            if candidate not in used:
                used.add(candidate)
                payment.reference = candidate
                break
        else:
            raise RuntimeError("Could not assign a unique numeric payment reference.")
    db.session.commit()


def find_student_by_lookup(lookup):
    """Accept '2026-0001', or the datalist text '2026-0001 - First Last'."""
    number = clean_text(lookup).split(" - ")[0].strip()
    if not number:
        return None
    return Student.query.filter(func.lower(Student.student_number) == number.lower()).first()


# -------------------------
# Grading system helpers (1.00 - 5.00 scale)
# -------------------------

def percentage_to_equivalent(percentage):
    """Percentage rating -> (grade, description). Rounded to a whole percent first, as on the school's form."""
    whole = int(Decimal(str(percentage)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    for lowest, grade, description in GRADING_SCALE:
        if whole >= lowest:
            return grade, description
    return FAILING_GRADE_EQUIVALENT, "Failed"


def grade_equivalent(percentage, mark=None):
    if mark:
        return FAILING_GRADE_EQUIVALENT if SPECIAL_MARKS.get(mark, ("", False, ""))[1] else None
    return percentage_to_equivalent(percentage)[0]


def grade_description(percentage, mark=None):
    if mark:
        return SPECIAL_MARKS.get(mark, (mark,))[0]
    return percentage_to_equivalent(percentage)[1]


def grade_remark(percentage, mark=None):
    if mark:
        return SPECIAL_MARKS.get(mark, ("", False, mark))[2]
    return "PASSED" if percentage_to_equivalent(percentage)[0] < FAILING_GRADE_EQUIVALENT else "FAILED"


def grade_is_passed(percentage, mark=None):
    return not mark and percentage_to_equivalent(percentage)[0] < FAILING_GRADE_EQUIVALENT


app.jinja_env.globals["equiv"] = lambda percentage: percentage_to_equivalent(percentage)


def grading_scale_rows():
    """Rows for the printed legend: percentage range, grade, description."""
    rows = [(label, f"{grade:.2f}", description)
            for label, (_low, grade, description) in zip(GRADING_SCALE_LABELS, GRADING_SCALE)]
    rows.append(("74 & below", f"{FAILING_GRADE_EQUIVALENT:.2f}", "Failed / UW / NCA"))
    return rows


def split_semester(label):
    """'1st Semester 2026-2027' -> ('1st Semester', '2026-2027'); (None, None) if it does not follow the pattern."""
    for term in TERM_OPTIONS:
        if (label or "").startswith(term + " "):
            year = label[len(term) + 1:]
            if re.fullmatch(r"\d{4}-\d{4}", year):
                return term, year
    return None, None


def semester_picker_context(existing_label=None):
    """Values for the point-and-click Semester / Period + School Year selects used by Grades and Assessments."""
    start = school_year_start()
    years = [f"{year}-{year + 1}" for year in range(start - 2, start + 6)]
    term, year = split_semester(existing_label)
    selected_term, selected_year = term or TERM_OPTIONS[0], year or f"{start}-{start + 1}"
    if selected_year not in years:
        years.append(selected_year)
        years.sort()
    return {"term_options": TERM_OPTIONS, "school_year_options": years,
            "selected_term": selected_term, "selected_school_year": selected_year}


def read_semester_form(form, term_field="semester_term", year_field="school_year"):
    term, school_year = clean_text(form.get(term_field)), clean_text(form.get(year_field))
    if term not in TERM_OPTIONS or not re.fullmatch(r"\d{4}-\d{4}", school_year):
        raise ValueError("Choose a semester / period and school year.")
    return f"{term} {school_year}"


def semester_suggestions():
    found = {row[0] for row in db.session.query(Grade.semester)}
    found |= {row[0] for row in db.session.query(AssessmentScore.semester)}
    start = school_year_start()
    found |= {f"{term} {start}-{start + 1}" for term in TERM_OPTIONS[:2]}
    return sorted(found)


# -------------------------
# Student form helpers
# -------------------------

_STUDENT_LIMITS = {"first_name": 80, "last_name": 80, "email": 120, "course": 100}
REPORT_FORM_FIELDS = ("gender", "birth_date", "residency", "student_type", "admission_year", "enrollment_load")


def parse_student_form(form, existing_program=None):
    data = {key: clean_text(form.get(key)) for key in _STUDENT_LIMITS}
    if not all(data.values()):
        raise ValueError("Please complete all required fields.")
    # "course" holds the student's DEGREE PROGRAM (managed on the Curriculum page), not a subject.
    # An unchanged legacy value on an existing student is still accepted so old records can be re-saved.
    if data["course"] != existing_program and not CurriculumProgram.query.filter_by(name=data["course"]).first():
        raise ValueError("Choose a degree program from the list.")
    if any(len(data[key]) > limit for key, limit in _STUDENT_LIMITS.items()):
        raise ValueError("One of the fields is too long.")
    if not EMAIL_RE.fullmatch(data["email"]):
        raise ValueError("Enter a valid email address.")
    data["year_level"] = parse_year(form.get("year_level"))
    data["status"] = form.get("status", "Active")
    if data["status"] not in STUDENT_STATUSES:
        raise ValueError("Choose a valid status.")
    data["section_id"] = form.get("section_id", type=int) or None
    if data["section_id"] and not db.session.get(Section, data["section_id"]):
        raise ValueError("Choose a valid section.")
    data.update(parse_report_fields(form))
    return data


def parse_report_fields(form):
    """Optional demographic / enrollment fields used by the Registrar reports."""
    gender = clean_text(form.get("gender"))
    if gender and gender not in GENDERS:
        raise ValueError("Choose a valid gender option.")
    birth_date = None
    raw_birth = clean_text(form.get("birth_date"))
    if raw_birth:
        try:
            birth_date = date.fromisoformat(raw_birth)
        except ValueError:
            raise ValueError("Enter a valid birth date.")
        if birth_date >= local_today() or birth_date.year < 1920:
            raise ValueError("Birth date must be in the past and after 1920.")
    residency = clean_text(form.get("residency"))
    if len(residency) > 100:
        raise ValueError("Residency is too long (100 characters maximum).")
    student_type = clean_text(form.get("student_type")) or STUDENT_TYPES[0]
    load = clean_text(form.get("enrollment_load")) or ENROLLMENT_LOADS[0]
    if student_type not in STUDENT_TYPES or load not in ENROLLMENT_LOADS:
        raise ValueError("Choose a valid student type and enrollment load.")
    admission_year = clean_text(form.get("admission_year")) or f"{school_year_start()}-{school_year_start() + 1}"
    match = re.fullmatch(r"(\d{4})-(\d{4})", admission_year)
    if not match or int(match.group(2)) != int(match.group(1)) + 1:
        raise ValueError("Admission year must look like 2026-2027.")
    return {"gender": gender or None, "birth_date": birth_date, "residency": residency or None,
            "student_type": student_type, "admission_year": admission_year, "enrollment_load": load}


def render_student_form(student=None, form=None):
    """Render the add/edit form, keeping what the user typed after an error."""
    if form:
        values = {key: clean_text(form.get(key)) for key in _STUDENT_LIMITS}
        values.update(year_level=form.get("year_level", type=int) or 1, status=form.get("status", "Active"),
                      section_id=form.get("section_id", type=int))
        values.update({key: clean_text(form.get(key)) for key in REPORT_FORM_FIELDS})
    elif student:
        values = {key: getattr(student, key) for key in [*_STUDENT_LIMITS, "year_level", "status", "section_id"]}
        values.update({key: getattr(student, key) or "" for key in REPORT_FORM_FIELDS})
        values["birth_date"] = student.birth_date.isoformat() if student.birth_date else ""
    else:
        values = {"first_name": "", "last_name": "", "email": "", "course": "", "year_level": 1,
                  "status": "Active", "section_id": None}
        values.update({key: "" for key in REPORT_FORM_FIELDS})
        values.update(student_type=STUDENT_TYPES[0], enrollment_load=ENROLLMENT_LOADS[0],
                      admission_year=f"{school_year_start()}-{school_year_start() + 1}")
    start = school_year_start()
    admission_years = sorted({f"{y}-{y + 1}" for y in range(start - 8, start + 2)} | ({values["admission_year"]} if values.get("admission_year") else set()))
    return render_template("student_form.html", student=student, values=values, genders=GENDERS,
                           student_types=STUDENT_TYPES, loads=ENROLLMENT_LOADS, admission_years=admission_years,
                           programs=CurriculumProgram.query.order_by(CurriculumProgram.position, CurriculumProgram.id).all(),
                           sections=Section.query.order_by(Section.name).all())


# -------------------------
# Seed data and schema upgrades
# -------------------------

def seed_database():
    """Seed demo users only in development; production uses an explicit admin bootstrap."""
    production = os.environ.get("APP_ENV", "development").lower() == "production"
    if User.query.count() == 0:
        bootstrap_username = clean_text(os.environ.get("BOOTSTRAP_ADMIN_USERNAME"))
        bootstrap_password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
        if production:
            if bootstrap_username and len(bootstrap_password) >= 12:
                user = User(username=bootstrap_username, role="Admin")
                user.set_password(bootstrap_password)
                db.session.add(user)
                db.session.commit()
                app.logger.warning("Created initial administrator from bootstrap environment variables; remove those variables after first deployment.")
            elif bootstrap_username or bootstrap_password:
                app.logger.error("Admin bootstrap skipped: provide both BOOTSTRAP_ADMIN_USERNAME and a BOOTSTRAP_ADMIN_PASSWORD of at least 12 characters.")
        elif os.environ.get("SEED_DEMO_USERS", "1") == "1":
            for username, password, role in [
                ("registrar", "registrar123", "Registrar"),
                ("accounting", "accounting123", "Accounting"),
                ("academic", "academic123", "Academic"),
                ("admin", "admin123", "Admin"),
            ]:
                user = User(username=username, role=role)
                user.set_password(password)
                db.session.add(user)

    # Sample student/course data is also development-only by default in production.
    seed_demo_data = not production or os.environ.get("SEED_DEMO_DATA") == "1"
    if seed_demo_data and Student.query.count() == 0:
        db.session.add_all([
            Student(student_number="2026-0001", first_name="Juan", last_name="Dela Cruz",
                    email="juan@gmail.com", course="BS Information Technology", year_level=2, status="Active"),
            Student(student_number="2026-0002", first_name="Maria", last_name="Santos",
                    email="maria@gmail.com", course="BS Computer Science", year_level=3, status="Active"),
            Student(student_number="2026-0003", first_name="Alex", last_name="Reyes",
                    email="alex@gmail.com", course="BS Information Systems", year_level=1, status="Active"),
        ])

    if seed_demo_data and Course.query.count() == 0:
        db.session.add_all([
            Course(code="IT101", name="Introduction to Information Technology", units=3, instructor="Prof. Garcia"),
            Course(code="NET201", name="Computer Networks", units=3, instructor="Prof. Cruz"),
            Course(code="PDC301", name="Parallel and Distributed Computing", units=3, instructor="Prof. Santos"),
        ])
    if seed_demo_data and FinancialReport.query.count() == 0:
        for (kind, year), _values in fr.SAMPLES.items():
            db.session.add(FinancialReport(kind=kind, period=str(year), updated_by="system",
                                           data=fr.dumps(fr.default_data(kind, year, sample=True))))
    db.session.commit()


# Columns added over the project's history. create_all() never alters existing
# tables, so databases created by older versions get upgraded here (SQLite only).
SQLITE_COLUMN_UPGRADES = [
    ("student", "image_filename", "VARCHAR(255)"),
    ("student", "section_id", "INTEGER"),
    ("student", "gender", "VARCHAR(30)"),
    ("student", "birth_date", "DATE"),
    ("student", "residency", "VARCHAR(100)"),
    ("student", "student_type", "VARCHAR(30) NOT NULL DEFAULT 'First-time Freshman'"),
    ("student", "admission_year", "VARCHAR(9)"),
    ("student", "enrollment_load", "VARCHAR(20) NOT NULL DEFAULT 'Full-time'"),
    ("section", "capacity", f"INTEGER NOT NULL DEFAULT {DEFAULT_SECTION_CAPACITY}"),
    ("user", "profile_image", "VARCHAR(255)"),
    ("user", "can_manage_teachers_timetable", "BOOLEAN NOT NULL DEFAULT 0"),
    ("user", "failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
    ("user", "login_locked", "BOOLEAN NOT NULL DEFAULT 0"),
    ("user", "security_notifications_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
    ("assessment_score", "component", "VARCHAR(30) NOT NULL DEFAULT 'Written Work'"),
    ("grade", "mark", "VARCHAR(5)"),
    ("curriculum_course", "course_id", "INTEGER"),
    ("attendance", "recorded_by", "VARCHAR(50) NOT NULL DEFAULT 'legacy'"),
    ("attendance", "created_at", "DATETIME NOT NULL DEFAULT '1970-01-01 00:00:00'"),
    ("department_message", "archived_by_sender", "BOOLEAN NOT NULL DEFAULT 0"),
    ("department_message", "archived_by_recipient", "BOOLEAN NOT NULL DEFAULT 0"),
    ("department_message", "deleted_by_sender", "BOOLEAN NOT NULL DEFAULT 0"),
    ("department_message", "deleted_by_recipient", "BOOLEAN NOT NULL DEFAULT 0"),
]


def upgrade_sqlite_schema():
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    pending = [(t, c, ddl) for t, c, ddl in SQLITE_COLUMN_UPGRADES
               if t in tables and c not in {col["name"] for col in inspector.get_columns(t)}]
    with db.engine.connect() as conn:
        # "assessment" is a leftover table from an old version that no model uses.
        drop_legacy = "assessment" in tables and conn.execute(text('SELECT COUNT(*) FROM "assessment"')).scalar() == 0
    if not pending and not drop_legacy:
        return

    db_file = db.engine.url.database
    if db_file and Path(db_file).exists():
        backup = f"{db_file}.{datetime.now():%Y%m%d-%H%M%S}.bak"
        source, target = sqlite3.connect(db_file), sqlite3.connect(backup)
        try:
            source.backup(target)  # consistent even when the WAL file holds recent writes
        finally:
            target.close()
            source.close()
        app.logger.warning("Upgrading database schema. Backup saved to %s", backup)

    with db.engine.begin() as conn:
        for table, column, ddl in pending:
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
            if (table, column) == ("attendance", "created_at"):
                # Best available estimate for rows that predate the column.
                conn.execute(text("UPDATE attendance SET created_at = attendance_date || ' 00:00:00'"))
        if drop_legacy:
            conn.execute(text('DROP TABLE "assessment"'))


def ensure_grade_uniqueness():
    """Add a database-level guard against duplicate student/course/semester grades.

    Existing databases may already contain duplicates. Do not delete or alter
    academic records automatically: log the issue and leave the index absent so
    an administrator can review the conflicting rows before retrying startup.
    """
    inspector = inspect(db.engine)
    if "grade" not in inspector.get_table_names():
        return

    target_columns = ["student_id", "course_id", "semester"]
    unique_constraints = inspector.get_unique_constraints("grade")
    unique_indexes = inspector.get_indexes("grade")
    if any(c.get("column_names") == target_columns for c in unique_constraints) or any(
        i.get("unique") and i.get("column_names") == target_columns for i in unique_indexes
    ):
        return

    with db.engine.connect() as conn:
        duplicate = conn.execute(text("""
            SELECT student_id, course_id, semester, COUNT(*) AS row_count
            FROM grade
            GROUP BY student_id, course_id, semester
            HAVING COUNT(*) > 1
            LIMIT 1
        """)).first()
    if duplicate:
        app.logger.error(
            "Cannot enforce grade uniqueness: duplicate grade records exist for "
            "student_id=%s, course_id=%s, semester=%s. Review duplicates; no records were deleted.",
            duplicate.student_id, duplicate.course_id, duplicate.semester,
        )
        return

    # CREATE UNIQUE INDEX IF NOT EXISTS is supported by SQLite and PostgreSQL.
    with db.engine.begin() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_grade_student_course_semester "
            "ON grade (student_id, course_id, semester)"
        ))
    app.logger.info("Grade uniqueness protection is enabled.")


# -------------------------
# Authentication
# -------------------------

@app.route("/")
def home():
    return redirect(url_for("dashboard" if is_logged_in() else "login"))


def clear_account_lock(user):
    user.login_locked = False
    user.failed_login_count = 0
    user.locked_until = None
    user.last_failed_login_at = None


def refresh_account_lock(user):
    """Unlock the account if its lock period is over. Returns True while it is still locked."""
    if not user.login_locked:
        return False
    if user.locked_until is None:  # lock created by an older version: let it expire too
        user.locked_until = utcnow() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
        db.session.commit()
        return True
    if utcnow() >= user.locked_until:
        clear_account_lock(user)
        db.session.commit()
        return False
    return True


def lock_minutes_left(user):
    seconds = (user.locked_until - utcnow()).total_seconds() if user.locked_until else 0
    return max(1, math.ceil(seconds / 60))


def register_account_failure(user):
    """Count a failed password for this account (atomically) and lock it at the threshold."""
    now = utcnow()
    window = timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
    stale = user.last_failed_login_at is None or now - user.last_failed_login_at > window
    User.query.filter_by(id=user.id).update(
        {"failed_login_count": 1 if stale else User.failed_login_count + 1, "last_failed_login_at": now},
        synchronize_session=False)
    db.session.commit()
    db.session.refresh(user)
    if user.failed_login_count >= ACCOUNT_LOCK_THRESHOLD:
        user.login_locked = True
        user.locked_until = now + window
        db.session.commit()


@app.route("/login", methods=["GET", "POST"])
def login():
    if is_logged_in():
        return redirect(url_for("dashboard"))

    next_url = safe_next_url(request.values.get("next"))
    if request.method == "POST":
        username = clean_text(request.form.get("username"))
        password = request.form.get("password", "")
        key = _throttle_key(username)
        user = User.query.filter_by(username=username).first()
        ip = request.remote_addr or "unknown IP"
        if user and refresh_account_lock(user):
            log_auth_attempt(username, f"FAILED_LOGIN: attempt while account locked from {ip}")
            flash(f"This account is temporarily locked after too many failed login attempts. "
                  f"Try again in {lock_minutes_left(user)} minute(s), or ask an administrator to unlock it.", "danger")
        else:
            wait = login_wait_seconds(key)
            if wait:
                log_auth_attempt(username, f"FAILED_LOGIN: throttled attempt from {ip}")
                flash(f"Too many failed attempts. Please try again in {math.ceil(wait / 60)} minute(s).", "danger")
            elif user and user.check_password(password):
                clear_login_failures(key)
                user.failed_login_count = 0
                user.last_failed_login_at = None
                db.session.commit()
                log_auth_attempt(user.username, f"LOGIN: successful sign-in from {ip}", user.role)
                session.clear()
                session["user_id"] = user.id
                session.permanent = True
                flash(f"Welcome, {user.role}!", "success")
                return redirect(next_url or url_for("dashboard"))
            else:
                record_login_failure(key)
                if user:
                    register_account_failure(user)
                log_auth_attempt(username, f"FAILED_LOGIN: invalid credentials from {ip}")
                if user and user.login_locked:
                    log_auth_attempt(username, f"FAILED_LOGIN: account locked for {LOGIN_LOCKOUT_MINUTES} minutes after "
                                               f"{ACCOUNT_LOCK_THRESHOLD} failed attempts from {ip}")
                    flash(f"Too many failed attempts on this account. It is locked for {LOGIN_LOCKOUT_MINUTES} minutes "
                          f"(or until an administrator unlocks it).", "danger")
                else:
                    flash("Invalid username or password. Please try again.", "danger")

    return render_template("login.html", next_url=next_url)


@app.route("/admin/login-security", methods=["GET", "POST"])
@roles_required("Admin")
def login_security():
    """Admin-only failed-login inbox and manual unlock controls."""
    if request.method == "POST":
        operation = request.form.get("operation", "unlock")
        if operation == "dismiss":
            log_id = request.form.get("log_id", type=int)
            entry = db.session.get(ActivityLog, log_id) if log_id else None
            if entry and "FAILED_LOGIN" in (entry.action or "").upper():
                entry.notification_cleared = True
                db.session.commit()
                log_activity(f"UPDATED: Admin {current_user().username} cleared a failed-login notification for '{entry.username}' (audit record retained)")
                flash("Notification cleared. The failed-login audit record has been retained.", "success")
            else:
                flash("Could not clear that notification; it may no longer exist.", "danger")
            return redirect(url_for("login_security"))

        username = clean_text(request.form.get("username"))[:50]
        ip_address = clean_text(request.form.get("ip_address"))[:80]
        if username:
            with _failed_lock:
                if ip_address:
                    _failed_logins.pop((ip_address, username.lower()), None)
                else:
                    for throttle_key in list(_failed_logins):
                        if throttle_key[1] == username.lower():
                            _failed_logins.pop(throttle_key, None)
            locked_user = User.query.filter_by(username=username).first()
            if locked_user:
                clear_account_lock(locked_user)
                db.session.commit()
            log_activity(f"UPDATED: Admin {current_user().username} manually unlocked login for username '{username}' (IP {ip_address or 'all'})")
            flash(f"Login lock cleared for {username}. The audit history is retained.", "success")
        else:
            flash("Could not clear the throttle: username or IP address was missing.", "danger")
        return redirect(url_for("login_security"))

    failed_logs = ActivityLog.query.filter(
        ActivityLog.action.ilike("%FAILED_LOGIN%"),
        ActivityLog.notification_cleared.is_(False)
    ).order_by(ActivityLog.created_at.desc()).limit(200).all()
    # In-app alert count: uncleared failed attempts recorded in the last 24 hours.
    since = utcnow() - timedelta(hours=24)
    failed_alert_count = ActivityLog.query.filter(
        ActivityLog.action.ilike("%FAILED_LOGIN%"),
        ActivityLog.notification_cleared.is_(False),
        ActivityLog.created_at >= since
    ).count()
    return render_template("login_security.html", failed_logs=failed_logs, failed_alert_count=failed_alert_count, locked_users=User.query.filter(User.login_locked.is_(True), or_(User.locked_until.is_(None), User.locked_until > utcnow())).order_by(User.username).all())


@app.route("/admin/security-notifications/toggle", methods=["POST"])
@roles_required("Admin")
def toggle_security_notifications():
    user = current_user()
    user.security_notifications_enabled = not bool(user.security_notifications_enabled)
    db.session.commit()
    flash("Security notifications " + ("enabled." if user.security_notifications_enabled else "muted."), "success")
    return redirect(request.referrer if request.referrer and request.referrer.startswith("/") else url_for("login_security"))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    if request.method == "GET":  # logging out requires a POST (CSRF-safe)
        return redirect(url_for("dashboard" if is_logged_in() else "login"))
    session.clear()
    flash("You have been logged out safely.", "success")
    return redirect(url_for("login"))


# -------------------------
def _attachment_extension(filename):
    """Lower-case extension of the uploaded name, or '' when there is none."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def delete_attachment_files(item):
    """Remove a message's attachment files from disk (the caller updates the database row)."""
    try:
        entries = json.loads(item.attachments or "[]")
    except (TypeError, ValueError):
        entries = []
    folder = Path(app.instance_path) / "message_attachments"
    for meta in entries:
        try:
            (folder / Path(meta["stored_name"]).name).unlink(missing_ok=True)
        except (KeyError, TypeError, OSError):
            app.logger.warning("Could not remove an attachment file for message %s", getattr(item, "id", "?"))


def _valid_message_attachment(uploaded_file):
    """Check file signatures so renaming a non-image file cannot bypass validation."""
    ext = _attachment_extension(uploaded_file.filename)
    header = uploaded_file.stream.read(16)
    uploaded_file.stream.seek(0)
    if ext == "png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {"jpg", "jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if ext == "webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if ext == "pdf":
        return header.startswith(b"%PDF-")
    return False


# Department messages
# -------------------------

@app.route("/messages", methods=["GET", "POST"])
@roles_required()
def messages():
    user = current_user()
    if request.method == "POST":
        recipient_mode = clean_text(request.form.get("recipient_mode", "department"))
        recipient_role = clean_text(request.form.get("recipient_role"))
        recipient_user_id = request.form.get("recipient_user_id", type=int)
        category = clean_text(request.form.get("category")) or "General"
        subject = clean_text(request.form.get("subject"))
        body = clean_text(request.form.get("body"))
        allowed_categories = {
            "Request for Information", "Enrollment / Registration", "Transcript / Grade History",
            "Graduation Requirements", "Payment History", "Payment Clarification", "Other", "General"
        }
        target_user = db.session.get(User, recipient_user_id) if recipient_user_id else None
        uploads = [f for f in request.files.getlist("attachments") if f and f.filename]
        allowed_extensions = {"png", "jpg", "jpeg", "webp", "pdf"}
        valid_recipient = (recipient_mode == "department" and recipient_role in ("Registrar", "Accounting")) or (recipient_mode == "private" and target_user and target_user.id != user.id)
        if not valid_recipient:
            flash("Choose a valid department or a different account for a private message.", "danger")
        elif not subject or len(subject) > 140 or not body or len(body) > 5000:
            flash("Enter a subject (up to 140 characters) and message (up to 5,000 characters).", "danger")
        elif category not in allowed_categories:
            flash("Choose a valid request type.", "danger")
        elif len(uploads) > 5:
            flash("Attach up to 5 files per message.", "danger")
        elif any(_attachment_extension(f.filename) not in allowed_extensions for f in uploads):
            flash("Only PNG, JPG, JPEG, WEBP images and PDF files are allowed.", "danger")
        elif any(not _valid_message_attachment(f) for f in uploads):
            flash("One or more attachments do not appear to be a valid PNG, JPG, WEBP, or PDF file. Please choose the original file and try again.", "danger")
        else:
            attachment_items = []
            attachment_dir = Path(app.instance_path) / "message_attachments"
            attachment_dir.mkdir(parents=True, exist_ok=True)
            try:
                for uploaded in uploads:
                    ext = _attachment_extension(uploaded.filename)
                    stem = secure_filename(uploaded.filename.rsplit(".", 1)[0])[:150] or "attachment"
                    original = f"{stem}.{ext}"
                    stored = f"{secrets.token_hex(20)}.{ext}"
                    uploaded.save(str(attachment_dir / stored))
                    attachment_items.append({"stored_name": stored, "original_name": original,
                                             "kind": "pdf" if ext == "pdf" else "image"})
                item = DepartmentMessage(
                    sender_id=user.id,
                    recipient_role=target_user.role if recipient_mode == "private" else recipient_role,
                    recipient_user_id=target_user.id if recipient_mode == "private" else None,
                    attachments=json.dumps(attachment_items) if attachment_items else None,
                    subject=subject, category=category, body=body)
                db.session.add(item)
                db.session.commit()
            except Exception:
                db.session.rollback()
                for meta in attachment_items:
                    (attachment_dir / meta["stored_name"]).unlink(missing_ok=True)
                app.logger.exception("Could not save message or its attachments")
                flash("The message could not be sent. Please try again.", "danger")
            else:
                destination = f"{target_user.username} (private)" if recipient_mode == "private" else recipient_role
                log_activity(f"SENT MESSAGE TO {destination}: {subject}")
                flash(f"Your message was sent to {destination}.", "success")
                return redirect(url_for("messages", view="sent"))

    view = request.args.get("view", "inbox")
    if view not in ("inbox", "sent", "archived"):
        view = "inbox"
    recipient_scope = or_(DepartmentMessage.recipient_user_id == user.id,
                          (DepartmentMessage.recipient_user_id.is_(None)) & (DepartmentMessage.recipient_role == user.role))
    if view == "sent":
        message_query = DepartmentMessage.query.filter_by(sender_id=user.id, archived_by_sender=False, deleted_by_sender=False)
    elif view == "archived":
        message_query = DepartmentMessage.query.filter(or_(
            (DepartmentMessage.sender_id == user.id) & DepartmentMessage.archived_by_sender.is_(True) & DepartmentMessage.deleted_by_sender.is_(False),
            recipient_scope & DepartmentMessage.archived_by_recipient.is_(True) & DepartmentMessage.deleted_by_recipient.is_(False)))
    else:
        view = "inbox"
        message_query = DepartmentMessage.query.filter(recipient_scope,
            DepartmentMessage.archived_by_recipient.is_(False), DepartmentMessage.deleted_by_recipient.is_(False))

    search_query = clean_text(request.args.get("q", ""))[:200]
    if search_query:
        pattern = f"%{search_query}%"
        message_query = message_query.filter(or_(
            DepartmentMessage.subject.ilike(pattern), DepartmentMessage.body.ilike(pattern),
            DepartmentMessage.category.ilike(pattern), DepartmentMessage.recipient_role.ilike(pattern),
            DepartmentMessage.sender.has(User.username.ilike(pattern)),
            DepartmentMessage.recipient_user.has(User.username.ilike(pattern))))

    opened_message = None
    message_id = request.args.get("message_id", type=int)
    if message_id:
        opened_message = db.session.get(DepartmentMessage, message_id)
        is_sender = bool(opened_message and opened_message.sender_id == user.id)
        is_recipient = bool(opened_message and (opened_message.recipient_user_id == user.id or
            (opened_message.recipient_user_id is None and user.role in ("Registrar", "Accounting") and opened_message.recipient_role == user.role)))
        if not opened_message or not (is_sender or is_recipient):
            abort(404)
        if (is_sender and opened_message.deleted_by_sender) or (is_recipient and opened_message.deleted_by_recipient):
            abort(404)
        if is_recipient and not opened_message.is_read:
            opened_message.is_read = True
            db.session.commit()

    message_items = message_query.order_by(DepartmentMessage.created_at.desc()).limit(200).all()
    unread_count = DepartmentMessage.query.filter(
        DepartmentMessage.is_read.is_(False), DepartmentMessage.archived_by_recipient.is_(False),
        DepartmentMessage.deleted_by_recipient.is_(False),
        or_(DepartmentMessage.recipient_user_id == user.id,
            (DepartmentMessage.recipient_user_id.is_(None)) & (DepartmentMessage.recipient_role == user.role))).count()
    accounts = User.query.filter(User.id != user.id).order_by(User.username.asc()).all()
    return render_template("messages.html", messages=message_items, view=view,
                           opened_message=opened_message, unread_count=unread_count,
                           search_query=search_query, accounts=accounts, json_loads=json.loads)


@app.route("/messages/<int:message_id>/attachments/<int:attachment_index>")
@roles_required()
def download_message_attachment(message_id, attachment_index):
    user = current_user()
    item = db.session.get(DepartmentMessage, message_id)
    is_sender = bool(item and item.sender_id == user.id and not item.deleted_by_sender)
    is_recipient = bool(item and not item.deleted_by_recipient and (item.recipient_user_id == user.id or
        (item.recipient_user_id is None and user.role in ("Registrar", "Accounting") and item.recipient_role == user.role)))
    if not item or not (is_sender or is_recipient):
        abort(404)
    try:
        attachments = json.loads(item.attachments or "[]")
        meta = attachments[attachment_index]
        stored_name = Path(meta["stored_name"]).name
    except (ValueError, KeyError, IndexError, TypeError):
        abort(404)
    path = Path(app.instance_path) / "message_attachments" / stored_name
    if not path.is_file():
        abort(404)
    ext = path.suffix.lower()
    image_mimetypes = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    is_image = ext in image_mimetypes
    response = send_file(path, as_attachment=not is_image,
                         download_name=secure_filename(meta.get("original_name", "attachment")),
                         mimetype=image_mimetypes.get(ext, "application/pdf"), max_age=0)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@app.route("/messages/<int:message_id>/open", methods=["POST"])
@roles_required()
def open_message(message_id):
    user = current_user()
    item = db.session.get(DepartmentMessage, message_id)
    is_sender = bool(item and item.sender_id == user.id)
    is_recipient = bool(item and (item.recipient_user_id == user.id or (item.recipient_user_id is None and user.role in ("Registrar", "Accounting") and item.recipient_role == user.role)))
    if not item or not (is_sender or is_recipient):
        abort(404)
    if (is_sender and item.deleted_by_sender) or (is_recipient and item.deleted_by_recipient):
        abort(404)
    if is_recipient and not item.is_read:
        item.is_read = True
        db.session.commit()
    return redirect(url_for("messages", view="sent" if is_sender else "inbox", message_id=item.id,
                            q=clean_text(request.form.get("q", "")) or None))


@app.route("/messages/<int:message_id>/<action>", methods=["POST"])
@roles_required()
def manage_message(message_id, action):
    if action not in ("archive", "unarchive", "delete"):
        abort(404)
    user = current_user()
    item = db.session.get(DepartmentMessage, message_id)
    is_sender = bool(item and item.sender_id == user.id)
    is_recipient = bool(item and (item.recipient_user_id == user.id or (item.recipient_user_id is None and user.role in ("Registrar", "Accounting") and item.recipient_role == user.role)))
    if not item or not (is_sender or is_recipient):
        abort(404)
    role_suffix = "sender" if is_sender else "recipient"
    if action == "delete":
        setattr(item, f"deleted_by_{role_suffix}", True)
        if item.deleted_by_sender and item.deleted_by_recipient and item.attachments:
            delete_attachment_files(item)  # nobody can see this message any more
            item.attachments = None
        flash("Message deleted from your mailbox.", "success")
    else:
        setattr(item, f"archived_by_{role_suffix}", action == "archive")
        flash("Message archived." if action == "archive" else "Message restored to your mailbox.", "success")
    db.session.commit()
    log_activity(f"{action.upper()}D MESSAGE {item.id} BY {user.username}")
    return redirect(url_for("messages", view="archived" if request.form.get("return_view") == "archived" else ("sent" if is_sender else "inbox"),
                            q=clean_text(request.form.get("q", "")) or None))


# -------------------------
# Dashboard
# -------------------------

@app.route("/dashboard")
@roles_required()
def dashboard():
    user = current_user()
    stats = {
        "students": Student.query.count(),
        "courses": Course.query.count(),
        "payments": Payment.query.count(),
        "grades": Grade.query.count(),
    }
    log_search = clean_text(request.args.get("activity_search"))
    log_date = clean_text(request.args.get("activity_date"))
    log_action_type = clean_text(request.args.get("activity_type"))
    log_query = ActivityLog.query
    activity_types = ["CREATED", "EDITED", "UPDATED", "DELETED", "RECORDED", "CALCULATED", "LOGIN", "LOGOUT", "FAILED_LOGIN"]
    departments = ["Registrar", "Accounting", "Academic", "Security"]
    selected_department = clean_text(request.args.get("department"))

    # Admin can audit all departments and security events. Other accounts can
    # audit only departments explicitly granted in Staff Accounts settings.
    if user.role != "Admin":
        try:
            allowed_departments = json.loads(user.activity_departments) if user.activity_departments else [user.role]
        except (TypeError, ValueError):
            allowed_departments = [user.role]
        allowed_departments = [d for d in allowed_departments if d in ("Registrar", "Accounting", "Academic")]
        if not allowed_departments:
            log_query = log_query.filter(text("1=0"))
            selected_department = ""
        else:
            if selected_department not in allowed_departments:
                selected_department = user.role if user.role in allowed_departments else allowed_departments[0]
            if selected_department:
                same_department_users = db.session.query(User.username).filter_by(role=selected_department).subquery()
                log_query = log_query.filter(or_(ActivityLog.department == selected_department,
                                                 (ActivityLog.department.is_(None) & ActivityLog.username.in_(same_department_users))))
        try:
            allowed_types = json.loads(user.activity_visibility) if user.activity_visibility else activity_types
        except (TypeError, ValueError):
            allowed_types = []
        allowed_types = [item for item in allowed_types if item in activity_types]
        if allowed_types:
            log_query = log_query.filter(or_(*(ActivityLog.action.ilike(f"%{item}%") for item in allowed_types)))
        else:
            log_query = log_query.filter(text("1=0"))
    elif selected_department in departments:
        same_department_users = db.session.query(User.username).filter_by(role=selected_department).subquery()
        log_query = log_query.filter(or_(ActivityLog.department == selected_department,
                                         (ActivityLog.department.is_(None) & ActivityLog.username.in_(same_department_users))))
    elif selected_department == "Security":
        log_query = log_query.filter(ActivityLog.department == "Security")

    if log_action_type:
        if log_action_type == "FAILED_LOGIN" and user.role != "Admin":
            log_query = log_query.filter(text("1=0"))
        else:
            log_query = log_query.filter(ActivityLog.action.ilike(f"%{log_action_type}%"))
    if log_search:
        log_query = log_query.filter(or_(ActivityLog.username.ilike(f"%{log_search}%"),
                                         ActivityLog.action.ilike(f"%{log_search}%")))
    if log_date:
        try:
            start, end = local_day_range_utc(date.fromisoformat(log_date))
            log_query = log_query.filter(ActivityLog.created_at >= start, ActivityLog.created_at < end)
        except ValueError:
            flash("Please choose a valid activity date.", "danger")
    recent_logs = log_query.order_by(ActivityLog.created_at.desc()).limit(300).all()
    announcements = Announcement.query.filter_by(is_published=True).order_by(Announcement.created_at.desc()).limit(8).all()
    return render_template("dashboard.html", user=user, stats=stats, recent_logs=recent_logs,
                           log_search=log_search, log_date=log_date, log_action_type=log_action_type,
                           activity_types=activity_types, departments=departments,
                           selected_department=selected_department, announcements=announcements,
                           allowed_departments=(allowed_departments if user.role != "Admin" else departments))


@app.route("/announcements")
@roles_required()
def announcements():
    items = Announcement.query.filter_by(is_published=True).order_by(Announcement.created_at.desc()).all()
    return render_template("announcements.html", user=current_user(), announcements=items)


@app.route("/announcements/<int:announcement_id>")
@roles_required()
def announcement_detail(announcement_id):
    item = Announcement.query.filter_by(id=announcement_id, is_published=True).first_or_404()
    return render_template("announcement_detail.html", user=current_user(), announcement=item)


@app.route("/admin/announcements", methods=["GET", "POST"])
@roles_required("Admin")
def manage_announcements():
    if request.method == "POST":
        title = clean_text(request.form.get("title", ""))[:180]
        body = (request.form.get("body") or "").strip()
        if not title or not body:
            flash("Enter both an announcement title and message.", "danger")
        elif len(body) > 10_000:
            flash("Announcement text is limited to 10,000 characters.", "danger")
        else:
            item = Announcement(title=title, body=body, author=current_user().username,
                                is_published=request.form.get("is_published") == "on")
            db.session.add(item)
            db.session.commit()
            log_activity(f"PUBLISHED ANNOUNCEMENT {item.id}: {title}")
            flash("Announcement saved.", "success")
            return redirect(url_for("manage_announcements"))
    items = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return render_template("manage_announcements.html", user=current_user(), announcements=items)


@app.route("/admin/announcements/<int:announcement_id>/toggle", methods=["POST"])
@roles_required("Admin")
def toggle_announcement(announcement_id):
    item = db.get_or_404(Announcement, announcement_id)
    item.is_published = not item.is_published
    item.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    log_activity(f"{'PUBLISHED' if item.is_published else 'UNPUBLISHED'} ANNOUNCEMENT {item.id}")
    flash("Announcement published." if item.is_published else "Announcement moved back to draft.", "success")
    return redirect(url_for("manage_announcements"))


@app.route("/admin/announcements/<int:announcement_id>/delete", methods=["POST"])
@roles_required("Admin")
def delete_announcement(announcement_id):
    item = db.get_or_404(Announcement, announcement_id)
    db.session.delete(item)
    db.session.commit()
    log_activity(f"DELETED ANNOUNCEMENT {announcement_id}")
    flash("Announcement deleted.", "success")
    return redirect(url_for("manage_announcements"))


@app.route("/activity-report")
@roles_required()
def activity_report():
    user = current_user()
    departments = ["Registrar", "Accounting", "Academic", "Security"]
    selected_department = clean_text(request.args.get("department"))
    if user.role != "Admin":
        try:
            allowed_departments = json.loads(user.activity_departments) if user.activity_departments else [user.role]
        except (TypeError, ValueError):
            allowed_departments = [user.role]
        allowed_departments = [d for d in allowed_departments if d in ("Registrar", "Accounting", "Academic")]
        if not allowed_departments:
            flash("Your account has no department activity-history access. Contact an administrator.", "warning")
            return redirect(url_for("dashboard"))
        if selected_department not in allowed_departments:
            selected_department = user.role if user.role in allowed_departments else allowed_departments[0]
    elif selected_department not in departments:
        selected_department = "All"

    start_text = clean_text(request.args.get("start_date"))
    end_text = clean_text(request.args.get("end_date"))
    today = local_today()
    try:
        start_date = date.fromisoformat(start_text) if start_text else today
        end_date = date.fromisoformat(end_text) if end_text else today
        if start_date > end_date:
            raise ValueError
        if (end_date - start_date).days > 366:
            flash("Please choose a report period of 366 days or less.", "danger")
            return redirect(url_for("activity_report", department=selected_department,
                                    start_date=start_date.isoformat(), end_date=end_date.isoformat()))
    except ValueError:
        flash("Choose a valid date range (start date must be on or before end date).", "danger")
        return redirect(url_for("activity_report", department=selected_department))

    start_utc, _ = local_day_range_utc(start_date)
    _, end_utc = local_day_range_utc(end_date)
    query = ActivityLog.query.filter(ActivityLog.created_at >= start_utc, ActivityLog.created_at < end_utc)
    if user.role != "Admin" or selected_department != "All":
        if selected_department == "All":
            pass
        elif selected_department == "Security" and user.role == "Admin":
            query = query.filter(ActivityLog.department == "Security")
        else:
            same_department_users = db.session.query(User.username).filter_by(role=selected_department).subquery()
            query = query.filter(or_(ActivityLog.department == selected_department,
                                     (ActivityLog.department.is_(None) & ActivityLog.username.in_(same_department_users))))
    report_logs = query.order_by(ActivityLog.created_at.asc()).limit(5000).all()
    return render_template("activity_report.html", report_logs=report_logs, user=user,
                           selected_department=selected_department, departments=departments,
                           allowed_departments=(allowed_departments if user.role != "Admin" else departments),
                           start_date=start_date.isoformat(), end_date=end_date.isoformat(),
                           generated_at=datetime.now(LOCAL_TZ))


# -------------------------
# Registrar: Sections
# -------------------------

@app.route("/sections", methods=["GET", "POST"])
@roles_required("Registrar", "Admin")
def sections():
    edit_section = get_or_none(Section, request.args.get("edit"))
    if request.method == "POST":
        section_id = request.form.get("section_id", type=int)
        name = clean_text(request.form.get("name"))
        try:
            year_level = parse_year(request.form.get("year_level"))
            target = db.session.get(Section, section_id) if section_id else Section()
            if target is None:
                raise ValueError("That section could not be found.")
            if not name or len(name) > 80:
                raise ValueError("Enter a section name (up to 80 characters).")
            duplicate = Section.query.filter(func.lower(Section.name) == name.lower())
            if section_id:
                duplicate = duplicate.filter(Section.id != section_id)
            if duplicate.first():
                raise ValueError("That section name already exists.")
            capacity = request.form.get("capacity", type=int)
            if capacity is None or not 1 <= capacity <= 500:
                raise ValueError("Enter a section capacity between 1 and 500.")
            target.name, target.year_level, target.capacity = name, year_level, capacity
            if not section_id:
                db.session.add(target)
            db.session.commit()
            log_activity(f"{'EDITED' if section_id else 'CREATED'} section {name}")
            flash("Section saved successfully.", "success")
            return redirect(url_for("sections"))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc) or "Enter a section name and valid year level.", "danger")

    student_counts = dict(db.session.query(Student.section_id, func.count(Student.id)).group_by(Student.section_id).all())
    return render_template("sections.html", sections=Section.query.order_by(Section.year_level, Section.name).all(),
                           edit_section=edit_section, student_counts=student_counts)


@app.route("/sections/<int:section_id>/delete", methods=["POST"])
@roles_required("Registrar", "Admin")
def delete_section(section_id):
    section = db.get_or_404(Section, section_id)
    if Student.query.filter_by(section_id=section.id).first():
        flash("This section still has students. Move them to another section first.", "danger")
        return redirect(url_for("sections"))
    name = section.name
    db.session.delete(section)
    db.session.commit()
    log_activity(f"DELETED section {name}")
    flash(f"Section {name} deleted.", "success")
    return redirect(url_for("sections"))


# -------------------------
# Registrar: Students
# -------------------------

@app.route("/students")
@roles_required("Registrar", "Academic", "Admin")
def students():
    search = clean_text(request.args.get("search"))
    status_filter = clean_text(request.args.get("status"))
    section_filter = request.args.get("section_id", type=int)

    query = Student.query.options(joinedload(Student.section))
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(Student.student_number.ilike(pattern), Student.first_name.ilike(pattern),
                                 Student.last_name.ilike(pattern), Student.course.ilike(pattern),
                                 Student.email.ilike(pattern)))
    if status_filter in STUDENT_STATUSES:
        query = query.filter(Student.status == status_filter)
    if section_filter:
        query = query.filter(Student.section_id == section_filter)

    return render_template("students.html", students=query.order_by(Student.last_name, Student.first_name).all(),
                           search=search, status_filter=status_filter, section_filter=section_filter,
                           sections=Section.query.order_by(Section.name).all())


@app.route("/students/add", methods=["GET", "POST"])
@roles_required("Registrar", "Admin")
def add_student():
    if request.method == "POST":
        image_name = None
        try:
            data = parse_student_form(request.form)
            image_name = save_image(request.files.get("photo"), "student")
            student = commit_with_retry(lambda: Student(student_number=generate_student_number(),
                                                        image_filename=image_name, **data))
        except ValueError as exc:
            db.session.rollback()
            delete_upload(image_name)
            flash(str(exc) or "Please complete all fields correctly.", "danger")
            return render_student_form(None, request.form)
        log_activity(f"Added student {student.student_number}")
        flash(f"Student {student.student_number} added successfully.", "success")
        return redirect(url_for("students"))
    return render_student_form()


@app.route("/students/<int:student_id>")
@roles_required("Registrar", "Academic", "Admin")
def student_detail(student_id):
    student = db.get_or_404(Student, student_id)
    academic_year = clean_text(request.args.get("academic_year"))
    academic_date_from = clean_text(request.args.get("date_from"))
    academic_date_to = clean_text(request.args.get("date_to"))
    grade_query = Grade.query.filter_by(student_id=student.id).options(joinedload(Grade.course))
    if academic_year:
        grade_query = grade_query.filter(Grade.semester.ilike(f"%{academic_year}%"))
    grades = grade_query.all()
    semester_totals = {}
    numeric_grades = [g for g in grades if not g.mark]  # INC / AW / UW / NCA carry no percentage
    for item in numeric_grades:
        semester_totals.setdefault(item.semester, []).append(item.grade)
    semester_averages = {period: round(sum(v) / len(v), 2) for period, v in semester_totals.items()}
    overall_average = round(sum(g.grade for g in numeric_grades) / len(numeric_grades), 2) if numeric_grades else None
    assessment_query = (AssessmentScore.query.filter_by(student_id=student.id)
                        .options(joinedload(AssessmentScore.course)))
    if academic_year:
        assessment_query = assessment_query.filter(AssessmentScore.semester.ilike(f"%{academic_year}%"))
    try:
        if academic_date_from:
            assessment_query = assessment_query.filter(AssessmentScore.created_at >= datetime.combine(date.fromisoformat(academic_date_from), datetime.min.time()))
        if academic_date_to:
            assessment_query = assessment_query.filter(AssessmentScore.created_at < datetime.combine(date.fromisoformat(academic_date_to) + timedelta(days=1), datetime.min.time()))
    except ValueError:
        flash("Please choose valid academic overview dates.", "danger")
        academic_date_from, academic_date_to = "", ""
    assessment_scores = assessment_query.order_by(AssessmentScore.created_at.desc()).all()
    attendance_counts = dict(db.session.query(Attendance.status, func.count(Attendance.id))
                             .filter(Attendance.student_id == student.id).group_by(Attendance.status).all())
    return render_template("student_detail.html", student=student, grades=grades,
                           semester_averages=semester_averages, overall_average=overall_average,
                           overall_equivalent=(percentage_to_equivalent(overall_average)[0] if overall_average is not None else None),
                           assessment_scores=assessment_scores, attendance_counts=attendance_counts,
                           academic_year=academic_year, academic_date_from=academic_date_from, academic_date_to=academic_date_to)


@app.route("/students/<int:student_id>/edit", methods=["GET", "POST"])
@roles_required("Registrar", "Admin")
def edit_student(student_id):
    student = db.get_or_404(Student, student_id)
    if request.method == "POST":
        new_image = None
        try:
            data = parse_student_form(request.form, existing_program=student.course)
            new_image = save_image(request.files.get("photo"), "student")
        except ValueError as exc:
            flash(str(exc) or "Please complete all fields correctly.", "danger")
            return render_student_form(student, request.form)

        old_image = student.image_filename
        for key, value in data.items():
            setattr(student, key, value)
        if new_image:
            student.image_filename = new_image
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            delete_upload(new_image)
            app.logger.exception("Could not update student %s", student_id)
            flash("Could not save the changes. Please try again.", "danger")
            return render_student_form(student, request.form)
        if new_image:
            delete_upload(old_image)
        log_activity(f"Updated student {student.student_number}")
        flash("Student record updated successfully.", "success")
        return redirect(url_for("student_detail", student_id=student.id))
    return render_student_form(student)


@app.route("/students/<int:student_id>/delete", methods=["POST"])
@roles_required("Registrar", "Admin")
def delete_student(student_id):
    student = db.get_or_404(Student, student_id)
    number, image = student.student_number, student.image_filename
    try:
        db.session.delete(student)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("Could not delete student %s", student_id)
        flash("Could not delete the student record.", "danger")
        return redirect(url_for("students"))
    delete_upload(image)
    log_activity(f"Deleted student {number}")
    flash(f"Student {number} deleted.", "success")
    return redirect(url_for("students"))


# -------------------------
# Accounting: Payments
# -------------------------

@app.route("/payments", methods=["GET", "POST"])
@roles_required("Accounting", "Admin")
def payments():
    if request.method == "POST":
        try:
            student = find_student_by_lookup(request.form.get("student_lookup"))
            if not student:
                raise ValueError("Choose a student from the list or type a valid student number.")
            try:
                amount = parse_money(request.form.get("amount"))
            except ValueError:
                raise ValueError("Enter a valid payment amount greater than zero.") from None
            payment_type = clean_text(request.form.get("payment_type"))
            if payment_type not in PAYMENT_TYPES:
                raise ValueError("Choose a valid payment type.")
            consume_form_token(request.form.get("submit_token"))  # blocks double-submits
            payment = commit_with_retry(lambda: Payment(student_id=student.id, amount=amount,
                                                        payment_type=payment_type,
                                                        reference=generate_payment_reference()))
            log_activity(f"Recorded payment {payment.reference}")
            flash(f"Payment {payment.reference} recorded successfully.", "success")
            return redirect(url_for("payments"))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    search = clean_text(request.args.get("search"))
    date_from = clean_text(request.args.get("date_from"))
    date_to = clean_text(request.args.get("date_to"))
    day = clean_text(request.args.get("day"))
    query = Payment.query.options(joinedload(Payment.student))
    all_dates = request.args.get("all_dates") == "1"
    if not any([search, date_from, date_to, day]) and not all_dates:
        day = local_today().isoformat()  # default view: today's transactions
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(Payment.reference.ilike(pattern), Payment.payment_type.ilike(pattern),
                                 Payment.student.has(or_(Student.student_number.ilike(pattern),
                                                         Student.first_name.ilike(pattern),
                                                         Student.last_name.ilike(pattern)))))
    try:
        if day:
            start, end = local_day_range_utc(date.fromisoformat(day))
            query = query.filter(Payment.payment_date >= start, Payment.payment_date < end)
        if date_from:
            query = query.filter(Payment.payment_date >= local_day_range_utc(date.fromisoformat(date_from))[0])
        if date_to:
            query = query.filter(Payment.payment_date < local_day_range_utc(date.fromisoformat(date_to))[1])
    except ValueError:
        flash("Please use valid dates for the transaction filter.", "danger")
    total = query.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0
    all_time_total = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0
    payments_list = query.order_by(Payment.payment_date.desc()).limit(500).all()
    return render_template("payments.html", students=Student.query.order_by(Student.last_name, Student.first_name).all(),
                           sections=Section.query.order_by(Section.year_level, Section.name).all(),
                           payments=payments_list, total=total, all_time_total=all_time_total,
                           search=search, date_from=date_from, date_to=date_to, day=day,
                           payment_types=PAYMENT_TYPES, pay_token=new_form_token())


# -------------------------
# Academic: Courses
# -------------------------

# -------------------------
# Accounting: Financial reports
# -------------------------

@app.template_filter("fr_money")
def fr_money_filter(value):
    return fr.fmt(value)


@app.template_filter("fr_input")
def fr_input_filter(value):
    return fr.fmt_input(value)


app.jinja_env.globals["fr_bad"] = fr.is_unfavourable


def read_report_period(raw):
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return local_today().year
    return year if 1990 <= year <= 2100 else local_today().year


def report_year_options(selected):
    this_year = local_today().year
    years = set(range(this_year - 6, this_year + 3)) | {selected}
    return sorted(years, reverse=True)


def can_edit_reports(user):
    if not user:
        return False
    # Saving a report is an upsert, so either Create or Edit access unlocks the form.
    return has_module_access(user, "financial_reports", "edit") or has_module_access(user, "financial_reports", "create")


def saved_report(kind, period):
    return FinancialReport.query.filter_by(kind=kind, period=str(period)).first()


def equity_defaults(period):
    """A new Statement of Changes in Equity starts from last year's closing balance and this year's net income."""
    values, notes = {}, []
    previous = saved_report("equity", period - 1)
    if previous:
        closing = fr.compute("equity", period - 1, fr.loads("equity", period - 1, previous.data))["totals"]["close"]
        values["open"] = {"Opening Balance": [closing[0], closing[1]]}
        notes.append(f"Opening balance taken from the {period - 1} closing balance.")
    income = saved_report("income_statement", period)
    if income:
        net = fr.compute("income_statement", period, fr.loads("income_statement", period, income.data))["totals"]["net"][0]
        if net >= 0:
            values["add"] = {"Net Income": [0, net]}
        else:
            values["less"] = {"Net Loss": [0, -net]}
        notes.append(f"Net income taken from the saved {period} Income Statement.")
    return fr.default_data("equity", period, values), notes


def report_page_context(kind, period, data, record, notes=()):
    spec = fr.spec_for(kind)
    result = fr.compute(kind, period, data)
    check = None
    if spec.get("check"):
        a, b = spec["check"]["a"], spec["check"]["b"]
        check = {"label": spec["check"]["label"], "a": a, "b": b,
                 "gap": result["totals"][a][0] - result["totals"][b][0]}
    columns = spec["columns"](period)
    return dict(kind=kind, spec=spec, period=period, columns=columns, extra=spec["extra"],
                ncols=len(columns), span=len(columns) + 2 + (1 if spec["extra"] else 0), zero_vals=[fr.ZERO] * len(columns),
                generated=datetime.now(LOCAL_TZ),
                data=data, result=result, record=record, editable=can_edit_reports(current_user()),
                years=report_year_options(period), notes=list(notes), check=check,
                subtitle=spec["subtitle"].format(period=period), kinds=fr.REPORTS)


@app.route("/financial-reports")
@roles_required("Accounting", "Admin")
def financial_reports():
    period = read_report_period(request.args.get("period"))
    saved = {(r.kind, r.period): r for r in FinancialReport.query.all()}
    recent = sorted((r for r in saved.values() if r.kind in fr.REPORTS), key=lambda r: r.updated_at, reverse=True)[:12]
    statements = sum(1 for r in saved.values() if r.kind == "billing_statement")
    return render_template("financial_reports.html", kinds=fr.REPORTS, period=period,
                           years=report_year_options(period), saved=saved, recent=recent, statements=statements,
                           editable=can_edit_reports(current_user()))


@app.route("/financial-reports/<kind>", methods=["GET", "POST"])
@roles_required("Accounting", "Admin")
def financial_report(kind):
    if kind not in fr.REPORTS:
        abort(404)
    period = read_report_period(request.values.get("period"))
    record = saved_report(kind, period)

    if request.method == "POST":
        if not can_edit_reports(current_user()):
            return _error_page(403, "Access Denied", "Your account cannot change financial reports.")
        try:
            data = fr.parse_form(kind, period, request.form)
            if record and request.form.get("expected_updated") != record.updated_at.isoformat():
                flash("Edit conflict: this report was saved by someone else while you were editing. "
                      "The latest version is shown; apply your changes again if needed.", "danger")
                return redirect(url_for("financial_report", kind=kind, period=period))
            title = fr.REPORTS[kind]["title"]
            if record:
                record.data, record.updated_by = fr.dumps(data), current_user().username
                action = "EDITED"
            else:
                record = FinancialReport(kind=kind, period=str(period), data=fr.dumps(data), updated_by=current_user().username)
                db.session.add(record)
                action = "CREATED"
            db.session.commit()
            log_activity(f"{action} FINANCIAL REPORT {title} ({period})")
            flash(f"{title} for {period} saved.", "success")
            return redirect(url_for("financial_report", kind=kind, period=period))
        except IntegrityError:
            db.session.rollback()
            flash("That report was created by someone else at the same moment. Reload and try again.", "danger")
            return redirect(url_for("financial_report", kind=kind, period=period))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            # keep what the user typed so nothing is lost
            try:
                typed = fr.parse_form(kind, period, _LenientForm(request.form))
            except ValueError:
                typed = None
            return render_template("financial_report.html", **report_page_context(kind, period, typed or fr.loads(kind, period, record.data if record else None), record)), 400

    notes = []
    if record:
        data = fr.loads(kind, period, record.data)
    elif kind == "equity":
        data, notes = equity_defaults(period)
    else:
        data = fr.default_data(kind, period)
    return render_template("financial_report.html", **report_page_context(kind, period, data, record, notes))


class _LenientForm:
    """Same lists as the posted form, but an unreadable amount counts as 0, so the page can be shown again."""
    def __init__(self, form):
        self.form = form

    def getlist(self, key):
        values = self.form.getlist(key)
        if key.startswith("v__"):
            cleaned = []
            for value in values:
                try:
                    fr.parse_amount(value)
                    cleaned.append(value)
                except ValueError:
                    cleaned.append("")
            return cleaned
        return values


@app.route("/financial-reports/<kind>/delete", methods=["POST"])
@roles_required("Accounting", "Admin")
def delete_financial_report(kind):
    if kind not in fr.REPORTS and kind != "billing_statement":
        abort(404)
    period = clean_text(request.form.get("period"))
    record = saved_report(kind, period)
    if record:
        title = fr.REPORTS[kind]["title"] if kind in fr.REPORTS else "Billing Statement"
        db.session.delete(record)
        db.session.commit()
        log_activity(f"DELETED FINANCIAL REPORT {title} ({period})")
        flash(f"The saved {title} for {period} was deleted. The page now shows a fresh template.", "success")
    if kind == "billing_statement":
        student = Student.query.filter_by(student_number=period).first()
        return redirect(url_for("billing_statement", student_id=student.id) if student else url_for("billing_statement"))
    return redirect(url_for("financial_report", kind=kind, period=period))


def parse_statement_form(form):
    """Billing statement fields -> JSON-ready dict. Raises ValueError with a readable message."""
    def read_date(raw, label, required=False):
        raw = clean_text(raw)
        if not raw:
            if required:
                raise ValueError(f"{label} is required.")
            return ""
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            raise ValueError(f"{label} is not a valid date.") from None

    dates, descriptions, amounts = (form.getlist(k) for k in ("charge_date", "charge_desc", "charge_amount"))
    if not (len(dates) == len(descriptions) == len(amounts)):
        raise ValueError("The form was incomplete. Reload the page and try again.")
    if len(dates) > fr.MAX_ROWS:
        raise ValueError(f"A statement can have at most {fr.MAX_ROWS} charges.")
    charges = []
    for raw_date, raw_desc, raw_amount in zip(dates, descriptions, amounts):
        description = " ".join((raw_desc or "").split())
        if not (clean_text(raw_date) or description or clean_text(raw_amount)):
            continue
        amount = fr.parse_amount(raw_amount)
        if not description or not amount:
            raise ValueError("Each charge needs a description and an amount.")
        if len(description) > 120:
            raise ValueError("A charge description is too long (limit 120 characters).")
        charges.append({"date": read_date(raw_date, "A charge date", required=True), "description": description,
                        "amount": str(amount)})
    remit = (form.get("remit_to") or "").strip()
    if len(remit) > 400:
        raise ValueError("The “remit to” text is too long (limit 400 characters).")
    return {"forward": str(fr.parse_amount(form.get("forward"))),
            "statement_date": read_date(form.get("statement_date"), "Statement date", required=True),
            "due_date": read_date(form.get("due_date"), "Payment due date"),
            "remit_to": remit, "charges": charges}


DEFAULT_REMIT_TO = "ASIAN INSTITUTE OF COMPUTER STUDIES\nAccounting Department\nPlease write the student number on your payment."


def load_statement(record):
    try:
        raw = json.loads(record.data) if record else {}
    except (TypeError, ValueError):
        raw = {}
    data = {"forward": fr.to_decimal(raw.get("forward", 0)),
            "statement_date": raw.get("statement_date") or local_today().isoformat(),
            "due_date": raw.get("due_date") or "", "remit_to": raw.get("remit_to") or DEFAULT_REMIT_TO, "charges": []}
    for item in raw.get("charges", [])[:fr.MAX_ROWS]:
        try:
            data["charges"].append({"date": date.fromisoformat(item["date"]).isoformat(),
                                    "description": str(item["description"])[:120], "amount": fr.to_decimal(item["amount"])})
        except (KeyError, TypeError, ValueError):
            continue
    return data


def statement_activity(student, data):
    """Balance forward, charges and the student's recorded payments in date order, with a running balance."""
    try:
        as_of = date.fromisoformat(data["statement_date"])
    except ValueError:
        as_of = local_today()
    rows = []
    for charge in data["charges"]:
        day = date.fromisoformat(charge["date"])
        if day <= as_of:
            rows.append({"date": day, "order": 0, "type": "Charge", "ref": "", "description": charge["description"],
                         "charge": charge["amount"], "payment": None})
    for payment in Payment.query.filter_by(student_id=student.id).order_by(Payment.payment_date, Payment.id).all():
        stamp = payment.payment_date.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ) if payment.payment_date.tzinfo is None \
            else payment.payment_date.astimezone(LOCAL_TZ)
        if stamp.date() <= as_of:
            rows.append({"date": stamp.date(), "order": 1, "type": "Payment", "ref": payment.reference,
                         "description": f"{payment.payment_type} payment", "charge": None,
                         "payment": Decimal(payment.amount)})
    rows.sort(key=lambda r: (r["date"], r["order"]))
    balance = data["forward"]
    for row in rows:
        balance += (row["charge"] or Decimal(0)) - (row["payment"] or Decimal(0))
        row["balance"] = balance
    return rows, balance, as_of


@app.route("/financial-reports/statement", methods=["GET", "POST"])
@roles_required("Accounting", "Admin")
def billing_statement():
    student = get_or_none(Student, request.values.get("student_id"))
    record = saved_report("billing_statement", student.student_number) if student else None

    if request.method == "POST":
        if not student:
            flash("Choose a student first.", "danger")
            return redirect(url_for("billing_statement"))
        if not can_edit_reports(current_user()):
            return _error_page(403, "Access Denied", "Your account cannot change financial reports.")
        try:
            data = parse_statement_form(request.form)
            if record and request.form.get("expected_updated") != record.updated_at.isoformat():
                flash("Edit conflict: this statement was saved by someone else while you were editing. "
                      "The latest version is shown; apply your changes again if needed.", "danger")
                return redirect(url_for("billing_statement", student_id=student.id))
            payload = json.dumps(data, separators=(",", ":"))
            if record:
                record.data, record.updated_by = payload, current_user().username
                action = "EDITED"
            else:
                record = FinancialReport(kind="billing_statement", period=student.student_number, data=payload,
                                         updated_by=current_user().username)
                db.session.add(record)
                action = "CREATED"
            db.session.commit()
            log_activity(f"{action} FINANCIAL REPORT Billing Statement ({student.student_number})")
            flash("Billing statement saved.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("That statement was created by someone else at the same moment. Reload and try again.", "danger")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        return redirect(url_for("billing_statement", student_id=student.id))

    context = {"student": student, "sections": Section.query.order_by(Section.name).all(),
               "students": Student.query.options(joinedload(Student.section)).order_by(Student.last_name, Student.first_name).all(),
               "editable": can_edit_reports(current_user()), "record": record, "kinds": fr.REPORTS}
    if student:
        data = load_statement(record)
        rows, balance, as_of = statement_activity(student, data)
        due = date.fromisoformat(data["due_date"]) if data["due_date"] else None
        context.update(data=data, rows=rows, balance=balance, as_of=as_of, due=due,
                       statement_no=f"SOA-{student.student_number}-{as_of:%Y%m%d}")
    return render_template("billing_statement.html", **context)


@app.route("/courses", methods=["GET", "POST"])
@roles_required("Academic", "Admin")
def courses():
    edit_course = get_or_none(Course, request.args.get("edit"))
    if request.method == "POST":
        course_id = request.form.get("course_id", type=int)
        try:
            code = clean_text(request.form.get("code")).upper()
            name = clean_text(request.form.get("name"))
            instructor = clean_text(request.form.get("instructor"))
            units = int(request.form.get("units"))
            if not code or not name or not instructor or not 1 <= units <= 10:
                raise ValueError("Please enter valid course details.")
            if len(code) > 30 or len(name) > 120 or len(instructor) > 120:
                raise ValueError("One of the course fields is too long.")
            target = db.session.get(Course, course_id) if course_id else Course()
            if target is None:
                raise ValueError("That course could not be found.")
            duplicate = Course.query.filter(func.lower(Course.code) == code.lower())
            if course_id:
                duplicate = duplicate.filter(Course.id != course_id)
            if duplicate.first():
                flash("That course code already exists.", "danger")
                return redirect(url_for("courses", edit=course_id) if course_id else url_for("courses"))
            target.code, target.name, target.units, target.instructor = code, name, units, instructor
            if not course_id:
                db.session.add(target)
            db.session.commit()
            log_activity(f"{'EDITED' if course_id else 'CREATED'} COURSE {target.code} - {target.name}")
            flash(f"Course {target.code} saved successfully.", "success")
            return redirect(url_for("courses"))
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc) if isinstance(exc, ValueError) and str(exc) and "invalid literal" not in str(exc)
                  else "Please enter valid course details.", "danger")

    search = clean_text(request.args.get("search"))
    query = Course.query
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(Course.code.ilike(pattern), Course.name.ilike(pattern), Course.instructor.ilike(pattern)))
    return render_template("courses.html", courses=query.order_by(Course.code).all(), search=search,
                           edit_course=edit_course)


@app.route("/courses/<int:course_id>/delete", methods=["POST"])
@roles_required("Academic", "Admin")
def delete_course(course_id):
    course = db.get_or_404(Course, course_id)
    if (Grade.query.filter_by(course_id=course.id).first()
            or AssessmentScore.query.filter_by(course_id=course.id).first()
            or Attendance.query.filter_by(course_id=course.id).first()):
        flash("This course has academic or attendance records. It cannot be deleted; edit it instead to preserve history.", "danger")
        return redirect(url_for("courses"))
    code = course.code
    CurriculumCourse.query.filter_by(course_id=course.id).update({CurriculumCourse.course_id: None}, synchronize_session=False)
    db.session.delete(course)
    db.session.commit()
    log_activity(f"DELETED COURSE {code}")
    flash(f"Course {code} deleted.", "success")
    return redirect(url_for("courses"))


# -------------------------
# Academic: Grades
# -------------------------

@app.route("/grades", methods=["GET", "POST"])
@roles_required("Academic", "Registrar", "Admin")
def grades():
    section_filter = request.args.get("section_id", type=int)
    edit_grade = get_or_none(Grade, request.args.get("edit"))

    if request.method == "POST":
        try:
            student_id = int(request.form.get("student_id"))
            course_id = int(request.form.get("course_id"))
            mark = clean_text(request.form.get("mark")).upper() or None
            if mark and mark not in SPECIAL_MARKS:
                raise ValueError("Choose a valid special mark.")
            # A special mark (INC, AW, UW, NCA) replaces the numeric grade, so no percentage is needed.
            grade_value = 0.0 if mark else parse_float(request.form.get("grade"), minimum=0, maximum=100)
            semester = read_semester_form(request.form)
            if not db.session.get(Student, student_id) or not db.session.get(Course, course_id):
                raise ValueError("Choose a valid student and course.")

            grade_id = request.form.get("grade_id", type=int)
            existing = Grade.query.filter_by(student_id=student_id, course_id=course_id, semester=semester)
            if grade_id:
                existing = existing.filter(Grade.id != grade_id)
            duplicate = existing.first()
            if duplicate:
                flash("A grade for that student, course, and semester already exists. Edit that record instead.", "danger")
                return redirect(url_for("grades", edit=duplicate.id))

            if grade_id:
                grade = db.session.get(Grade, grade_id)
                if grade is None:
                    raise ValueError("That grade record could not be found.")
                expected_raw = request.form.get("expected_grade")
                expected_mark = clean_text(request.form.get("expected_mark"))
                if expected_raw not in (None, ""):
                    # Optimistic locking: the UPDATE only applies if the stored grade is still
                    # the value this user saw when the edit form was opened. Otherwise someone
                    # else changed it first, and we refuse rather than silently overwrite.
                    changed = Grade.query.filter(Grade.id == grade_id, Grade.grade == float(expected_raw),
                                                 func.coalesce(Grade.mark, "") == expected_mark).update(
                        {Grade.student_id: student_id, Grade.course_id: course_id,
                         Grade.grade: grade_value, Grade.semester: semester, Grade.mark: mark},
                        synchronize_session=False)
                    if not changed:
                        db.session.rollback()
                        flash("Edit conflict: this grade was changed by another user while you were editing. "
                              "The latest value is shown below; review it and edit again if needed.", "danger")
                        return redirect(url_for("grades", edit=grade_id))
                else:
                    grade.student_id, grade.course_id, grade.grade, grade.semester = student_id, course_id, grade_value, semester
                    grade.mark = mark
                db.session.commit()
                log_activity(f"EDITED grade record #{grade.id} for {grade.student.student_number} in {grade.course.code}")
                flash("Grade record edited successfully. The change was added to activity history.", "success")
            else:
                grade = Grade(student_id=student_id, course_id=course_id, grade=grade_value, semester=semester, mark=mark)
                db.session.add(grade)
                db.session.commit()
                log_activity(f"NEW GRADE RECORDED: {grade.student.student_number} / {grade.course.code} / {grade.shown} ({grade.semester})")
                flash(f"Grade recorded successfully: {grade.shown} ({grade.description}).", "success")
            return redirect(url_for("grades"))
        except IntegrityError:
            # The database constraint is the final guard if two requests both
            # pass the earlier duplicate lookup at nearly the same time.
            db.session.rollback()
            flash("A grade for that student, course, and semester already exists, or the record conflicts with a database rule. Refresh and try again.", "danger")
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc) if isinstance(exc, ValueError) and str(exc) and "invalid literal" not in str(exc) and "could not convert" not in str(exc)
                  else "Please check the selected student, course, grade (0-100), and semester.", "danger")

    students_query = Student.query
    if section_filter:
        students_query = students_query.filter(Student.section_id == section_filter)
    students_list = students_query.options(joinedload(Student.section)).order_by(Student.last_name, Student.first_name).all()

    search = clean_text(request.args.get("search"))
    query = (Grade.query.join(Grade.student).join(Grade.course)
             .options(contains_eager(Grade.student), contains_eager(Grade.course)))
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(Student.student_number.ilike(pattern), Student.first_name.ilike(pattern),
                                 Student.last_name.ilike(pattern), Course.code.ilike(pattern),
                                 Grade.semester.ilike(pattern)))
    rec_section = request.args.get("rec_section", type=int)
    rec_student = request.args.get("rec_student", type=int)
    if rec_section:
        query = query.filter(Student.section_id == rec_section)
    if rec_student:
        query = query.filter(Grade.student_id == rec_student)

    return render_template("grades.html", students=students_list,
                           record_students=Student.query.order_by(Student.last_name, Student.first_name).all(),
                           rec_section=rec_section, rec_student=rec_student, courses=Course.query.order_by(Course.code).all(),
                           sections=Section.query.order_by(Section.year_level, Section.name).all(),
                           section_filter=section_filter, grades=query.order_by(Grade.id.desc()).all(),
                           search=search, edit_grade=edit_grade, special_marks=SPECIAL_MARKS,
                           grading_scale=grading_scale_rows(), grading_json=[[low, grade, desc] for low, grade, desc in GRADING_SCALE],
                           failing_grade=FAILING_GRADE_EQUIVALENT,
                           filter_data=course_filter_data(students_list),
                           legacy_semester=(edit_grade.semester if edit_grade and split_semester(edit_grade.semester)[0] is None else None),
                           **semester_picker_context(edit_grade.semester if edit_grade else None))


@app.route("/grades/<int:grade_id>/delete", methods=["POST"])
@roles_required("Academic", "Admin")
def delete_grade(grade_id):
    grade = db.get_or_404(Grade, grade_id)
    description = f"grade record #{grade.id} for {grade.student.student_number} / {grade.course.code} / {grade.semester}"
    try:
        db.session.delete(grade)
        db.session.commit()
        log_activity(f"DELETED {description}")
        flash("Grade record deleted successfully.", "success")
    except Exception:
        db.session.rollback()
        app.logger.exception("Unable to delete grade record %s", grade_id)
        flash("The grade could not be deleted. Please try again.", "danger")
    return redirect(url_for("grades"))


# -------------------------
# Academic: BSIT curriculum plan (printable) and student report card (printable)
# -------------------------

# Grades are stored as a 0-100 percentage; the 1.00-5.00 equivalent comes from GRADING_SCALE (75% = 3.00 is the lowest pass).
TERM_ORDER = {"1st Semester": 1, "2nd Semester": 2, "Summer": 3}


CURRICULUM_TERMS = ("First Semester", "Second Semester", "Summer")
CURRICULUM_YEARS = tuple(sorted(YEAR_LABELS))


def can_edit_curriculum(user, action="edit"):
    """Admins always may; other staff only when an Admin granted that Curriculum action
    (Staff Accounts > Advanced module access control). Legacy accounts without a matrix are read-only."""
    if not user:
        return False
    return has_module_access(user, "curriculum", action)


def curriculum_write(action):
    """Gate a curriculum change on the Curriculum module permission (use below @roles_required())."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not can_edit_curriculum(current_user(), action):
                flash("Only an Admin, or staff an Admin has granted Curriculum access, can change the curriculum.", "danger")
                return _error_page(403, "Access Denied", f"Your account does not have {action} access to the Curriculum module.")
            return view(*args, **kwargs)
        return wrapped
    return decorator


def build_curriculum(courses, include_empty=False):
    """Group a program's course rows by year and term with calculated (never typed) unit totals."""
    by_slot = {}
    for course in courses:
        by_slot.setdefault((course.year, course.term), []).append(course)
    years = []
    for year in CURRICULUM_YEARS:
        terms = []
        for term in CURRICULUM_TERMS:
            rows = sorted(by_slot.get((year, term), []), key=lambda c: (c.position, c.id))
            if rows or include_empty:
                terms.append({"term": term, "courses": rows, "total": sum(c.units for c in rows)})
        if not terms:
            continue
        years.append({"year": year, "label": YEAR_LABELS[year], "terms": terms,
                      "total": sum(t["total"] for t in terms),
                      "draft": any(c.draft for t in terms for c in t["courses"])})
    return years


def get_curriculum_program(program_key):
    programs = CurriculumProgram.query.order_by(CurriculumProgram.position, CurriculumProgram.id).all()
    if not programs:
        return None, programs
    if not program_key:
        program_key = DEFAULT_PROGRAM
    program = next((p for p in programs if p.key == program_key), None)
    if program is None and program_key == DEFAULT_PROGRAM:
        program = programs[0]
    return program, programs


def curriculum_redirect(program, edit=True):
    year = request.form.get("view_year", type=int)
    args = {"program": program.key}
    if year in CURRICULUM_YEARS:
        args["year"] = year
    if edit:
        args["edit"] = 1
    return redirect(url_for("curriculum", **args))


def parse_curriculum_course(form):
    code = clean_text(form.get("code")).upper()
    title = clean_text(form.get("title"))
    prereq = clean_text(form.get("prereq")) or NONE_PREREQ
    try:
        units = int(form.get("units"))
    except (TypeError, ValueError):
        raise ValueError("Units must be a whole number.") from None
    if not code or not title:
        raise ValueError("Course number and descriptive title are required.")
    if len(code) > 30 or len(title) > 200 or len(prereq) > 200:
        raise ValueError("One of the course fields is too long.")
    if not 0 <= units <= 12:
        raise ValueError("Units must be between 0 and 12.")
    return code, title, units, prereq, form.get("draft") == "on"


def curriculum_code_taken(program_id, code, exclude_id=None):
    query = CurriculumCourse.query.filter(CurriculumCourse.program_id == program_id,
                                          func.lower(CurriculumCourse.code) == code.lower())
    if exclude_id:
        query = query.filter(CurriculumCourse.id != exclude_id)
    return query.first() is not None


def next_curriculum_position(program_id):
    top = db.session.query(func.max(CurriculumCourse.position)).filter_by(program_id=program_id).scalar()
    return (top or 0) + 1


NONE_PREREQ = "NONE"


@app.route("/curriculum")
@roles_required("Academic", "Registrar", "Admin")
def curriculum():
    user = current_user()
    program, programs = get_curriculum_program(request.args.get("program"))
    if program is None and not programs and not can_edit_curriculum(user, "create"):
        return render_template("error.html", code=404, title="No curriculum yet",
                               message="No curriculum programs have been set up. Ask an Admin to add one."), 404
    can_edit, can_create, can_delete = (can_edit_curriculum(user, a) for a in ("edit", "create", "delete"))
    editing = request.args.get("edit") == "1"
    if editing and not (can_edit or can_create or can_delete):
        flash("You do not have permission to edit the curriculum.", "danger")
        return redirect(url_for("curriculum", program=program.key if program else None))
    if program is None:
        if request.args.get("program"):
            abort(404)
        return render_template("curriculum.html", program=None, programs=programs, program_key=None, years=[], all_years=[],
                               selected=None, grand_total=0, editing=True, can_edit=can_edit, can_create=can_create,
                               can_delete=can_delete, terms=CURRICULUM_TERMS, year_labels=YEAR_LABELS)
    selected = request.args.get("year", type=int)
    if selected and selected not in CURRICULUM_YEARS:
        abort(404)
    # While editing, every year and term is listed (even empty ones) so courses can be added anywhere.
    all_years = build_curriculum(program.courses, include_empty=editing)
    years = [y for y in all_years if y["year"] == selected] if selected else all_years
    if selected and not years:
        abort(404)
    return render_template("curriculum.html", years=years, all_years=all_years, selected=selected,
                           grand_total=sum(y["total"] for y in all_years),
                           program=program, program_key=program.key, programs=programs, editing=editing,
                           can_edit=can_edit, can_create=can_create, can_delete=can_delete,
                           terms=CURRICULUM_TERMS, year_labels=YEAR_LABELS)


@app.route("/curriculum/<int:program_id>/courses/add", methods=["POST"])
@roles_required()
@curriculum_write("create")
def add_curriculum_course(program_id):
    program = db.get_or_404(CurriculumProgram, program_id)
    year, term = request.form.get("year", type=int), clean_text(request.form.get("term"))
    try:
        if year not in CURRICULUM_YEARS or term not in CURRICULUM_TERMS:
            raise ValueError("Choose a valid year and term.")
        code, title, units, prereq, draft = parse_curriculum_course(request.form)
        if curriculum_code_taken(program.id, code):
            raise ValueError(f"{code} is already in the {program.short} curriculum.")
        row = CurriculumCourse(program_id=program.id, year=year, term=term, code=code, title=title,
                               units=units, prereq=prereq, draft=draft,
                               position=next_curriculum_position(program.id))
        db.session.add(row)
        db.session.flush()
        link_curriculum_course(row)  # also lists it in the Course List
        db.session.commit()
        log_activity(f"CREATED CURRICULUM COURSE {code} in {program.short}, {YEAR_LABELS[year]} {term}")
        flash(f"{code} added to {YEAR_LABELS[year]} · {term}.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return curriculum_redirect(program)


@app.route("/curriculum/courses/<int:course_id>/edit", methods=["POST"])
@roles_required()
@curriculum_write("edit")
def edit_curriculum_course(course_id):
    course = db.get_or_404(CurriculumCourse, course_id)
    program = course.program
    try:
        code, title, units, prereq, draft = parse_curriculum_course(request.form)
        if curriculum_code_taken(program.id, code, exclude_id=course.id):
            raise ValueError(f"{code} is already in the {program.short} curriculum.")
        course.code, course.title, course.units, course.prereq, course.draft = code, title, units, prereq, draft
        link_curriculum_course(course)  # keep the Course List entry in step
        db.session.commit()
        log_activity(f"EDITED CURRICULUM COURSE {code} in {program.short}")
        flash(f"{code} updated.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return curriculum_redirect(program)


@app.route("/curriculum/courses/<int:course_id>/delete", methods=["POST"])
@roles_required()
@curriculum_write("delete")
def delete_curriculum_course(course_id):
    course = db.get_or_404(CurriculumCourse, course_id)
    program, code = course.program, course.code
    db.session.delete(course)
    db.session.commit()
    log_activity(f"DELETED CURRICULUM COURSE {code} from {program.short}")
    flash(f"{code} removed from the curriculum.", "success")
    return curriculum_redirect(program)


def read_program_fields(form):
    short, name = clean_text(form.get("short")), clean_text(form.get("name"))
    reference, note = clean_text(form.get("reference")), clean_text(form.get("draft_note"))
    if not short or not name:
        raise ValueError("Program short name and full name are required.")
    if len(short) > 40 or len(name) > 100 or len(reference) > 300 or len(note) > 1000:
        raise ValueError("One of the program fields is too long.")
    return short, name, reference, note, form.get("draft_all") == "on"


@app.route("/curriculum/programs/add", methods=["POST"])
@roles_required()
@curriculum_write("create")
def add_curriculum_program():
    try:
        short, name, reference, note, draft_all = read_program_fields(request.form)
        base = re.sub(r"[^A-Za-z0-9]+", "", short)[:24] or "PROGRAM"
        key, n = base, 2
        while CurriculumProgram.query.filter(func.lower(CurriculumProgram.key) == key.lower()).first():
            key, n = f"{base}{n}", n + 1
        position = (db.session.query(func.max(CurriculumProgram.position)).scalar() or 0) + 1
        program = CurriculumProgram(key=key, short=short, name=name, reference=reference, draft_all=draft_all,
                                    draft_note=note, position=position)
        db.session.add(program)
        db.session.commit()
        log_activity(f"CREATED CURRICULUM PROGRAM {short} - {name}")
        flash(f"Program {short} created. Add its courses below.", "success")
        return redirect(url_for("curriculum", program=program.key, edit=1))
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("curriculum", program=request.form.get("current_program") or None, edit=1))


@app.route("/curriculum/programs/<int:program_id>/edit", methods=["POST"])
@roles_required()
@curriculum_write("edit")
def edit_curriculum_program(program_id):
    program = db.get_or_404(CurriculumProgram, program_id)
    try:
        old_name = program.name
        program.short, program.name, program.reference, program.draft_note, program.draft_all = read_program_fields(request.form)
        if program.name != old_name:  # students store the program name, so keep their records in step
            Student.query.filter_by(course=old_name).update({"course": program.name})
        db.session.commit()
        log_activity(f"EDITED CURRICULUM PROGRAM {program.short}")
        flash(f"Program {program.short} updated.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return curriculum_redirect(program)


@app.route("/curriculum/programs/<int:program_id>/delete", methods=["POST"])
@roles_required()
@curriculum_write("delete")
def delete_curriculum_program(program_id):
    program = db.get_or_404(CurriculumProgram, program_id)
    short = program.short
    db.session.delete(program)
    db.session.commit()
    log_activity(f"DELETED CURRICULUM PROGRAM {short}")
    flash(f"Program {short} and its courses were deleted.", "success")
    return redirect(url_for("curriculum", edit=1))


def seed_curriculum():
    """Copy the starting curricula from curriculum_data.py into the database on first run only.
    After that the database is the source of truth and is edited from the Curriculum page."""
    if CurriculumProgram.query.count():
        return
    for order, (key, data) in enumerate(PROGRAMS.items(), start=1):
        program = CurriculumProgram(key=key, short=data["short"], name=data["name"], reference=data["reference"],
                                    draft_all=bool(data["draft_all"]), draft_note=data["draft_note"], position=order)
        position = 0
        for block in data["blocks"]:
            for code, title, units, prereq in block["courses"]:
                position += 1
                program.courses.append(CurriculumCourse(year=block["year"], term=block["term"], code=code, title=title,
                                                        units=units, prereq=prereq, draft=bool(block.get("draft")),
                                                        position=position))
        db.session.add(program)
    db.session.commit()


# Faculty for the Computer Science (CC / CS / MATH) subjects, and a general pool for everything else.
CS_FACULTY = ["Prof. Bhats", "Prof. Toliongco", "Prof. Sevilla", "Prof. May", "Prof. Bendiro", "Prof. Dela Cruz", "Prof. Seno"]
GENERAL_FACULTY = ["Prof. Ramos", "Prof. Villanueva", "Prof. Aquino", "Prof. Mendoza", "Prof. Castillo", "Prof. Navarro",
                   "Prof. Domingo", "Prof. Pascual", "Prof. Hernandez", "Prof. Soriano", "Prof. Bautista", "Prof. Fernandez",
                   "Prof. Salazar", "Prof. Manalo", "Prof. Lim", "Prof. Tan"]
CS_PREFIXES = {"CC", "CS", "MATH"}


def pick_instructor(program_key, code):
    """Stable (not random per run) instructor choice. A lecture and its laboratory share one instructor."""
    base = re.sub(r"\s+L$", "", code.strip().upper())
    prefix = base.split()[0] if base.split() else base
    pool = CS_FACULTY if program_key == "BSCS" and prefix in CS_PREFIXES else GENERAL_FACULTY
    return pool[zlib.crc32(base.encode("utf-8")) % len(pool)]


def _course_matches(course, title, units):
    return course is not None and course.name == title[:120] and course.units == units


def link_curriculum_course(row):
    """Make sure a curriculum row has a matching entry in the Course List and link it. Does not commit.

    Course codes are unique in the Course List, but different programs reuse a code for different
    subjects (e.g. GE 103). The first subject keeps the plain code; a clash gets the program in brackets."""
    title, units, program = row.title[:120], row.units, row.program
    # A row that is the only user of its Course List entry keeps that entry up to date when it is edited.
    if row.course_id and row.course is not None:
        shared = CurriculumCourse.query.filter(CurriculumCourse.course_id == row.course_id, CurriculumCourse.id != row.id).count()
        if not shared:
            clash = Course.query.filter(func.lower(Course.code) == row.code.lower(), Course.id != row.course_id).first()
            if not clash:
                row.course.code, row.course.name, row.course.units = row.code, title, units
                return row.course
    for code in (row.code, f"{row.code} ({program.short})"[:30]):
        existing = Course.query.filter(func.lower(Course.code) == code.lower()).first()
        if _course_matches(existing, title, units):
            row.course = existing
            return existing
        if existing is None:
            course = Course(code=code, name=title, units=units, instructor=pick_instructor(program.key, row.code))
            db.session.add(course)
            db.session.flush()
            row.course = course
            return course
    # Even the program-suffixed code is taken by a different subject: leave it unlinked rather than guess.
    return None


def sync_curriculum_to_courses():
    """One-time import of every curriculum subject into the Course List (skipped once any row is linked,
    so a course an Admin later deletes does not come back on restart)."""
    if CurriculumCourse.query.filter(CurriculumCourse.course_id.isnot(None)).first():
        return
    rows = (CurriculumCourse.query.join(CurriculumProgram)
            .order_by(CurriculumProgram.position, CurriculumProgram.id, CurriculumCourse.year,
                      CurriculumCourse.position, CurriculumCourse.id).all())
    for row in rows:
        link_curriculum_course(row)
    db.session.commit()


TERM_FROM_CURRICULUM = {"First Semester": "1st Semester", "Second Semester": "2nd Semester", "Summer": "Summer"}


def course_filter_data(students):
    """JSON-ready data for the Grades / Assessments forms: which Course List entries belong to a student's
    program, year level and semester, plus each student's program and year."""
    programs = {p.name: p.id for p in CurriculumProgram.query.all()}
    plan = {}
    for program_id, year, term, course_id in (db.session.query(CurriculumCourse.program_id, CurriculumCourse.year,
                                                                CurriculumCourse.term, CurriculumCourse.course_id)
                                              .filter(CurriculumCourse.course_id.isnot(None))):
        slot = plan.setdefault(str(program_id), {}).setdefault(str(year), {}).setdefault(TERM_FROM_CURRICULUM.get(term, term), [])
        if course_id not in slot:
            slot.append(course_id)
    meta = {str(s.id): {"program": programs.get(s.course), "year": s.year_level} for s in students}
    return {"plan": plan, "students": meta}


def semester_sort_key(label):
    """Oldest first: school year, then 1st Sem -> 2nd Sem -> Summer."""
    match = re.search(r"(\d{4})-\d{4}", label or "")
    term = next((order for name, order in TERM_ORDER.items() if (label or "").startswith(name)), 9)
    return (int(match.group(1)) if match else 0, term, label or "")


SEMESTER_BADGES = {"1st Semester": "1ST SEMESTER", "2nd Semester": "2ND SEMESTER", "Summer": "SUMMER"}


def remark_for(grade):
    return grade_remark(grade)


@app.route("/students/<int:student_id>/report-card")
@roles_required("Registrar", "Academic", "Admin")
def report_card(student_id):
    student = db.get_or_404(Student, student_id)
    records = (Grade.query.filter_by(student_id=student.id).options(joinedload(Grade.course)).all())
    semesters = sorted({g.semester for g in records}, key=semester_sort_key)
    chosen = clean_text(request.args.get("semester"))
    if chosen != "all":
        chosen = chosen if chosen in semesters else (semesters[-1] if semesters else "")
    shown = sorted(semesters if chosen == "all" else ([chosen] if chosen else []), key=semester_sort_key)

    terms, graded_units, weighted_points, passed_units = [], 0, 0.0, 0
    for semester in shown:
        rows = sorted((g for g in records if g.semester == semester), key=lambda g: g.course.code)
        counted = [g for g in rows if g.equivalent is not None]  # INC and AW are not graded
        units = sum(g.course.units for g in counted)
        points = sum(g.equivalent * g.course.units for g in counted)
        term_passed = sum(g.course.units for g in rows if grade_is_passed(g.grade, g.mark))
        term_name, school_year = split_semester(semester)
        terms.append({"semester": semester, "term": term_name, "school_year": school_year,
                      "badge": SEMESTER_BADGES.get(term_name, (term_name or semester).upper()),
                      "rows": rows, "units": units, "passed_units": term_passed,
                      "average": round(points / units, 2) if units else None})
        graded_units += units; weighted_points += points; passed_units += term_passed

    attendance = {}
    for course_id, status, count in (db.session.query(Attendance.course_id, Attendance.status, func.count(Attendance.id))
                                     .filter(Attendance.student_id == student.id)
                                     .group_by(Attendance.course_id, Attendance.status)):
        attendance.setdefault(course_id, {})[status] = count
    totals = {s: sum(v.get(s, 0) for v in attendance.values()) for s in ("Present", "Late", "Absent", "Excused")}

    return render_template("report_card.html", student=student, terms=terms, semesters=semesters, chosen=chosen,
                           single_period=(terms[0] if len(terms) == 1 else None),
                           general_average=round(weighted_points / graded_units, 2) if graded_units else None,
                           graded_units=graded_units, passed_units=passed_units,
                           grading_scale=grading_scale_rows(), special_marks=SPECIAL_MARKS,
                           attendance=attendance, attendance_totals=totals,
                           issued_on=local_today(), issued_by=current_user().username)


# -------------------------
# Academic: Assessments (scores and weighted course-grade calculation)
# -------------------------

def calculate_weighted_grade(records):
    """Weighted grade out of 100 from assessment records.

    Each component's earned/possible points are weighted; components with no
    records are left out and the remaining weights are renormalised so that
    missing components do not count as zero.
    """
    component_scores = {}
    for component in ASSESSMENT_WEIGHTS:
        items = [r for r in records if r.component == component]
        possible = sum(r.max_score for r in items)
        if items and possible:
            component_scores[component] = sum(r.score for r in items) / possible * 100
    active_weight = sum(ASSESSMENT_WEIGHTS[k] for k in component_scores)
    if not active_weight:
        return 0.0
    return sum(score * ASSESSMENT_WEIGHTS[k] for k, score in component_scores.items()) / active_weight


@app.route("/assessments", methods=["GET", "POST"])
@roles_required("Academic", "Admin")
def assessments():
    edit_score = get_or_none(AssessmentScore, request.args.get("edit"))

    if request.method == "POST":
        action = request.form.get("action", "save")
        try:
            student = db.session.get(Student, int(request.form.get("student_id")))
            course = db.session.get(Course, int(request.form.get("course_id")))
            if not student or not course:
                raise ValueError
            semester = read_semester_form(request.form)

            if action == "calculate":
                records = AssessmentScore.query.filter_by(student_id=student.id, course_id=course.id, semester=semester).all()
                if not records:
                    flash("No assessment records found for that student, course, and semester.", "danger")
                    return redirect(url_for("assessments"))
                computed = round(calculate_weighted_grade(records), 2)
                grade = Grade.query.filter_by(student_id=student.id, course_id=course.id, semester=semester).first()
                if grade:
                    grade.grade, grade.mark = computed, None
                else:
                    db.session.add(Grade(student_id=student.id, course_id=course.id, semester=semester, grade=computed))
                db.session.commit()
                log_activity(f"CALCULATED GRADE from accumulated assessments: {student.student_number} / {course.code} / {semester} = {computed:.2f}")
                equivalent, description = percentage_to_equivalent(computed)
                flash(f"Calculated grade {computed:.2f}/100 = {equivalent:.2f} ({description}) was saved to Grade Records. Check your school's grading policy before using it as an official grade.", "success")
                return redirect(url_for("grades", search=student.student_number))

            category = clean_text(request.form.get("category"))
            component = clean_text(request.form.get("component"))
            title = clean_text(request.form.get("title"))
            max_score = parse_float(request.form.get("max_score"), minimum=0.01, maximum=1_000_000)
            score = parse_float(request.form.get("score"), minimum=0, maximum=max_score)
            if component not in ASSESSMENT_WEIGHTS or not title or len(title) > 120:
                raise ValueError

            score_id = request.form.get("score_id", type=int)
            item = db.session.get(AssessmentScore, score_id) if score_id else None
            if score_id and item is None:
                raise ValueError
            # The assessment type must belong to the chosen component. An old record may keep its legacy type.
            if category not in ASSESSMENT_TYPES[component] and not (item and item.category == category and item.component == component):
                raise ValueError(f"Choose a valid assessment type for {component}.")
            if score_id:
                item.student_id, item.course_id, item.semester = student.id, course.id, semester
                item.category, item.component, item.title = category, component, title
                item.score, item.max_score = score, max_score  # created_by stays the original recorder
                db.session.commit()
                log_activity(f"EDITED {category.upper()} ASSESSMENT #{item.id} for {student.student_number}, {course.code}")
                flash("Assessment record updated.", "success")
            else:
                db.session.add(AssessmentScore(student_id=student.id, course_id=course.id, semester=semester,
                                               category=category, component=component, title=title, score=score,
                                               max_score=max_score, weight=100.0, created_by=current_user().username))
                db.session.commit()
                log_activity(f"RECORDED {category.upper()} ASSESSMENT '{title}' for {student.student_number}, {course.code}")
                flash("Assessment score recorded. It is stored in Assessment Records until you calculate the course grade.", "success")
            return redirect(url_for("assessments"))
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc) if isinstance(exc, ValueError) and str(exc) and "could not convert" not in str(exc)
                  else "Check the student, course, score, maximum score, component, assessment type, and semester fields.", "danger")

    student_filter = request.args.get("student_id", type=int)
    section_filter = request.args.get("section_id", type=int)
    course_filter = request.args.get("course_id", type=int)
    query = (AssessmentScore.query.join(AssessmentScore.student)
             .options(contains_eager(AssessmentScore.student).joinedload(Student.section),
                      joinedload(AssessmentScore.course)))
    if student_filter:
        query = query.filter(AssessmentScore.student_id == student_filter)
    if section_filter:
        query = query.filter(Student.section_id == section_filter)
    if course_filter:
        query = query.filter(AssessmentScore.course_id == course_filter)
    scores = query.order_by(AssessmentScore.created_at.desc()).limit(500).all()

    all_students = Student.query.options(joinedload(Student.section)).order_by(Student.last_name, Student.first_name).all()
    return render_template("assessments.html",
                           students=all_students, filter_data=course_filter_data(all_students),
                           courses=Course.query.order_by(Course.code).all(),
                           sections=Section.query.order_by(Section.year_level, Section.name).all(),
                           scores=scores, edit_score=edit_score, student_filter=student_filter,
                           section_filter=section_filter, course_filter=course_filter,
                           assessment_weights=ASSESSMENT_WEIGHTS, assessment_types=ASSESSMENT_TYPES,
                           **semester_picker_context(edit_score.semester if edit_score else None))


@app.route("/assessments/<int:score_id>/delete", methods=["POST"])
@roles_required("Academic", "Admin")
def delete_assessment(score_id):
    item = db.get_or_404(AssessmentScore, score_id)
    description = f"{item.category} '{item.title}' for {item.student.student_number} / {item.course.code}"
    db.session.delete(item)
    db.session.commit()
    log_activity(f"DELETED ASSESSMENT {description}")
    flash("Assessment record deleted. Recalculate the grade if needed.", "success")
    return redirect(url_for("assessments"))


# -------------------------
# Academic: Attendance
# -------------------------

@app.route("/attendance", methods=["GET", "POST"])
@roles_required("Academic", "Admin")
def attendance():
    selected_date = clean_text(request.args.get("date") or request.form.get("attendance_date") or local_today().isoformat())
    if request.method == "POST":
        try:
            student = db.session.get(Student, int(request.form.get("student_id", "")))
            course = db.session.get(Course, int(request.form.get("course_id", "")))
            attendance_date = date.fromisoformat(request.form.get("attendance_date", ""))
            status = clean_text(request.form.get("status"))
            note = clean_text(request.form.get("note"))[:250]
            if not student or not course or status not in ATTENDANCE_STATUSES:
                raise ValueError
            record = Attendance.query.filter_by(student_id=student.id, course_id=course.id,
                                                attendance_date=attendance_date).first()
            if record:
                record.status, record.note, record.recorded_by = status, note or None, current_user().username
                action = "UPDATED"
            else:
                record = Attendance(student_id=student.id, course_id=course.id, attendance_date=attendance_date,
                                    status=status, note=note or None, recorded_by=current_user().username)
                db.session.add(record)
                action = "RECORDED"
            try:
                db.session.commit()
            except IntegrityError:
                # Another request inserted the same student/course/date between our lookup
                # and our insert. The unique constraint stopped the duplicate; apply our
                # values to the row that won instead of failing with a server error.
                db.session.rollback()
                record = Attendance.query.filter_by(student_id=student.id, course_id=course.id,
                                                    attendance_date=attendance_date).first()
                if record is None:
                    raise
                record.status, record.note, record.recorded_by = status, note or None, current_user().username
                action = "UPDATED"
                db.session.commit()
            log_activity(f"{action} attendance: {student.student_number} / {course.code} / {attendance_date.isoformat()} / {status}")
            flash("Attendance updated successfully." if action == "UPDATED" else "Attendance recorded successfully.", "success")
            return redirect(url_for("attendance", date=attendance_date.isoformat()))
        except (ValueError, TypeError):
            db.session.rollback()
            flash("Please select a valid student, course, date, and attendance status.", "danger")

    try:
        selected_day = date.fromisoformat(selected_date)
    except ValueError:
        selected_day = local_today()
        selected_date = selected_day.isoformat()
        flash("Invalid date selected. Showing today's attendance.", "warning")
    section_filter = request.args.get("section_id", type=int)
    records_query = (Attendance.query.join(Attendance.student).join(Attendance.course)
               .options(contains_eager(Attendance.student), contains_eager(Attendance.course))
               .filter(Attendance.attendance_date == selected_day))
    if section_filter:
        records_query = records_query.filter(Student.section_id == section_filter)
    course_filter = request.args.get("course_id", type=int)
    if course_filter:
        records_query = records_query.filter(Attendance.course_id == course_filter)
    records = records_query.order_by(Student.last_name, Student.first_name, Course.code).all()
    status_counts = {status: sum(1 for r in records if r.status == status) for status in ATTENDANCE_STATUSES}
    all_students = Student.query.options(joinedload(Student.section)).order_by(Student.last_name, Student.first_name).all()
    return render_template("attendance.html", students=all_students, filter_data=course_filter_data(all_students),
                           term_options=TERM_OPTIONS, course_filter=course_filter,
                           sections=Section.query.order_by(Section.name).all(), section_filter=section_filter,
                           courses=Course.query.order_by(Course.code).all(), records=records,
                           selected_date=selected_date, statuses=ATTENDANCE_STATUSES, status_counts=status_counts)


# -------------------------
# Parallel / concurrency demo
# -------------------------

CONCURRENCY_TASKS = 10
CONCURRENCY_WORKERS = 5


def run_counter_trial(use_lock):
    """Increment a shared counter from several threads, with or without a lock.

    Every call gets its own counter, so simultaneous visitors cannot disturb
    each other. Without the lock, tasks read the same value and overwrite each
    other's updates (a race condition).
    """
    state = {"value": 0}
    lock = threading.Lock()

    def increment():
        before = state["value"]
        time.sleep(0.05)  # simulated work between reading and writing
        state["value"] = before + 1
        return before, before + 1

    def task(number):
        if use_lock:
            with lock:
                before, after = increment()
        else:
            before, after = increment()
        return {"task": number, "before": before, "after": after}

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CONCURRENCY_WORKERS) as executor:
        results = list(executor.map(task, range(1, CONCURRENCY_TASKS + 1)))
    return {"results": results, "final": state["value"], "ms": round((time.perf_counter() - started) * 1000, 1)}


@app.route("/concurrency")
@roles_required()
def concurrency():
    safe = run_counter_trial(use_lock=True)
    unsafe = run_counter_trial(use_lock=False)
    log_activity(f"Ran concurrency demo: {CONCURRENCY_TASKS} tasks, locked {safe['final']}/{CONCURRENCY_TASKS}, unlocked {unsafe['final']}/{CONCURRENCY_TASKS}")
    return render_template("concurrency.html", safe=safe, unsafe=unsafe, task_count=CONCURRENCY_TASKS,
                           worker_count=CONCURRENCY_WORKERS)


# -------------------------
# Personal account settings
# -------------------------

@app.route("/account", methods=["GET", "POST"])
@roles_required()
def manage_account():
    user = current_user()
    if request.method == "POST":
        username = clean_text(request.form.get("username"))
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        duplicate = User.query.filter(func.lower(User.username) == username.lower(), User.id != user.id).first()
        if not USERNAME_RE.fullmatch(username):
            flash("Username must be 3–50 characters and use letters, numbers, dots, underscores, or hyphens.", "danger")
        elif duplicate:
            flash("That username is already in use.", "danger")
        elif new_password and (not user.check_password(current_password) or len(new_password) < 12):
            flash("To change your password, enter your current password and a new password of at least 12 characters.", "danger")
        else:
            try:
                new_image = save_image(request.files.get("profile_image"), "user")
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("manage_account"))
            old_username, old_image = user.username, user.profile_image
            user.username = username
            if new_image:
                user.profile_image = new_image
            if new_password:
                user.set_password(new_password)
            db.session.commit()
            if new_image:
                delete_upload(old_image)
            log_activity(f"UPDATED ACCOUNT PROFILE for {old_username}; username now {username}" + ("; password changed" if new_password else ""))
            flash("Account settings updated.", "success")
            return redirect(url_for("manage_account"))
    return render_template("account.html", user=user)


# -------------------------
# Admin-only staff management (no public self-registration)
# -------------------------

@app.route("/staff", methods=["GET", "POST"])
@roles_required("Admin")
def staff_management():
    edit_user = get_or_none(User, request.args.get("edit"))
    if request.method == "POST":
        user_id = request.form.get("user_id", type=int)
        username = clean_text(request.form.get("username"))
        password = request.form.get("password", "")
        role = clean_text(request.form.get("role"))
        activity_types = ["CREATED", "EDITED", "UPDATED", "DELETED", "RECORDED", "CALCULATED", "LOGIN", "LOGOUT", "FAILED_LOGIN"]
        selected_visibility = [item for item in request.form.getlist("activity_visibility") if item in activity_types]
        activity_departments = [item for item in request.form.getlist("activity_departments") if item in ("Registrar", "Accounting", "Academic")]
        access_modules = list(ACCESS_MODULE_LABELS)
        grant_everything = request.form.get("grant_everything") == "on"
        selected_permissions = {}
        for module in access_modules:
            selected = [action for action in ACCESS_ACTIONS if request.form.get(f"perm_{module}_{action}") == "on"]
            if grant_everything:
                selected = list(ACCESS_ACTIONS)
            selected_permissions[module] = selected
        if request.form.get("can_manage_teachers_timetable") == "on":
            for module in ("instructors", "timetable"):
                selected_permissions[module] = list(ACCESS_ACTIONS)
        for module in ADMIN_ONLY_MODULES:
            selected_permissions[module] = []  # never delegable
        target = db.session.get(User, user_id) if user_id else User()
        duplicate = User.query.filter(func.lower(User.username) == username.lower())
        if user_id:
            duplicate = duplicate.filter(User.id != user_id)

        if target is None:
            flash("That staff account could not be found.", "danger")
            return redirect(url_for("staff_management"))
        if not USERNAME_RE.fullmatch(username) or role not in ROLES:
            flash("Use a valid username (3–50 letters, numbers, dots, underscores, hyphens) and role.", "danger")
        elif (not user_id or password) and len(password) < 12:
            flash("Passwords must be at least 12 characters.", "danger")
        elif duplicate.first():
            flash("That username already exists.", "danger")
        elif user_id and target.id == current_user().id and role != "Admin":
            flash("You cannot remove your own Admin role while logged in.", "danger")
        else:
            target.username, target.role = username, role
            target.activity_visibility = json.dumps(selected_visibility)
            target.activity_departments = json.dumps(activity_departments)
            # Admin retains full control; non-admin accounts receive only checked module actions.
            target.access_permissions = None if role == "Admin" else json.dumps(selected_permissions)
            target.can_manage_teachers_timetable = (role == "Admin" or any(selected_permissions.get(m) for m in ("instructors", "timetable")))
            if password:
                target.set_password(password)
            if not user_id:
                db.session.add(target)
            db.session.commit()
            log_activity(f"{'EDITED' if user_id else 'CREATED'} STAFF ACCOUNT: {username}, role {role}")
            flash("Staff account saved successfully.", "success")
            return redirect(url_for("staff_management"))
    return render_template("staff.html", staff=User.query.order_by(User.role, User.username).all(),
                           edit_user=edit_user, roles=ROLES,
                           activity_types=["CREATED", "EDITED", "UPDATED", "DELETED", "RECORDED", "CALCULATED", "LOGIN", "LOGOUT", "FAILED_LOGIN"],
                           edit_visibility=(json.loads(edit_user.activity_visibility) if edit_user and edit_user.activity_visibility else ["CREATED", "EDITED", "UPDATED", "DELETED", "RECORDED", "CALCULATED", "LOGIN", "LOGOUT", "FAILED_LOGIN"]),
                           activity_departments=["Registrar", "Accounting", "Academic"],
                           access_modules=ACCESS_MODULE_LABELS,
                           access_actions=ACCESS_ACTIONS,
                           admin_only_modules=sorted(ADMIN_ONLY_MODULES),
                           role_defaults={r: default_access_for_role(r) for r in ROLES if r != "Admin"},
                           edit_permissions=(get_access_permissions(edit_user) if edit_user and edit_user.access_permissions else default_access_for_role(edit_user.role, edit_user) if edit_user else default_access_for_role(request.form.get("role", "Registrar"))),
                           edit_departments=(json.loads(edit_user.activity_departments) if edit_user and edit_user.activity_departments else ([edit_user.role] if edit_user and edit_user.role in ("Registrar", "Accounting", "Academic") else [])))


@app.route("/staff/<int:user_id>/delete", methods=["POST"])
@roles_required("Admin")
def delete_staff(user_id):
    target = db.get_or_404(User, user_id)
    if target.id == current_user().id:
        flash("You cannot delete the account you're currently using.", "danger")
        return redirect(url_for("staff_management"))
    username, role, image = target.username, target.role, target.profile_image
    # SQLite does not enforce ON DELETE CASCADE unless foreign keys are switched on, so remove this
    # account's messages (and their attachment files) explicitly; PostgreSQL would cascade anyway.
    for message in DepartmentMessage.query.filter(or_(DepartmentMessage.sender_id == target.id,
                                                      DepartmentMessage.recipient_user_id == target.id)).all():
        delete_attachment_files(message)
        db.session.delete(message)
    db.session.delete(target)
    db.session.commit()
    delete_upload(image)
    log_activity(f"DELETED STAFF ACCOUNT: {username}, role {role}")
    flash(f"Staff account '{username}' deleted.", "success")
    return redirect(url_for("staff_management"))


# -------------------------
# Instructors and weekly timetable
# -------------------------
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

def teacher_permission_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        module = ACCESS_MODULES.get(request.endpoint, "instructors")
        action = required_access_action(request.endpoint)
        if not has_module_access(user, module, action):
            return _error_page(403, "Access Denied", f"Your account does not have {action} access to this module.")
        return view(*args, **kwargs)
    return wrapped

def lock_timetable():
    """Serialize timetable writes. Call before checking for clashes; commit or rollback releases it."""
    for _ in range(3):
        changed = ScheduleLock.query.filter_by(id=1).update(
            {ScheduleLock.version: ScheduleLock.version + 1}, synchronize_session=False)
        if changed:
            return
        try:  # first use on this database: create the lock row (a racing request may win; then retry)
            db.session.add(ScheduleLock(id=1, version=0))
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
    raise ValueError("The timetable is busy. Please try again.")

def schedule_conflicts(day, start, end, teacher_id, classroom, section_id, exclude_id=None):
    conflicts=[]
    for item in ClassSchedule.query.filter_by(day=day).all():
        if exclude_id and item.id == exclude_id: continue
        if start < item.end_time and end > item.start_time:
            if item.teacher_id == teacher_id: conflicts.append(f"Instructor conflict: {item.teacher.name} already has {item.start_time}–{item.end_time}.")
            if item.classroom.strip().lower() == classroom.strip().lower(): conflicts.append(f"Room conflict: {classroom} is already booked {item.start_time}–{item.end_time}.")
            if item.section_id == section_id: conflicts.append(f"Section conflict: {item.section.name} already has a class {item.start_time}–{item.end_time}.")
    return conflicts

@app.route("/teachers", methods=["GET", "POST"])
@teacher_permission_required
def teachers():
    edit_teacher = db.session.get(Teacher, request.args.get("edit", type=int)) if request.args.get("edit") else None
    if request.method == "POST":
        tid=request.form.get("teacher_id", type=int)
        teacher=db.session.get(Teacher, tid) if tid else Teacher()
        name=clean_text(request.form.get("name")); email=clean_text(request.form.get("email")).lower()
        subjects=clean_text(request.form.get("subjects")); employment=request.form.get("employment_type", "Full-time")
        days=[d for d in request.form.getlist("working_days") if d in WEEKDAYS]
        start=request.form.get("available_start", "07:00"); end=request.form.get("available_end", "17:00")
        duplicate=Teacher.query.filter(func.lower(Teacher.email)==email)
        if tid: duplicate=duplicate.filter(Teacher.id != tid)
        if not teacher or not name or "@" not in email or not subjects or employment not in ["Full-time", "Part-time"] or not days or start >= end:
            flash("Please complete all instructor fields with valid availability.", "danger")
        elif duplicate.first(): flash("An instructor with that email already exists.", "danger")
        else:
            teacher.name=name; teacher.email=email; teacher.subjects=subjects; teacher.employment_type=employment
            teacher.working_days=",".join(days); teacher.available_start=start; teacher.available_end=end
            db.session.add(teacher); db.session.commit(); log_activity(f"{'EDITED' if tid else 'CREATED'} Instructor: {name}")
            flash("Instructor record saved.", "success"); return redirect(url_for("teachers"))
    return render_template("teachers.html", teachers=Teacher.query.order_by(Teacher.name).all(), edit_teacher=edit_teacher, weekdays=WEEKDAYS)

@app.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@teacher_permission_required
def delete_teacher(teacher_id):
    teacher=db.get_or_404(Teacher, teacher_id)
    if ClassSchedule.query.filter_by(teacher_id=teacher.id).first():
        flash("This instructor is assigned to a class. Remove or reassign those classes first.", "danger")
    else:
        name=teacher.name; db.session.delete(teacher); db.session.commit(); log_activity(f"DELETED Instructor: {name}"); flash("Instructor removed.", "success")
    return redirect(url_for("teachers"))

@app.route("/timetable", methods=["GET", "POST"])
@teacher_permission_required
def timetable():
    edit_class=db.session.get(ClassSchedule, request.args.get("edit", type=int)) if request.args.get("edit") else None
    if request.method == "POST":
        sid=request.form.get("schedule_id", type=int); item=db.session.get(ClassSchedule, sid) if sid else ClassSchedule()
        day=request.form.get("day", ""); start=request.form.get("start_time", ""); end=request.form.get("end_time", "")
        subject=clean_text(request.form.get("subject")); teacher_id=request.form.get("teacher_id", type=int)
        classroom=clean_text(request.form.get("classroom")); section_id=request.form.get("section_id", type=int)
        if not item or day not in WEEKDAYS or not start or not end or start >= end or not subject or not classroom or not db.session.get(Teacher, teacher_id) or not db.session.get(Section, section_id):
            flash("Please complete all class schedule fields. End time must be after start time.", "danger")
        else:
            try:
                lock_timetable()  # from here until commit/rollback no other request can change the timetable
            except ValueError as exc:
                db.session.rollback(); flash(str(exc), "danger")
                return redirect(url_for("timetable"))
            teacher=db.session.get(Teacher, teacher_id); db.session.refresh(teacher)
            if sid:  # the class may have been changed or removed while we waited for the lock
                item=db.session.get(ClassSchedule, sid, populate_existing=True)
                if item is None:
                    db.session.rollback(); flash("That class was removed by someone else.", "danger")
                    return redirect(url_for("timetable"))
            problems=schedule_conflicts(day,start,end,teacher_id,classroom,section_id,sid)
            if day not in teacher.working_days.split(",") or start < teacher.available_start or end > teacher.available_end:
                problems.append(f"Instructor availability conflict: {teacher.name} is not available for that day/time.")
            if problems:
                db.session.rollback()  # release the timetable lock
                for problem in problems: flash(problem, "danger")
            else:
                item.day=day; item.start_time=start; item.end_time=end; item.subject=subject; item.teacher_id=teacher_id; item.classroom=classroom; item.section_id=section_id
                db.session.add(item); db.session.commit(); log_activity(f"{'EDITED' if sid else 'CREATED'} CLASS: {subject} {day} {start}-{end}")
                flash("Class schedule saved.", "success"); return redirect(url_for("timetable"))
    schedules=ClassSchedule.query.all()
    grouped={d: sorted([x for x in schedules if x.day==d], key=lambda x:x.start_time) for d in WEEKDAYS}
    return render_template("timetable.html", grouped=grouped, weekdays=WEEKDAYS, teachers=Teacher.query.order_by(Teacher.name).all(), sections=Section.query.order_by(Section.name).all(), edit_class=edit_class)

@app.route("/timetable/<int:schedule_id>/delete", methods=["POST"])
@teacher_permission_required
def delete_schedule(schedule_id):
    item=db.get_or_404(ClassSchedule,schedule_id); label=item.subject
    db.session.delete(item); db.session.commit(); log_activity(f"DELETED CLASS SCHEDULE: {label}"); flash("Class removed from timetable.", "success")
    return redirect(url_for("timetable"))

# -------------------------
# Registrar reports: enrollment statistics and operational / scheduling sheets
# -------------------------

CHART_COLORS = ("#9333ea", "#f59e0b", "#14b8a6", "#ec4899", "#3b82f6", "#84cc16", "#f97316", "#94a3b8")
AGE_GROUPS = (("Under 18", 0, 17), ("18-19", 18, 19), ("20-21", 20, 21), ("22-24", 22, 24), ("25 and over", 25, 200))
WEEK_HOURS = 55  # Mon-Fri, 07:00-18:00: the hours shown on the weekly timetable


def _age_on(birth_date, today):
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))


def _age_group(birth_date, today):
    if not birth_date:
        return "Not recorded"
    age = _age_on(birth_date, today)
    return next((label for label, low, high in AGE_GROUPS if low <= age <= high), "Not recorded")


def _fte(students):
    full = sum(1 for s in students if s.enrollment_load != "Part-time")
    return round(full + (len(students) - full) * PART_TIME_FTE_WEIGHT, 1)


def _chart_rows(counter, order=None, top=None):
    """Turn {label: count} into rows with percentages and colours for the CSS pie / bar charts."""
    items = [(label, counter[label]) for label in order if counter.get(label)] if order else \
        sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    extras = [k for k in counter if order and k not in order and counter[k]]
    items += [(k, counter[k]) for k in extras]
    if top and len(items) > top:
        items = items[:top] + [("Other", sum(count for _label, count in items[top:]))]
    total = sum(count for _label, count in items) or 1
    biggest = max((count for _label, count in items), default=1) or 1
    rows, start = [], 0.0
    for index, (label, count) in enumerate(items):
        share = count / total * 100
        rows.append({"label": label, "count": count, "pct": round(share, 1), "bar": round(count / biggest * 100, 1),
                     "color": CHART_COLORS[index % len(CHART_COLORS)], "from": start, "to": start + share})
        start += share
    gradient = ", ".join(f"{r['color']} {r['from']:.2f}% {r['to']:.2f}%" for r in rows) or "#e2e8f0 0 100%"
    return {"rows": rows, "total": sum(r["count"] for r in rows), "gradient": gradient}


def _breakdown(students, key_func):
    counter = {}
    for student in students:
        label = key_func(student)
        counter[label] = counter.get(label, 0) + 1
    return counter


@app.route("/registrar/reports")
@roles_required("Registrar", "Admin")
def reports():
    return render_template("reports_index.html")


@app.route("/registrar/reports/enrollment")
@roles_required("Registrar", "Admin")
def report_enrollment():
    today = local_today()
    all_students = Student.query.all()
    enrolled = [s for s in all_students if s.status == "Active"]
    status_counts = _breakdown(all_students, lambda s: s.status)

    def split_table(label_func, order=None):
        groups = {}
        for student in enrolled:
            groups.setdefault(label_func(student), []).append(student)
        labels = [l for l in (order or []) if l in groups] + sorted(l for l in groups if not order or l not in order)
        return [{"label": l, "headcount": len(groups[l]), "full": sum(1 for s in groups[l] if s.enrollment_load != "Part-time"),
                 "part": sum(1 for s in groups[l] if s.enrollment_load == "Part-time"), "fte": _fte(groups[l])} for l in labels]

    by_program = split_table(lambda s: s.course)
    by_year = split_table(lambda s: f"Year {s.year_level}", order=[f"Year {n}" for n in range(1, 5)])
    max_head = max([r["headcount"] for r in by_program] + [1])
    for row in by_program:
        row["bar"] = round(row["headcount"] / max_head * 100, 1)
        row["fte_bar"] = round(row["fte"] / max_head * 100, 1)

    gender_chart = _chart_rows(_breakdown(enrolled, lambda s: s.gender or "Not recorded"), order=list(GENDERS) + ["Not recorded"])
    age_chart = _chart_rows(_breakdown(enrolled, lambda s: _age_group(s.birth_date, today)), order=[g[0] for g in AGE_GROUPS] + ["Not recorded"])
    residency_chart = _chart_rows(_breakdown(enrolled, lambda s: s.residency or "Not recorded"), top=7)
    program_chart = _chart_rows(_breakdown(enrolled, lambda s: s.course), top=7)
    type_chart = _chart_rows(_breakdown(enrolled, lambda s: s.student_type), order=list(STUDENT_TYPES))

    # Year-over-year: students grouped by the school year they were admitted.
    cohorts = {}
    for student in all_students:
        year = student.admission_year or "Not recorded"
        entry = cohorts.setdefault(year, {"year": year, "freshman": 0, "freshman_active": 0, "transfer": 0, "transfer_active": 0})
        kind = "transfer" if student.student_type == "Transfer" else "freshman"
        entry[kind] += 1
        entry[kind + "_active"] += student.status == "Active"
    cohort_rows = sorted(cohorts.values(), key=lambda c: (c["year"] == "Not recorded", c["year"]))
    previous = None
    for row in cohort_rows:
        row["total"] = row["freshman"] + row["transfer"]
        row["active"] = row["freshman_active"] + row["transfer_active"]
        row["transfer_share"] = round(row["transfer"] / row["total"] * 100, 1) if row["total"] else 0.0
        row["freshman_retained"] = round(row["freshman_active"] / row["freshman"] * 100) if row["freshman"] else None
        row["transfer_retained"] = round(row["transfer_active"] / row["transfer"] * 100) if row["transfer"] else None
        known = row["year"] != "Not recorded"
        row["change"] = None
        if known and previous and previous["total"]:
            row["change"] = round((row["total"] - previous["total"]) / previous["total"] * 100, 1)
        if known:
            previous = row
    cohort_max = max([r["total"] for r in cohort_rows] + [1])
    for row in cohort_rows:
        row["bar"] = round(row["total"] / cohort_max * 100, 1)

    return render_template("report_enrollment.html", today=today, headcount=len(enrolled), fte=_fte(enrolled),
                           full=sum(1 for s in enrolled if s.enrollment_load != "Part-time"), status_counts=status_counts,
                           by_program=by_program, by_year=by_year, gender_chart=gender_chart, age_chart=age_chart,
                           residency_chart=residency_chart, program_chart=program_chart, type_chart=type_chart,
                           cohort_rows=cohort_rows, total_records=len(all_students), fte_weight=PART_TIME_FTE_WEIGHT)


def _overlaps(a, b):
    return a.day == b.day and a.start_time < b.end_time and a.end_time > b.start_time


@app.route("/registrar/reports/schedule")
@roles_required("Registrar", "Admin")
def report_schedule():
    day_filter = clean_text(request.args.get("day"))
    room_filter = clean_text(request.args.get("room"))
    schedules = ClassSchedule.query.options(joinedload(ClassSchedule.teacher), joinedload(ClassSchedule.section)).all()
    counts = dict(db.session.query(Student.section_id, func.count(Student.id))
                  .filter(Student.status == "Active", Student.section_id.isnot(None)).group_by(Student.section_id).all())
    rooms = sorted({s.classroom.strip() for s in schedules}, key=str.lower)

    rows = []
    for item in schedules:
        capacity, enrolled = item.section.capacity, counts.get(item.section_id, 0)
        code, _sep, title = item.subject.partition("|")
        rows.append({"day": item.day, "start": item.start_time, "end": item.end_time,
                     "course_id": code.strip() if _sep else "-", "title": (title if _sep else code).strip(),
                     "professor": item.teacher.name, "room": item.classroom.strip(), "section": item.section.name,
                     "capacity": capacity, "enrolled": enrolled, "open": capacity - enrolled,
                     "fill": round(enrolled / capacity * 100) if capacity else 0,
                     "status": "Over capacity" if enrolled > capacity else "Full" if enrolled == capacity else "Open"})
    rows.sort(key=lambda r: (WEEKDAYS.index(r["day"]) if r["day"] in WEEKDAYS else 9, r["start"], r["room"]))

    conflicts = []
    for index, first in enumerate(schedules):
        for second in schedules[index + 1:]:
            if not _overlaps(first, second):
                continue
            if first.teacher_id == second.teacher_id:
                conflicts.append(f"{first.day}: instructor {first.teacher.name} is double-booked ({first.subject} / {second.subject}).")
            if first.classroom.strip().lower() == second.classroom.strip().lower():
                conflicts.append(f"{first.day}: room {first.classroom} is double-booked ({first.subject} / {second.subject}).")
            if first.section_id == second.section_id:
                conflicts.append(f"{first.day}: section {first.section.name} has two classes at once ({first.subject} / {second.subject}).")

    usage = {}
    for item in schedules:
        hours = (int(item.end_time[:2]) * 60 + int(item.end_time[3:]) - int(item.start_time[:2]) * 60 - int(item.start_time[3:])) / 60
        entry = usage.setdefault(item.classroom.strip(), {"room": item.classroom.strip(), "classes": 0, "hours": 0.0})
        entry["classes"] += 1
        entry["hours"] += hours
    room_rows = sorted(usage.values(), key=lambda r: -r["hours"])
    for row in room_rows:
        row["hours"] = round(row["hours"], 1)
        row["pct"] = round(row["hours"] / WEEK_HOURS * 100)

    if day_filter in WEEKDAYS:
        rows = [r for r in rows if r["day"] == day_filter]
    if room_filter:
        rows = [r for r in rows if r["room"].lower() == room_filter.lower()]
    return render_template("report_schedule.html", rows=rows, room_rows=room_rows, conflicts=conflicts, rooms=rooms,
                           weekdays=WEEKDAYS, day_filter=day_filter, room_filter=room_filter, week_hours=WEEK_HOURS,
                           over_count=sum(1 for r in rows if r["status"] == "Over capacity"))


GRADE_BANDS = (("1.00 - 1.50", 1.0, 1.5), ("1.75 - 2.50", 1.75, 2.5), ("2.75 - 3.00", 2.75, 3.0))


@app.route("/registrar/reports/grades")
@roles_required("Registrar", "Admin")
def report_grades():
    semesters = sorted({row[0] for row in db.session.query(Grade.semester).distinct()}, key=semester_sort_key)
    semester = clean_text(request.args.get("semester"))
    query = Grade.query.options(joinedload(Grade.course))
    if semester:
        query = query.filter(Grade.semester == semester)
    courses = {}
    for grade in query.all():
        entry = courses.setdefault(grade.course_id, {"code": grade.course.code, "name": grade.course.name,
                                                    "instructor": grade.course.instructor, "records": 0, "graded": 0,
                                                    "points": 0.0, "bands": [0, 0, 0], "failed": 0, "other": 0})
        entry["records"] += 1
        equivalent = grade.equivalent
        if equivalent is None:           # INC / AW: not graded
            entry["other"] += 1
            continue
        entry["graded"] += 1
        entry["points"] += equivalent
        if equivalent >= FAILING_GRADE_EQUIVALENT:
            entry["failed"] += 1
        else:
            for index, (_label, low, high) in enumerate(GRADE_BANDS):
                if low <= equivalent <= high:
                    entry["bands"][index] += 1
                    break
    rows = []
    for entry in courses.values():
        graded = entry["graded"]
        entry["average"] = round(entry["points"] / graded, 2) if graded else None
        entry["fail_rate"] = round(entry["failed"] / graded * 100, 1) if graded else 0.0
        flags = []
        if graded and entry["fail_rate"] >= HIGH_FAIL_RATE:
            flags.append("High fail rate")
        if graded >= 5 and entry["average"] is not None and entry["average"] <= INFLATION_AVERAGE:
            flags.append("Possible grade inflation")
        entry["flags"] = flags
        rows.append(entry)
    rows.sort(key=lambda r: r["code"].lower())
    graded_total = sum(r["graded"] for r in rows)
    overall = {"records": sum(r["records"] for r in rows), "graded": graded_total,
               "average": round(sum(r["points"] for r in rows) / graded_total, 2) if graded_total else None,
               "failed": sum(r["failed"] for r in rows),
               "fail_rate": round(sum(r["failed"] for r in rows) / graded_total * 100, 1) if graded_total else 0.0}
    return render_template("report_grades.html", rows=rows, overall=overall, semesters=semesters, semester=semester,
                           bands=[b[0] for b in GRADE_BANDS], high_fail=HIGH_FAIL_RATE, inflation=INFLATION_AVERAGE,
                           flagged=sum(1 for r in rows if r["flags"]))


@app.route("/registrar/reports/clearance")
@roles_required("Registrar", "Admin")
def report_clearance():
    year_filter = request.args.get("year", "4")
    program_filter = clean_text(request.args.get("program"))
    search = clean_text(request.args.get("search"))
    query = Student.query.filter(Student.status == "Active")
    if year_filter.isdigit():
        query = query.filter(Student.year_level == int(year_filter))
    if program_filter:
        query = query.filter(Student.course == program_filter)
    if search:
        query = query.filter(or_(Student.student_number.ilike(f"%{search}%"), Student.last_name.ilike(f"%{search}%"),
                                 Student.first_name.ilike(f"%{search}%")))
    students_found = query.order_by(Student.student_number).all()

    programs = CurriculumProgram.query.order_by(CurriculumProgram.position, CurriculumProgram.id).all()
    by_name = {p.name: p for p in programs}
    grade_map = {}
    ids = [s.id for s in students_found]
    if ids:
        for grade in Grade.query.filter(Grade.student_id.in_(ids)).all():
            grade_map.setdefault(grade.student_id, {}).setdefault(grade.course_id, []).append(grade)

    rows = []
    for student in students_found:
        program = by_name.get(student.course)
        record = {"student": student, "program": program, "required": 0, "earned": 0, "missing": []}
        if program is None:
            rows.append(record)
            continue
        for item in program.courses:
            record["required"] += item.units
            history = grade_map.get(student.id, {}).get(item.course_id, []) if item.course_id else []
            if any(grade_is_passed(g.grade, g.mark) for g in history):
                record["earned"] += item.units
                continue
            if not history:
                reason = "Not taken"
            elif any(g.mark in ("INC", "AW") for g in history):
                reason = "Incomplete / withdrawn"
            else:
                reason = "Failed"
            record["missing"].append({"code": item.code, "title": item.title, "units": item.units, "reason": reason,
                                      "year": item.year, "term": item.term})
        record["missing"].sort(key=lambda m: (m["year"], m["term"], m["code"]))
        record["missing_units"] = record["required"] - record["earned"]
        record["pct"] = round(record["earned"] / record["required"] * 100) if record["required"] else 0
        rows.append(record)
    cleared = sum(1 for r in rows if r["program"] and not r["missing"])
    return render_template("report_clearance.html", rows=rows, programs=programs, year_filter=year_filter,
                           program_filter=program_filter, search=search, cleared=cleared,
                           with_gaps=sum(1 for r in rows if r["program"] and r["missing"]),
                           draft_programs=[p.short for p in programs if p.draft_all or any(c.draft for c in p.courses)])


# -------------------------
# Error handling
# -------------------------

def _error_page(code, title, message):
    return render_template("error.html", code=code, title=title, message=message), code


@app.errorhandler(403)
def forbidden(error):
    return _error_page(403, "Access Denied", "You do not have permission to access this page.")


@app.errorhandler(404)
def not_found(error):
    return _error_page(404, "Page Not Found", "The page you requested does not exist.")


@app.errorhandler(405)
def method_not_allowed(error):
    return _error_page(405, "Action Not Allowed", "That action is not available from this page.")


@app.errorhandler(413)
def too_large(error):
    return _error_page(413, "File Too Large", "The total request is larger than the 12 MB limit. Choose smaller attachments and try again.")


@app.errorhandler(OperationalError)
def database_busy(error):
    db.session.rollback()
    app.logger.warning("Database busy/unavailable: %s", error)
    return _error_page(503, "System Busy", "The database is busy with other requests. Your change was not saved. Please try again in a moment.")


@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    return _error_page(500, "Something Went Wrong", "The server hit an unexpected problem. Your data was not changed. Please try again.")


# -------------------------
# Startup
# -------------------------

def upgrade_money_columns():
    """Older databases stored Payment.amount as FLOAT. Make it exact. Safe to run on every start."""
    try:
        if db.engine.dialect.name == "postgresql":
            amount_type = {c["name"]: c["type"] for c in inspect(db.engine).get_columns("payment")}.get("amount")
            if isinstance(amount_type, Float):  # still double precision -> convert once
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE payment ALTER COLUMN amount TYPE NUMERIC(12,2) "
                                      "USING ROUND(amount::numeric, 2)"))
                app.logger.warning("Converted payment.amount from FLOAT to NUMERIC(12,2).")
        else:
            with db.engine.begin() as conn:  # SQLite: only tidy values that carry float noise
                conn.execute(text("UPDATE payment SET amount = ROUND(amount, 2) WHERE amount <> ROUND(amount, 2)"))
    except Exception as exc:  # pragma: no cover - defensive
        app.logger.warning("Could not upgrade payment.amount: %s", exc)


def expire_legacy_account_locks():
    """Accounts locked by older versions never expired. Give them an expiry so they unlock themselves."""
    try:
        User.query.filter(User.login_locked.is_(True), User.locked_until.is_(None)).update(
            {User.locked_until: utcnow() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)}, synchronize_session=False)
        db.session.commit()
    except Exception as exc:  # pragma: no cover - defensive
        db.session.rollback()
        app.logger.warning("Could not expire legacy account locks: %s", exc)


PERFORMANCE_INDEXES = [
    ("ix_payment_student_id", "payment", "student_id"),
    ("ix_payment_payment_date", "payment", "payment_date"),
    ("ix_grade_student_id", "grade", "student_id"),
    ("ix_grade_course_id", "grade", "course_id"),
    ("ix_attendance_attendance_date", "attendance", "attendance_date"),
    ("ix_activity_log_created_at", "activity_log", "created_at"),
    ("ix_student_section_id", "student", "section_id"),
]


def ensure_report_columns():
    """Add the Registrar-report columns on databases that SQLITE_COLUMN_UPGRADES does not cover (PostgreSQL)."""
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    for table, column, ddl in SQLITE_COLUMN_UPGRADES:
        if table not in ("student", "section") or table not in tables:
            continue
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        if column in ("gender", "birth_date", "residency", "student_type", "admission_year", "enrollment_load", "capacity"):
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))


def ensure_performance_indexes():
    """create_all() never adds indexes to tables that already exist, so create them here.
    Each statement is independent: a failure is logged and never stops startup."""
    for name, table, column in PERFORMANCE_INDEXES:
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS {name} ON "{table}" ("{column}")'))
        except Exception as exc:  # pragma: no cover - defensive
            app.logger.warning("Could not create index %s: %s", name, exc)


def init_database():
    with app.app_context():
        db.create_all()
        if database_url.startswith("sqlite"):
            upgrade_sqlite_schema()
        ensure_grade_uniqueness()
        ensure_performance_indexes()
        # create_all() does not add columns to existing databases; upgrade safely on
        # both SQLite and PostgreSQL installations.
        inspector = inspect(db.engine)
        if "user" in inspector.get_table_names() and "activity_visibility" not in {c["name"] for c in inspector.get_columns("user")}:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN activity_visibility TEXT'))
        inspector = inspect(db.engine)
        if "user" in inspector.get_table_names() and "activity_departments" not in {c["name"] for c in inspector.get_columns("user")}:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN activity_departments TEXT'))
        inspector = inspect(db.engine)
        if "user" in inspector.get_table_names() and "access_permissions" not in {c["name"] for c in inspector.get_columns("user")}:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN access_permissions TEXT'))
        inspector = inspect(db.engine)
        if "curriculum_course" in inspector.get_table_names() and "course_id" not in {c["name"] for c in inspector.get_columns("curriculum_course")}:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE curriculum_course ADD COLUMN course_id INTEGER REFERENCES course(id) ON DELETE SET NULL'))
        inspector = inspect(db.engine)
        if "grade" in inspector.get_table_names() and "mark" not in {c["name"] for c in inspector.get_columns("grade")}:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE grade ADD COLUMN mark VARCHAR(5)'))
        inspector = inspect(db.engine)
        if "department_message" in inspector.get_table_names():
            message_columns = {c["name"] for c in inspector.get_columns("department_message")}
            with db.engine.begin() as conn:
                for column in ("archived_by_sender", "archived_by_recipient", "deleted_by_sender", "deleted_by_recipient"):
                    if column not in message_columns:
                        conn.execute(text(f'ALTER TABLE department_message ADD COLUMN {column} BOOLEAN NOT NULL DEFAULT FALSE'))
        inspector = inspect(db.engine)
        if "department_message" in inspector.get_table_names():
            message_columns = {c["name"] for c in inspector.get_columns("department_message")}
            with db.engine.begin() as conn:
                if "recipient_user_id" not in message_columns:
                    conn.execute(text('ALTER TABLE department_message ADD COLUMN recipient_user_id INTEGER REFERENCES "user"(id) ON DELETE CASCADE'))
                if "attachments" not in message_columns:
                    conn.execute(text('ALTER TABLE department_message ADD COLUMN attachments TEXT'))
        inspector = inspect(db.engine)
        if "user" in inspector.get_table_names() and "can_manage_teachers_timetable" not in {c["name"] for c in inspector.get_columns("user")}:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN can_manage_teachers_timetable BOOLEAN NOT NULL DEFAULT FALSE'))
        inspector = inspect(db.engine)
        if "user" in inspector.get_table_names():
            user_columns = {c["name"] for c in inspector.get_columns("user")}
            with db.engine.begin() as conn:
                for column, ddl in [("failed_login_count", "INTEGER NOT NULL DEFAULT 0"), ("login_locked", "BOOLEAN NOT NULL DEFAULT FALSE"), ("security_notifications_enabled", "BOOLEAN NOT NULL DEFAULT TRUE"), ("locked_until", "TIMESTAMP"), ("last_failed_login_at", "TIMESTAMP")]:
                    if column not in user_columns:
                        conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {column} {ddl}'))
        inspector = inspect(db.engine)
        if "activity_log" in inspector.get_table_names():
            activity_columns = {c["name"] for c in inspector.get_columns("activity_log")}
            with db.engine.begin() as conn:
                if "department" not in activity_columns:
                    conn.execute(text('ALTER TABLE activity_log ADD COLUMN department VARCHAR(30)'))
                if "notification_cleared" not in activity_columns:
                    conn.execute(text('ALTER TABLE activity_log ADD COLUMN notification_cleared BOOLEAN NOT NULL DEFAULT 0'))
        ensure_report_columns()
        upgrade_money_columns()
        expire_legacy_account_locks()
        normalize_payment_references()
        seed_database()
        seed_curriculum()
        sync_curriculum_to_courses()
        # With `gunicorn --preload` the app is imported once, then forked. Close the
        # startup connections so each worker opens its own instead of sharing them.
        db.engine.dispose()


init_database()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    # The interactive debugger is only enabled by default when listening on localhost.
    debug = os.environ.get("FLASK_DEBUG", "1" if host in {"127.0.0.1", "localhost"} else "0") == "1"
    app.run(host=host, port=int(os.environ.get("PORT", 5000)), debug=debug)
