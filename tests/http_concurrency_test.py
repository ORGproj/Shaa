#!/usr/bin/env python3
"""HTTP-level concurrency + load test for the Student Management System (PDC project).

Unlike tests/concurrency_db_test.py (which inserts rows directly), this drives the
REAL running app through its login/CSRF/forms, with one independent session per
simulated user -- exactly what happens when several computers use the system.

Standard library only. Usage:

    # 1. start the app (python app.py  OR  gunicorn -w 4 --threads 4 app:app)
    # 2. in another terminal:
    python http_concurrency_test.py --base-url http://127.0.0.1:5000

Defaults to the demo accounts from the README. Override with:
    --registrar user:pass --accounting user:pass --academic user:pass

It creates tagged test students (last name ZZLOADTEST) and deletes them at the end.
Run it against a COPY of the database / a test deployment, not real data.
Refuses non-local URLs unless you pass --allow-remote.
"""
import argparse
import concurrent.futures as cf
import html
import http.cookiejar
import json
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

TAG = "ZZLOADTEST"
CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]+)"')
FLASH_RE = re.compile(r'class="flash[^"]*"[^>]*>(.*?)</', re.S)


class Client:
    """One simulated user/computer: its own cookie jar = its own session."""

    def __init__(self, base, creds):
        self.base = base.rstrip("/")
        self.creds = creds
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None

    def _open(self, req, timeout=60):
        t0 = time.perf_counter()
        try:
            with self.opener.open(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
                return r.status, body, time.perf_counter() - t0
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), time.perf_counter() - t0
        except Exception as e:  # timeouts, resets
            return 0, f"CLIENT-ERROR {type(e).__name__}: {e}", time.perf_counter() - t0

    def get(self, path):
        status, body, dt = self._open(urllib.request.Request(self.base + path))
        m = CSRF_RE.search(body)
        if m:
            self.csrf = m.group(1)
        return status, body, dt

    def post(self, path, fields):
        if not self.csrf:
            self.get("/dashboard")
        data = urllib.parse.urlencode({**fields, "csrf_token": self.csrf}, doseq=True).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST")
        status, body, dt = self._open(req)
        m = CSRF_RE.search(body)
        if m:
            self.csrf = m.group(1)
        return status, body, dt

    def login(self):
        self.get("/login")
        user, pw = self.creds
        status, body, _ = self.post("/login", {"username": user, "password": pw})
        ok = status == 200 and "/logout" in body
        if not ok:
            hint = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))[:300]
            raise RuntimeError(
                f"Login failed for {user} (status {status}). Server/response said: {hint!r}\n"
                "status 0 = no HTTP response at all (see CLIENT-ERROR text above); 200 = wrong password, "
                "locked account or CSRF problem; 500 = check the app's terminal for the traceback.")
        self.get("/dashboard")
        return self


def flashes(body):
    return " | ".join(re.sub(r"<[^>]+>|\s+", " ", m).strip() for m in FLASH_RE.findall(body))[:300]


def options(body, select_id):
    m = re.search(rf'<select[^>]*id="{select_id}"[^>]*>(.*?)</select>', body, re.S)
    return re.findall(r'<option[^>]*value="(\d+)"', m.group(1)) if m else []


def program_names(body):
    """Degree programs offered by the add-student form (the server only accepts these)."""
    m = re.search(r'<select[^>]*id="course"[^>]*>(.*?)</select>', body, re.S)
    names = re.findall(r'<option[^>]*value="([^"]+)"', m.group(1)) if m else []
    return [html.unescape(n) for n in names]


def run_parallel(fn, n):
    """Run fn(i) in n threads released at the same instant (barrier)."""
    barrier = threading.Barrier(n)

    def wrapped(i):
        barrier.wait(timeout=60)
        return fn(i)

    with cf.ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(wrapped, range(n)))


RESULTS = []


