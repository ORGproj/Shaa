#!/usr/bin/env python3
"""One-command runner for the HTTP concurrency test.

    python tests/run_concurrency_tests.py
    python tests/run_concurrency_tests.py --users 20 --load-levels 1,10,25,50

What it does (so you do not need two terminals):
  1. creates a throw-away SQLite database in your system temp folder
     (your real database is never touched),
  2. starts app.py on a free local port with debug/reloader OFF,
  3. waits until the server answers, then runs tests/http_concurrency_test.py,
  4. stops the server and saves the server's own log to server_log.txt.

Any extra arguments are passed straight to http_concurrency_test.py.
"""
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def server_ready(url):
    try:
        with urllib.request.urlopen(url + "/login", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def tail(path, n=40):
    try:
        return "".join(Path(path).read_text(errors="replace").splitlines(True)[-n:])
    except OSError:
        return "(no log)"


def main():
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    cwd_for_outputs = Path.cwd()
    server_log_copy = cwd_for_outputs / "server_log.txt"

    with tempfile.TemporaryDirectory(prefix="sms_test_", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        db_file = tmp / "test.db"
        log_file = tmp / "server.log"
        env = {
            **os.environ,
            "DATABASE_URL": "sqlite:///" + db_file.as_posix(),
            "PORT": str(port),
            "HOST": "127.0.0.1",
            "FLASK_DEBUG": "0",                    # no reloader: it restarts the server mid-test
            "SECRET_KEY": secrets.token_urlsafe(48),
            "APP_ENV": "development",
            "PYTHONUNBUFFERED": "1",
        }

        print(f"Starting app on {url} with temporary database {db_file}")
        with open(log_file, "w", encoding="utf-8", errors="replace") as log:
            server = subprocess.Popen([sys.executable, "app.py"], cwd=PROJECT, env=env,
                                      stdout=log, stderr=subprocess.STDOUT)
            code = 1
            try:
                deadline = time.time() + 90
                while time.time() < deadline:
                    if server.poll() is not None:
                        print(f"\nThe app exited during startup (exit code {server.returncode}). Server log:\n")
                        print(tail(log_file))
                        return 2
                    if server_ready(url):
                        break
                    time.sleep(0.5)
                else:
                    print("\nThe app did not answer within 90 seconds. Server log:\n")
                    print(tail(log_file))
                    return 2

                print("Server is up. Running tests...\n")
                code = subprocess.call(
                    [sys.executable, str(HERE / "http_concurrency_test.py"), "--base-url", url,
                     "--json-out", str(cwd_for_outputs / "concurrency_results.json"), *sys.argv[1:]],
                    cwd=PROJECT)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()

        text = Path(log_file).read_text(errors="replace") if log_file.exists() else ""
        server_log_copy.write_text(text, encoding="utf-8")
        errors = text.count("Traceback")
        print(f"\nServer log saved to {server_log_copy} ({errors} traceback(s) during the run).")
        if errors:
            print("Last lines of the server log:\n" + tail(server_log_copy, 25))
        return code


if __name__ == "__main__":
    sys.exit(main())
