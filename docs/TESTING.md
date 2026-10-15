# Testing and concurrency evidence

## How to run

From the project root, with the dependencies installed:

```bash
python tests/run_concurrency_tests.py --users 20 --load-levels 1,5,10,25,50
```

The runner starts the app on a free local port using a **temporary** database (your real data is never touched), runs the HTTP test, stops the server and saves two files in the current folder: `concurrency_results.json` and `server_log.txt` (the server's own log of what happened while clients were sending requests).

Other tests:

| File | Purpose |
|---|---|
| `tests/http_concurrency_test.py` | Drives the running app over HTTP with one independent login session per simulated user (what separate computers do). Run directly with `--base-url` against a test deployment. It refuses non-local URLs unless `--allow-remote` is given, because it creates and deletes test records. |
| `tests/run_concurrency_tests.py` | One-command launcher for the test above. |
| `tests/concurrency_db_test.py` | Database-level check of the unique-constraint rules on a temporary SQLite database. |
| `/concurrency` page in the app | Visual demo of a race condition on an in-memory counter, with and without a lock. It illustrates the idea; it does not prove the database is safe. |

## What the HTTP tests check

| Test | Scenario | Expected |
|---|---|---|
| T0 | Registrar, Accounting and Academic log in at the same time | Three independent sessions |
| T1 | N users register students at once | N saved, no duplicate student numbers |
| T2 | N users submit the same grade at once | Exactly one row stored, no server errors |
| T3 | Two users edit the same grade at once | One saved, the other gets an edit-conflict message |
| T4 | N cashiers record payments at once | All saved, all references unique |
| T4b | The same payment form submitted 5 times at once | Recorded exactly once |
| T5 | N users record the same attendance entry at once | One row, no server errors |
| T6 | Negative amount, grade 101, invalid email | Rejected with a message, nothing saved |
| T7 | Accounting opens grades; Academic posts a payment | Both blocked (HTTP 403) |
| T7b | Registrar opens grades; Registrar posts a grade | Read allowed (200), write blocked (403) |
| T8 | Login plus repeated page loads at 1, 5, 10, 25, 50 users | Latency and throughput table |
| T9 | N users book the same room (then the same instructor) at the same time slot | Exactly one class stored, the rest get a conflict message. Needs the `admin` demo login (`--admin user:pass`) |

## Recorded results

Recorded by the team on 13 October 2026 on a Windows laptop (Python 3.14, Flask development server, temporary SQLite database, test client on the same machine), 20 concurrent users per race test. This was an earlier build of this project (it already included the concurrency safeguards, announcements and module permissions, but not the later exact-money, temporary-lockout and permission-detection fixes), so re-run the command above on the final code and replace these numbers before presenting. (T7b and T9 were added afterwards and have no recorded result yet.)

| Test | Result |
|---|---|
| T0 | Pass |
| T1 | Pass: 20 of 20 saved, 0 duplicate numbers |
| T2 | Pass: 1 row stored, 19 duplicates rejected, 0 server errors |
| T3 | Pass: 1 saved, 1 conflict message |
| T4 | Pass: 20 of 20 saved, 20 unique references |
| T4b | Pass: 1 payment recorded out of 5 identical submissions |
| T5 | Pass: 1 row, 0 server errors |
| T6 | Pass |
| T7 | Pass |

The server log recorded 0 tracebacks during the run.

**T8: read latency under load** (each user: login, then 5 rounds of 2 pages; zero errors at every level)

| Users | Requests | Requests/s | Median (ms) | 95th percentile (ms) |
|---:|---:|---:|---:|---:|
| 1 | 10 | 23.0 | 16 | 29 |
| 5 | 50 | 76.7 | 23 | 38 |
| 10 | 100 | 82.6 | 40 | 78 |
| 25 | 250 | 76.7 | 136 | 212 |
| 50 | 500 | 78.2 | 296 | 508 |

Earlier runs on previous builds gave the same shape (about 70 to 85 requests per second from 10 users upward), so expect about 10 percent run-to-run variation.

**Reading the table:** throughput levels off at roughly 75 to 85 requests per second from about 10 users, and response time then grows about in proportion to the number of users waiting. That is a saturated server: extra users queue rather than being served faster. The 1-user median includes the login request.

## Limitations of these results

- One machine: the test client and the server share the same CPU, which understates what the server could do on its own.
- One server process on SQLite. Not yet run against PostgreSQL or several Gunicorn workers (`gunicorn` does not run on Windows; use Linux, WSL or the Render deployment for that comparison).
- T8 measures reads. Write throughput under load has not been benchmarked separately.
- The results prove the tested race conditions are handled, not that no other race exists.
