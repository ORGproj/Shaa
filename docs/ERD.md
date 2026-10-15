# Database design (ERD)

Generated from the SQLAlchemy models in `app.py`. The diagram renders automatically on GitHub.

```mermaid
erDiagram
    SECTION ||--o{ STUDENT : "enrolls (optional)"
    SECTION ||--o{ CLASS_SCHEDULE : "scheduled for"
    TEACHER ||--o{ CLASS_SCHEDULE : "teaches"
    STUDENT ||--o{ PAYMENT : "pays"
    STUDENT ||--o{ GRADE : "receives"
    STUDENT ||--o{ ASSESSMENT_SCORE : "earns"
    STUDENT ||--o{ ATTENDANCE : "has"
    COURSE ||--o{ GRADE : "graded in"
    COURSE ||--o{ ASSESSMENT_SCORE : "scored in"
    COURSE ||--o{ ATTENDANCE : "attended in"
    USER ||--o{ DEPARTMENT_MESSAGE : "sends"
    USER ||--o{ DEPARTMENT_MESSAGE : "receives privately"

    USER {
        int id PK
        string username UK
        string password_hash
        string role "Registrar, Accounting, Academic or Admin"
        int failed_login_count
        boolean login_locked
        datetime locked_until "temporary lock expiry"
        datetime last_failed_login_at
        text activity_departments "audit access granted by admin"
        text access_permissions "JSON: allowed actions per module"
    }
    SECTION {
        int id PK
        string name UK
        int year_level
    }
    STUDENT {
        int id PK
        string student_number UK
        string first_name
        string last_name
        string email
        string course
        int year_level
        string status
        int section_id FK
    }
    COURSE {
        int id PK
        string code UK
        string name
        int units
        string instructor
    }
    PAYMENT {
        int id PK
        int student_id FK
        decimal amount "NUMERIC(12,2) exact money"
        string payment_type
        datetime payment_date
        string reference UK
    }
    FINANCIAL_REPORT {
        int id PK
        string kind "balance_sheet, income_statement, ... billing_statement"
        string period "a year, or a student number for billing statements"
        text data "editable lines as JSON; totals are recalculated, never stored"
        string updated_by
        datetime updated_at
    }
    GRADE {
        int id PK
        int student_id FK
        int course_id FK
        float grade
        string semester
    }
    ASSESSMENT_SCORE {
        int id PK
        int student_id FK
        int course_id FK
        string semester
        string component
        string title
        float score
        float max_score
    }
    ATTENDANCE {
        int id PK
        int student_id FK
        int course_id FK
        date attendance_date
        string status
        string recorded_by
    }
    TEACHER {
        int id PK
        string name
        string email UK
        string subjects
    }
    CLASS_SCHEDULE {
        int id PK
        string day
        string start_time
        string end_time
        int teacher_id FK
        int section_id FK
    }
    DEPARTMENT_MESSAGE {
        int id PK
        int sender_id FK
        int recipient_user_id FK "set for private messages"
        string recipient_role
        string subject
        text attachments "JSON list of private file metadata"
        boolean is_read
        boolean archived_by_sender
        boolean deleted_by_recipient
    }
    ACTIVITY_LOG {
        int id PK
        string username
        string department
        string action
        datetime created_at
    }
    FORM_TOKEN {
        string token PK
        datetime created_at
    }
    ANNOUNCEMENT {
        int id PK
        string title
        text body
        string author
        datetime created_at
        boolean is_published
    }
```

`ACTIVITY_LOG`, `FORM_TOKEN` and `ANNOUNCEMENT` have no foreign keys on purpose (the announcement author is stored as text). The log stores the username as text so audit history survives if an account is removed; the token table exists only so the database can reject a second submission of the same form.

## Integrity rules that matter for concurrency

| Table | Rule | Why it matters |
|---|---|---|
| `student` | `student_number` unique | Two registrars cannot end up with the same number; the loser retries with a fresh one |
| `payment` | `reference` unique | Payment references are never duplicated |
| `financial_report` | unique (`kind`, `period`) | One saved copy of each report per year (or per student for billing statements); saves compare `updated_at` so a stale edit is refused instead of overwriting |
| `grade` | unique (`student_id`, `course_id`, `semester`) | Only one grade per student, course and semester, even if two users submit at the same instant |
| `attendance` | unique (`student_id`, `course_id`, `attendance_date`) | One attendance record per student, course and day |
| `form_token` | `token` is the primary key | A form can be accepted only once (double-click protection) |
| `schedule_lock` | one row, locked by every timetable save | Timetable saves run one at a time, so the clash check and the insert cannot interleave (overlapping times cannot be a plain UNIQUE constraint) |
| `class_schedule` | `ON DELETE RESTRICT` to teacher and section | A teacher or section with scheduled classes cannot be deleted by accident |
| `attendance`, `department_message` | `ON DELETE CASCADE` | Dependent rows are removed with their parent. SQLite does not enforce this by default, so deleting a staff account also removes its messages and attachment files in code |
| `student` | ORM cascade `delete-orphan` to payments, grades, scores, attendance | Deleting a student removes their records in one transaction |

## Indexes

Besides primary and unique keys, startup creates indexes on `payment(student_id)`, `payment(payment_date)`, `grade(student_id)`, `grade(course_id)`, `attendance(attendance_date)`, `activity_log(created_at)` and `student(section_id)`. `department_message` and `activity_log.department` are indexed by the models.

## Data types

- Money is `NUMERIC(12,2)` and handled as Python `Decimal`, never floating point. Older databases are converted automatically at startup (PostgreSQL: `ALTER COLUMN ... TYPE NUMERIC(12,2)`; SQLite: values are rounded to two places).
- Grades and assessment scores are floats because they are percentages and scores, not currency.
- Timestamps are stored in UTC and shown in `APP_TIMEZONE` (default `Asia/Manila`).
