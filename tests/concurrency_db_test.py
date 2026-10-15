"""Standalone database concurrency check for the PDC project.

Run from the project root with the project's Python environment:
    python tests/concurrency_db_test.py

The script sets DATABASE_URL to a temporary SQLite file BEFORE importing app.py,
so it never writes to the developer's normal database.
"""
import os
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

TEMP_DIR = tempfile.TemporaryDirectory(prefix="student-management-concurrency-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP_DIR.name, "concurrency_test.db").resolve()).replace("\\", "/")
os.environ["SECRET_KEY"] = "test-only-secret-key-that-is-long-enough-123456"
os.environ["APP_ENV"] = "test"

import app as project  # noqa: E402  (environment must be set before this import)
from sqlalchemy.exc import IntegrityError  # noqa: E402


def main():
    with project.app.app_context():
        student = project.Student(
            student_number="TEST-" + uuid.uuid4().hex[:12],
            first_name="Concurrency", last_name="Test",
            email=f"{uuid.uuid4().hex[:8]}@example.test",
            course="PDC Test", year_level=1,
        )
        course = project.Course(
            code="T" + uuid.uuid4().hex[:8].upper(),
            name="Concurrency Test Course", units=3, instructor="Test Instructor",
        )
        project.db.session.add_all([student, course])
        project.db.session.commit()
        student_id, course_id = student.id, course.id

    barrier = threading.Barrier(2)

    def insert_same_grade(value):
        with project.app.app_context():
            try:
                barrier.wait(timeout=10)
                project.db.session.add(project.Grade(
                    student_id=student_id, course_id=course_id,
                    grade=value, semester="Concurrency Test Semester",
                ))
                project.db.session.commit()
                return "saved"
            except IntegrityError:
                project.db.session.rollback()
                return "rejected_duplicate"
            finally:
                project.db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(insert_same_grade, [85.0, 90.0]))

    assert outcomes.count("saved") == 1, f"Expected exactly one grade save; got {outcomes}"
    assert outcomes.count("rejected_duplicate") == 1, f"Expected one duplicate to be rejected; got {outcomes}"

    # Independent payment inserts should both persist with distinct references.
    refs = ["TEST-" + uuid.uuid4().hex[:20], "TEST-" + uuid.uuid4().hex[:20]]
    pay_barrier = threading.Barrier(2)

    def insert_payment(reference, amount):
        with project.app.app_context():
            try:
                pay_barrier.wait(timeout=10)
                project.db.session.add(project.Payment(
                    student_id=student_id, amount=amount,
                    payment_type="Tuition", reference=reference,
                ))
                project.db.session.commit()
                return "saved"
            finally:
                project.db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as pool:
        payment_outcomes = list(pool.map(insert_payment, refs, [Decimal("1000.00"), Decimal("2000.00")]))

    assert payment_outcomes == ["saved", "saved"], f"Independent payments failed: {payment_outcomes}"
    with project.app.app_context():
        saved_grade_count = project.Grade.query.filter_by(
            student_id=student_id, course_id=course_id,
            semester="Concurrency Test Semester",
        ).count()
        saved_payment_count = project.Payment.query.filter(
            project.Payment.reference.in_(refs)
        ).count()
        assert saved_grade_count == 1, f"Expected 1 grade, found {saved_grade_count}"
        assert saved_payment_count == 2, f"Expected 2 payments, found {saved_payment_count}"

        # Remove the test records from the temporary database.
        project.Payment.query.filter(project.Payment.reference.in_(refs)).delete(synchronize_session=False)
        project.Grade.query.filter_by(student_id=student_id, course_id=course_id,
                                      semester="Concurrency Test Semester").delete(synchronize_session=False)
        project.db.session.delete(project.db.session.get(project.Student, student_id))
        project.db.session.delete(project.db.session.get(project.Course, course_id))
        project.db.session.commit()

    print("PASS: concurrent duplicate grade inserts resulted in exactly one saved grade.")
    print("PASS: two independent concurrent payment inserts both persisted.")
    print("NOTE: This tests database constraints with SQLite; repeat against PostgreSQL before claiming PostgreSQL behavior.")


if __name__ == "__main__":
    try:
        main()
    finally:
        TEMP_DIR.cleanup()
