"""Real HTTP/SMTP account smoke test in an automatically removed database.

No vendor requests. --hold leaves the test API running for simulator QA.
Credentials below belong only to disposable accounts in a loopback-only server.
"""
import argparse
import json
import os
import re
import signal
import socket
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from aiosmtpd.controller import Controller
from psycopg import sql
from sqlalchemy.engine import make_url

from syncinerary.config import settings

PASSWORD = "Syncinerary test password 2026"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Inbox:
    def __init__(self):
        self.codes = {}

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        if not address.endswith("@example.com"):
            return "550 Test inbox accepts example.com only"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        code = re.search(rb"code is: (\d{8})", envelope.content)
        assert code
        for recipient in envelope.rcpt_tos:
            self.codes[recipient] = code[1].decode()
        return "250 OK"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold", action="store_true")
    options = parser.parse_args()
    db_name = "auth_e2e_" + uuid4().hex[:12]
    db = make_url(settings.database_url)
    admin = psycopg.connect(host=db.host, port=db.port, user=db.username,
                            password=db.password, dbname="postgres", autocommit=True)
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
    env = dict(os.environ, DATABASE_URL=db.set(database=db_name).render_as_string(hide_password=False))
    inbox = Inbox()
    smtp_port, api_port = free_port(), free_port()
    env.update(SMTP_HOST="127.0.0.1", SMTP_PORT=str(smtp_port), SMTP_SECURITY="plain",
               SMTP_FROM="Syncinerary QA <noreply@example.com>", SMTP_USERNAME="", SMTP_PASSWORD="")
    mail = Controller(inbox, hostname="127.0.0.1", port=smtp_port)
    api = None
    evidence = Path("evidence/sign-in-e2e")
    evidence.mkdir(parents=True, exist_ok=True)
    checks = []

    def check(name):
        checks.append(name)
        print("PASS", name, flush=True)
        (evidence / "http-auth-journey.json").write_text(json.dumps({"checks": checks, "email_transport": "local SMTP", "database": "disposable Postgres", "vendor_calls": False}, indent=2))

    try:
        for revision in ["head", "base", "head"]:
            direction = "downgrade" if revision == "base" else "upgrade"
            subprocess.run([".venv/bin/alembic", direction, revision], env=env, check=True, capture_output=True)
        check("Full migration upgrade/downgrade/upgrade in a disposable database")
        mail.start()
        with open("/tmp/syncinerary-qa-api.log", "w") as log:
            api = subprocess.Popen([".venv/bin/uvicorn", "syncinerary.api.main:app", "--host", "127.0.0.1", "--port", str(api_port)], env=env, stdout=log, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{api_port}"
        with httpx.Client(base_url=base, timeout=30) as client:
            for _ in range(60):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                assert api.poll() is None, "API exited; see /tmp/syncinerary-qa-api.log"
                time.sleep(1)
            else:
                raise RuntimeError("API startup timed out")

            def call(method, path, expected=200, token=None, **kwargs):
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                response = client.request(method, path, headers=headers, **kwargs)
                assert response.status_code == expected, (path, response.status_code, response.text[:500])
                return response.json() if response.content else None

            tokens = []
            for name in ["owner", "friend", "outsider"]:
                email = f"qa-{name}@example.com"
                call("POST", "/auth/register", 201, json={"display_name": name.title(), "email": email, "password": PASSWORD})
                tokens.append(call("POST", "/auth/session", 201, json={"email": email, "password": PASSWORD})["token"])
            friend, outsider = tokens[1:]
            check("Immediate registration and password sign-in for three accounts")
            call("POST", "/auth/session", 422, json={"display_name": "Owner", "handle": "owner"})
            check("Handle-only sign-in disabled")
            email = "qa-friend@example.com"
            call("POST", "/auth/password/forgot", 202, json={"email": email})
            call("POST", "/auth/password/reset", json={"email": email, "code": inbox.codes[email], "password": PASSWORD + " updated"})
            call("GET", "/auth/me", 401, friend)
            call("POST", "/auth/session", 401, json={"email": email, "password": PASSWORD})
            check("SMTP password reset revokes the old session and password")
            call("DELETE", "/auth/session", 204, outsider)
            call("GET", "/auth/me", 401, outsider)
            check("Server-side logout revokes the token")
            Path("/tmp/syncinerary-qa-url.txt").write_text(base)
            print("Simulator API:", base, flush=True)
            if options.hold:
                print("Holding disposable server for simulator QA. Interrupt to clean up.", flush=True)
                while True:
                    time.sleep(1)
    finally:
        if api:
            api.terminate()
            try:
                api.wait(timeout=15)
            except subprocess.TimeoutExpired:
                api.kill(); api.wait()
        mail.stop()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(db_name)))
        admin.close()
        print("Disposable services and database cleaned up.", flush=True)


def stop_test(*_):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, stop_test)
    try:
        main()
    except KeyboardInterrupt:
        pass