def record(name, passed, detail):
    RESULTS.append({"test": name, "passed": passed, "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}\n        {detail}")


def finding(name, detail):
    RESULTS.append({"test": name, "passed": None, "detail": detail})
    print(f"[INFO] {name}\n        {detail}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:5000")
    ap.add_argument("--registrar", default="registrar:registrar123")
    ap.add_argument("--accounting", default="accounting:accounting123")
    ap.add_argument("--academic", default="academic:academic123")
    ap.add_argument("--admin", default="admin:admin123", help="used only by T9 (creates and removes test instructors/sections)")
    ap.add_argument("--users", type=int, default=10, help="concurrent users for race tests")
    ap.add_argument("--load-levels", default="1,5,10,25,50")
    ap.add_argument("--allow-remote", action="store_true")
    ap.add_argument("--json-out", default="concurrency_results.json")
    a = ap.parse_args()

    host = urllib.parse.urlparse(a.base_url).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1") and not a.allow_remote:
        sys.exit("Refusing to test a non-local URL without --allow-remote (this test writes data).")

    split = lambda s: tuple(s.split(":", 1))
    reg_c, acc_c, aca_c, adm_c = split(a.registrar), split(a.accounting), split(a.academic), split(a.admin)
    N = a.users
    created_ids = []

    print(f"== Target {a.base_url}, {N} concurrent users per race test ==\n")

    # ---- preflight: one plain request, so connection problems are reported clearly
    st, body, dt = Client(a.base_url, reg_c).get("/login")
    print(f"Preflight GET /login -> status {st} in {dt*1000:.0f} ms" + ("" if st == 200 else f"  ({body[:200]!r})"))
    if st != 200:
        sys.exit("Server did not answer /login normally; fix that first (is app.py running at this URL?).")

    # ---- T0: three roles log in at the same time, each in its own session
    clients = run_parallel(lambda i: Client(a.base_url, [reg_c, acc_c, aca_c][i]).login(), 3)
    reg, acc, aca = clients
    record("T0 three department roles log in simultaneously", True, "Registrar, Accounting, Academic sessions established")

    # the server only accepts degree programs that exist on the Curriculum page,
    # so look one up from the real form instead of inventing a course name
    _, form_body, _ = reg.get("/students/add")
    programs = program_names(form_body)
    if not programs:
        sys.exit("No degree programs exist. Add one under Curriculum first (a fresh database seeds them on startup).")
    PROGRAM = programs[0]
    print(f"Using degree program: {PROGRAM}\n")

    # ---- T1: concurrent student registration (generate_student_number = max+1 race)
    def add_student(i):
        c = Client(a.base_url, reg_c).login()
        st, body, dt = c.post("/students/add", {
            "first_name": f"User{i}", "last_name": TAG, "email": f"u{i}@example.test",
            "course": PROGRAM, "year_level": "1", "status": "Active"})
        m = re.search(r"Student (\d{4}-\d+) added successfully", body)
        return {"status": st, "number": m.group(1) if m else None, "msg": flashes(body), "dt": dt}

    r1 = run_parallel(add_student, N)
    numbers = [r["number"] for r in r1 if r["number"]]
    fails = [r for r in r1 if not r["number"]]
    dup = len(numbers) - len(set(numbers))
    record(f"T1 {N} simultaneous student registrations -> unique student numbers, none lost",
           not fails and dup == 0,
           f"saved={len(numbers)}/{N}, duplicate numbers={dup}, failed={len(fails)}"
           + (f", sample failure: status {fails[0]['status']} '{fails[0]['msg']}'" if fails else ""))

    # collect ids of test students for later steps + cleanup
    _, body, _ = reg.get(f"/students?search={TAG}")
    created_ids = sorted({int(x) for x in re.findall(r"/students/(\d+)\"", body)})
    if not created_ids:
        print("Could not find test students; aborting remaining tests.")
        return finish(a)
    student_id = created_ids[0]

    # find a valid course + the test student's id as shown to Academic
    _, gbody, _ = aca.get("/grades")
    course_ids = options(gbody, "course_id")
    if not course_ids:
        print("No courses exist; create one as Academic first.")
        return cleanup(reg, created_ids) or finish(a)
    course_id = course_ids[0]
    # the grade form now takes a term + school year (read_semester_form), stored as "<term> <year>"
    term, school_year = "Summer", f"{2090 + int(time.time()) % 9}-{2091 + int(time.time()) % 9}"
    sem = f"{term} {school_year}"
    sem_fields = {"semester_term": term, "school_year": school_year}

    # ---- T2: same grade submitted by N users at once (check-then-insert race)
    def post_grade(i):
        c = Client(a.base_url, aca_c).login()
        st, body, dt = c.post("/grades", {"student_id": student_id, "course_id": course_id,
                                           "grade": 70 + i, **sem_fields})
        return {"status": st, "ok": "Grade recorded successfully" in body,
                "dup": "already exists" in body, "msg": flashes(body)}

    r2 = run_parallel(post_grade, N)
    saved = sum(r["ok"] for r in r2)
    errors500 = sum(1 for r in r2 if r["status"] >= 500 or r["status"] == 0)
    _, gl, _ = aca.get(f"/grades?search={urllib.parse.quote(sem)}")
    rows = len(re.findall(r'class="grade-pill"', gl))
    record(f"T2 {N} users submit the SAME grade at once -> exactly one row stored",
           rows == 1 and errors500 == 0,
           f"rows in DB={rows}, responses saved={saved}, duplicate-rejected={sum(r['dup'] for r in r2)}, "
           f"server errors={errors500}")

    # ---- T3: lost-update check on grade edit (no row versioning in the app)
    grade_id = None
    mm = re.search(r"grades\?edit=(\d+)", gl)
    if mm:
        grade_id = mm.group(1)

        # both users open the edit form first (so both "see" the same current grade) ...
        editors = []
        for _ in range(2):
            c = Client(a.base_url, aca_c).login()
            _, eb, _ = c.get(f"/grades?edit={grade_id}")
            me = re.search(r'name="expected_grade"\s+value="([^"]*)"', eb)
            editors.append((c, me.group(1) if me else ""))

        def edit(i):
            c, expected = editors[i]
            st, body, _ = c.post("/grades", {"grade_id": grade_id, "expected_grade": expected,
                                             "student_id": student_id, "course_id": course_id,
                                             "grade": 10 + i * 10, **sem_fields})
            return {"ok": "edited successfully" in body, "conflict": "Edit conflict" in body, "status": st}

        # ... then both submit at the same instant
        r3 = run_parallel(edit, 2)
        record("T3 two users edit the same grade at once -> one wins, the other gets an edit-conflict message",
               sum(r["ok"] for r in r3) == 1 and sum(r["conflict"] for r in r3) == 1,
               f"saved={sum(r['ok'] for r in r3)}, conflict-rejected={sum(r['conflict'] for r in r3)}, "
               f"statuses={[r['status'] for r in r3]} (2 saved would mean a silent lost update)")

    # ---- T4: concurrent payments from N cashiers: all succeed, unique references
    student_no = None
    _, pbody, _ = acc.get("/payments")
    m = re.search(r'<option value="([0-9]{4}-\d+)"[^>]*>[^<]*User0', pbody) or re.search(r'<option value="([0-9]{4}-\d+)"', pbody)
    # find a test student's number via the Registrar view
    _, sb, _ = reg.get(f"/students/{student_id}")
    mn = re.search(r"(\d{4}-\d{4,})", sb)
    student_no = mn.group(1) if mn else (m.group(1) if m else None)

    def form_token(c):
        _, pb, _ = c.get("/payments")
        mt = re.search(r'name="submit_token"\s+value="([^"]+)"', pb)
        return mt.group(1) if mt else ""

    def pay(i):
        c = Client(a.base_url, acc_c).login()
        st, body, dt = c.post("/payments", {"student_lookup": student_no, "amount": "100.00",
                                             "payment_type": "Tuition", "submit_token": form_token(c)})
        mref = re.search(r"Payment (\d{11}) recorded successfully", body)
        return {"status": st, "ref": mref.group(1) if mref else None, "dt": dt, "msg": flashes(body)}

    r4 = run_parallel(pay, N)
    refs = [r["ref"] for r in r4 if r["ref"]]
    _, plist, _ = acc.get(f"/payments?search={student_no}&all_dates=1")
    persisted = sum(1 for ref in refs if ref in plist)
    record(f"T4 {N} simultaneous payments -> all saved, references unique",
           len(refs) == N and len(set(refs)) == N and persisted == N,
           f"saved={len(refs)}/{N}, unique refs={len(set(refs))}, found in history={persisted}")

    # ---- T4b: one payment form submitted several times at once (double-click / retry)
    dclient = Client(a.base_url, acc_c).login()
    shared_token = form_token(dclient)

    def double_pay(i):
        c = Client(a.base_url, acc_c).login()
        st, body, _ = c.post("/payments", {"student_lookup": student_no, "amount": "777.00",
                                            "payment_type": "Tuition", "submit_token": shared_token})
        return "recorded successfully" in body

    r4b = run_parallel(double_pay, 5)
    record("T4b same payment form submitted 5 times at once -> recorded exactly once",
           sum(r4b) == 1, f"payments recorded={sum(r4b)} of 5 identical submissions")

    # ---- T5: same attendance record submitted by N users at once
    today = date.today().isoformat()

    def attend(i):
        c = Client(a.base_url, aca_c).login()
        st, body, _ = c.post("/attendance", {"student_id": student_id, "course_id": course_id,
                                              "attendance_date": today,
                                              "status": ["Present", "Absent", "Late", "Excused"][i % 4], "note": ""})
        return {"status": st, "msg": flashes(body)}

    r5 = run_parallel(attend, N)
    bad = [r for r in r5 if r["status"] >= 500 or r["status"] == 0 or "Something Went Wrong" in r["msg"]]
    _, ab, _ = aca.get(f"/attendance?date={today}")
    # count register rows only (the number also appears once in the student <select>)
    rows = len(re.findall(r"<tr><td>" + re.escape(student_no or "?") + r"\s*<span", ab))
    record(f"T5 {N} users record the same attendance entry at once -> one row, no server errors",
           rows == 1 and not bad,
           f"rows in DB={rows}, server errors={len(bad)}"
           + (f" (status {bad[0]['status']}: the unique constraint fired but the route has no IntegrityError handler)" if bad else ""))

    # ---- T6: validation / error handling
    st, b, _ = acc.post("/payments", {"student_lookup": student_no, "amount": "-5", "payment_type": "Tuition"})
    v1 = "valid payment amount" in b
    st, b, _ = aca.post("/grades", {"student_id": student_id, "course_id": course_id, "grade": "101", **sem_fields})
    v2 = "out of range" in b.lower() or "check the selected" in b.lower() or "grade (0-100)" in b
    st, b, _ = reg.post("/students/add", {"first_name": "A", "last_name": TAG, "email": "not-an-email",
                                           "course": PROGRAM, "year_level": "1"})
    v3 = "valid email" in b
    record("T6 validation: negative amount, grade 101, bad email are rejected with messages",
           v1 and v2 and v3, f"negative amount rejected={v1}, grade>100 rejected={v2}, bad email rejected={v3}")

    # ---- T7: role-based access control (denied requests answer HTTP 403, "does not have <action> access")
    st1, b, _ = acc.get("/grades")
    rbac1 = st1 == 403 and "does not have" in b
    st2, b, _ = aca.post("/payments", {"student_lookup": student_no, "amount": "1", "payment_type": "Tuition"})
    rbac2 = st2 == 403 and "does not have" in b
    record("T7 role separation: Accounting cannot open grades, Academic cannot post payments",
           rbac1 and rbac2, f"accounting->grades HTTP {st1} blocked={rbac1}, academic->payments HTTP {st2} blocked={rbac2}")

    # ---- T7b: Registrar may read grade history but not change it (read-only default)
    st1, _, _ = reg.get("/grades")
    st2, b, _ = reg.post("/grades", {"student_id": student_id, "course_id": course_id, "grade": "55",
                                      "semester_term": "Summer", "school_year": "2099-2100"})
    record("T7b role separation: Registrar can view grades (200) but cannot record one (403)",
           st1 == 200 and st2 == 403 and "does not have" in b, f"GET /grades -> {st1}, POST /grades -> {st2}")

    # ---- T9: timetable double-booking race (check-then-insert guarded by the timetable lock)
    def timetable_race(label, make_fields):
        adm = Client(a.base_url, adm_c).login()
        tag = f"{TAG}-{label}"
        for i in range(N):
            adm.post("/teachers", {"name": f"{tag} Teacher {i}", "email": f"{tag.lower()}{i}@example.test".replace("_", ""),
                                   "subjects": "Test", "employment_type": "Full-time",
                                   "working_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                                   "available_start": "07:00", "available_end": "17:00"})
            adm.post("/sections", {"name": f"{tag}-Sec{i}", "year_level": "1", "capacity": "40"})
        _, tb, _ = adm.get("/timetable")
        teacher_ids = re.findall(r'<option value="(\d+)"[^>]*>' + re.escape(tag) + r" Teacher \d+", tb)
        section_ids = re.findall(r'<option value="(\d+)"[^>]*>' + re.escape(tag) + r"-Sec\d+\s*<", tb)
        if len(teacher_ids) < N or len(section_ids) < N:
            return None, f"could not create {N} test instructors/sections (got {len(teacher_ids)}/{len(section_ids)})"

        def book(i):
            c = Client(a.base_url, adm_c).login()
            st, body, _ = c.post("/timetable", make_fields(i, teacher_ids, section_ids))
            return {"status": st, "saved": "Class schedule saved" in body, "conflict": "conflict" in body.lower()}

        res = run_parallel(book, N)
        _, tb, _ = adm.get("/timetable")
        rows = tb.count(f"{tag} Subject")
        return (res, rows, adm, tag, teacher_ids, section_ids), None

    def timetable_cleanup(adm, tag, teacher_ids, section_ids):
        _, tb, _ = adm.get("/timetable")
        for m in re.finditer(r'action="/timetable/(\d+)/delete"', tb):
            row_start = tb.rfind("weekly-class", 0, m.start())
            if tag in tb[row_start:m.start()]:
                adm.post(f"/timetable/{m.group(1)}/delete", {})
        for tid in teacher_ids:
            adm.post(f"/teachers/{tid}/delete", {})
        for sid in section_ids:
            adm.post(f"/sections/{sid}/delete", {})

    try:
        for label, maker, what in (
            ("ROOM", lambda i, t, s_: {"day": "Friday", "start_time": "16:00", "end_time": "17:00",
                                       "subject": f"{TAG}-ROOM Subject", "teacher_id": t[i], "section_id": s_[i],
                                       "classroom": f"{TAG}-ROOM-1"}, "same room"),
            ("TEACHER", lambda i, t, s_: {"day": "Thursday", "start_time": "16:00", "end_time": "17:00",
                                          "subject": f"{TAG}-TEACHER Subject", "teacher_id": t[0], "section_id": s_[i],
                                          "classroom": f"{TAG}-TEACHER-Room-{i}"}, "same instructor"),
        ):
            out, err = timetable_race(label, maker)
            if err:
                finding(f"T9 timetable race ({what}) skipped", err)
                continue
            res, rows, adm, tag, tids, sids = out
            saved = sum(r["saved"] for r in res)
            errs = sum(1 for r in res if r["status"] >= 500 or r["status"] == 0)
            record(f"T9 {N} users book the SAME {what} and time at once -> exactly one class stored",
                   saved == 1 and rows == 1 and errs == 0,
                   f"saved={saved}, rows in timetable={rows}, conflict-rejected={sum(r['conflict'] for r in res)}, server errors={errs}")
            timetable_cleanup(adm, tag, tids, sids)
    except RuntimeError as exc:  # admin login failed: do not abort the other results
        finding("T9 timetable race skipped", str(exc))

    # ---- T8: throughput / latency vs concurrent users (read-heavy mix)
    levels = [int(x) for x in a.load_levels.split(",")]
    table = []
    for n in levels:
        def user(i, n=n):
            c = Client(a.base_url, [reg_c, acc_c, aca_c][i % 3]).login()
            lat = []
            errs = 0
            paths = {0: ["/students", "/dashboard"], 1: ["/payments", "/dashboard"], 2: ["/grades", "/attendance"]}[i % 3]
            for _ in range(5):
                for p in paths:
                    st, _, dt = c.get(p)
                    lat.append(dt)
                    errs += st != 200
            return lat, errs

        t0 = time.perf_counter()
        out = run_parallel(user, n)
        wall = time.perf_counter() - t0
        lat = sorted(x for l, _ in out for x in l)
        errs = sum(e for _, e in out)
        table.append({"users": n, "requests": len(lat), "req_per_s": round(len(lat) / wall, 1),
                      "p50_ms": round(statistics.median(lat) * 1000), "p95_ms": round(lat[int(len(lat) * .95) - 1] * 1000),
                      "errors": errs})
    print("\nT8 read latency under load (each user: login + 5 rounds of 2 pages)")
    print(f"   {'users':>5} {'reqs':>5} {'req/s':>7} {'p50 ms':>7} {'p95 ms':>7} {'errors':>6}")
    for r in table:
        print(f"   {r['users']:>5} {r['requests']:>5} {r['req_per_s']:>7} {r['p50_ms']:>7} {r['p95_ms']:>7} {r['errors']:>6}")
    RESULTS.append({"test": "T8 load table", "passed": all(r["errors"] == 0 for r in table), "detail": table})

    cleanup(reg, created_ids)
    finish(a)


def cleanup(reg, ids):
    ok = 0
    for sid in ids:
        st, _, _ = reg.post(f"/students/{sid}/delete", {})
        ok += st == 200
    print(f"\nCleanup: deleted {ok}/{len(ids)} test students (their grades/payments/attendance cascade).")


def finish(a):
    with open(a.json_out, "w") as f:
        json.dump(RESULTS, f, indent=2)
    p = sum(1 for r in RESULTS if r["passed"] is True)
    f_ = sum(1 for r in RESULTS if r["passed"] is False)
    print(f"\nSUMMARY: {p} passed, {f_} failed. Details saved to {a.json_out}")
    sys.exit(1 if f_ else 0)


if __name__ == "__main__":
    main()
