import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name("app.py").read_text(encoding="utf-8")


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.module = types.ModuleType("memo_security_test_app")
        cls.module.__file__ = str(Path(cls.directory.name) / "app.py")
        sys.modules[cls.module.__name__] = cls.module
        cls.admin_password = secrets.token_urlsafe(24)
        with patch.dict(os.environ, {
            "SECRET_KEY": secrets.token_hex(32),
            "ADMIN_PASSWORD": cls.admin_password,
            "APP_ENV": "development",
            "TRUSTED_HOSTS": "localhost",
            "FLASK_DEBUG": "0",
        }):
            exec(compile(SOURCE, cls.module.__file__, "exec"), cls.module.__dict__)
        cls.app = cls.module.app
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        del sys.modules[cls.module.__name__]
        cls.directory.cleanup()

    def setUp(self):
        with self.module.connect_db() as connection:
            connection.execute("UPDATE rate_limits SET expires_at = 0")
        self.owner = self.create_member()
        self.other = self.create_member()
        self.guest = self.app.test_client()
        self.guest.get("/login")
        self.admin = self.app.test_client()
        self.admin.get("/login")
        self.assertEqual(self.post(self.admin, "/login", username="admin", password=self.admin_password).status_code, 302)

    def post(self, client, path, **data):
        with client.session_transaction() as state:
            data["csrf_token"] = state["csrf_token"]
        return client.post(path, data=data)

    def create_member(self):
        client = self.app.test_client()
        client.get("/register")
        username = "member_" + secrets.token_hex(6)
        password = secrets.token_urlsafe(20)
        self.assertEqual(self.post(client, "/register", username=username, password=password, is_admin="1").status_code, 302)
        self.assertEqual(self.post(client, "/login", username=username, password=password).status_code, 302)
        return client

    def create_memo(self, client=None, content="personal memo"):
        response = self.post(client or self.owner, "/memos/new", title="private title", content=content)
        self.assertEqual(response.status_code, 302)
        return response.headers["Location"]

    def test_crud_and_owner_isolation(self):
        detail = self.create_memo()
        self.assertIn("private title", self.owner.get("/").get_data(as_text=True))
        self.assertNotIn(detail + '"', self.other.get("/").get_data(as_text=True))
        self.assertEqual(self.owner.get(detail).status_code, 200)
        self.assertEqual(self.owner.get(detail + "/edit").status_code, 200)
        for client in (self.other, self.admin):
            self.assertEqual(client.get(detail).status_code, 404)
            self.assertEqual(client.get(detail + "/edit").status_code, 404)
            self.assertEqual(self.post(client, detail + "/edit", title="changed", content="changed").status_code, 404)
            self.assertEqual(self.post(client, detail + "/delete").status_code, 404)
        self.assertEqual(self.post(self.owner, detail + "/edit", title="edited", content="new body").status_code, 302)
        self.assertIn("new body", self.owner.get(detail).get_data(as_text=True))
        self.assertEqual(self.post(self.owner, detail + "/delete").status_code, 302)
        self.assertEqual(self.owner.get(detail).status_code, 404)

    def test_anonymous_and_admin_access(self):
        detail = self.create_memo()
        for path in ("/", "/admin", "/memos/new", detail, detail + "/edit"):
            self.assertEqual(self.guest.get(path).status_code, 302)
        for path in ("/memos/new", detail + "/edit", detail + "/delete"):
            self.assertEqual(self.post(self.guest, path, title="test", content="test").status_code, 302)
        self.assertEqual(self.owner.get("/admin").status_code, 403)
        self.assertEqual(self.admin.get("/admin").status_code, 200)
        with self.owner.session_transaction() as state:
            state["is_admin"] = True
            state["user_id"] = 1
        self.assertEqual(self.owner.get("/admin").status_code, 403)
        with self.module.connect_db() as connection:
            connection.execute("UPDATE users SET is_admin = 0 WHERE username = ?", ("admin",))
        try:
            self.assertEqual(self.admin.get("/admin").status_code, 403)
        finally:
            with self.module.connect_db() as connection:
                connection.execute("UPDATE users SET is_admin = 1 WHERE username = ?", ("admin",))

    def test_sql_input_remains_data(self):
        value = "' OR '1'='1"
        response = self.post(self.guest, "/login", username=value, password="invalid-password")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.guest.get("/admin").status_code, 302)
        detail = self.create_memo(content=value)
        self.assertEqual(self.owner.get(detail).status_code, 200)
        with self.module.connect_db() as connection:
            memo = connection.execute("SELECT content FROM memos WHERE id = ?", (int(detail.rsplit("/", 1)[1]),)).fetchone()
            self.assertEqual(memo["content"], value)

    def test_xss_escaped_and_csp(self):
        detail = self.create_memo(content="<script>alert(1)</script>")
        for path in (detail, detail + "/edit"):
            response = self.owner.get(path)
            html = response.get_data(as_text=True)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertNotIn("<script>alert(1)</script>", html)
            policy = response.headers["Content-Security-Policy"]
            self.assertNotIn("unsafe-inline", policy)
            nonce = policy.split("style-src 'nonce-", 1)[1].split("'", 1)[0]
            self.assertIn('nonce="' + nonce + '"', html)
            self.assertNotIn("onsubmit=", html)

    def test_csrf_all_post_routes(self):
        detail = self.create_memo()
        for path in ("/register", "/login", "/logout", "/memos/new", detail + "/edit", detail + "/delete", "/admin"):
            self.assertEqual(self.owner.post(path, headers={"Origin": "http://localhost"}).status_code, 400)
        self.assertEqual(self.owner.post(detail + "/delete", data={"csrf_token": "wrong"}).status_code, 400)
        self.assertEqual(self.owner.get(detail).status_code, 200)

    def test_account_rate_limit_and_expiry(self):
        username = "admin"
        with self.module.connect_db() as connection:
            connection.execute("UPDATE rate_limits SET expires_at = 0")
        for attempt in range(5):
            response = self.post(self.guest, "/login", username=username, password="incorrect")
            self.assertEqual(response.status_code, 200)
        response = self.post(self.guest, "/login", username=username, password="incorrect")
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["Retry-After"]), 0)
        with self.guest.session_transaction() as state:
            token = state["csrf_token"]
        response = self.guest.post(
            "/login", data={"username": username, "password": "incorrect", "csrf_token": token},
            environ_overrides={"REMOTE_ADDR": "192.0.2.20"},
        )
        self.assertEqual(response.status_code, 429)
        with patch.object(self.module.time, "time", return_value=time.time() + 901):
            self.assertEqual(self.post(self.guest, "/login", username=username, password="incorrect").status_code, 200)

    def test_ip_rate_limit_and_forwarded_header(self):
        with self.module.connect_db() as connection:
            connection.execute("UPDATE rate_limits SET expires_at = 0")
        with self.app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
            for attempt in range(30):
                self.assertEqual(self.module.limit_attempts("login", "account" + str(attempt)), 0)
        with self.guest.session_transaction() as state:
            token = state["csrf_token"]
        response = self.guest.post("/login", data={"csrf_token": token, "username": "fresh", "password": "invalid"}, headers={"X-Forwarded-For": "192.0.2.10"})
        self.assertEqual(response.status_code, 429)

    def test_session_rotation_revocation_expiry(self):
        client = self.app.test_client()
        client.get("/login")
        with client.session_transaction() as state:
            old_csrf = state["csrf_token"]
            state["untrusted"] = "discard"
        self.assertEqual(self.post(client, "/login", username="admin", password=self.admin_password).status_code, 302)
        with client.session_transaction() as state:
            self.assertNotIn("untrusted", state)
            self.assertNotEqual(old_csrf, state["csrf_token"])
        cookie_name = self.app.config["SESSION_COOKIE_NAME"]
        cookie = client.get_cookie(cookie_name).value
        self.assertEqual(self.post(client, "/logout").status_code, 302)
        client.set_cookie(cookie_name, cookie)
        self.assertEqual(client.get("/admin").status_code, 302)
        with self.owner.session_transaction() as state:
            token_hash = hashlib.sha256(state["auth_token"].encode()).hexdigest()
        with self.module.connect_db() as connection:
            connection.execute("UPDATE auth_sessions SET expires_at = 0 WHERE token_hash = ?", (token_hash,))
        self.assertEqual(self.owner.get("/").status_code, 302)

    def test_input_validation_and_generic_login(self):
        for username in ("bad name", "bad/name", "a" * 51, "zero\x00"):
            self.assertEqual(self.post(self.guest, "/register", username=username, password="valid-password").status_code, 200)
        for title, content in ((" ", "body"), ("a" * 101, "body"), ("title", "x" * 10001), ("title", "\x00")):
            self.assertEqual(self.post(self.owner, "/memos/new", title=title, content=content).status_code, 200)
        known = self.post(self.guest, "/login", username="admin", password="incorrect").get_data(as_text=True)
        unknown = self.post(self.guest, "/login", username="missing", password="incorrect").get_data(as_text=True)
        message = "아이디 또는 비밀번호가 올바르지 않습니다."
        self.assertIn(message, known)
        self.assertIn(message, unknown)

    def test_methods_paths_headers_errors(self):
        detail = self.create_memo()
        self.assertEqual(self.owner.get(detail + "/delete").status_code, 405)
        self.assertEqual(self.owner.get("/logout").status_code, 405)
        self.assertEqual(self.owner.get("/memos/" + "9" * 40).status_code, 404)
        self.assertEqual(self.owner.get("/memo.db").status_code, 404)
        self.assertEqual(self.owner.get("/../app.py").status_code, 404)
        self.assertEqual(self.guest.get("/login", headers={"Host": "untrusted.invalid"}).status_code, 400)
        response = self.guest.get("/login")
        for header, value in (("X-Content-Type-Options", "nosniff"), ("X-Frame-Options", "DENY"), ("Referrer-Policy", "no-referrer"), ("Cache-Control", "no-store")):
            self.assertEqual(response.headers[header], value)
        with patch.object(self.module, "connect_db", side_effect=sqlite3.OperationalError("private database detail")):
            response = self.owner.get("/")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private database detail", response.get_data(as_text=True))
        self.assertNotIn("Traceback", response.get_data(as_text=True))

    def test_production_cookies_and_https(self):
        previous_secure = self.app.config["SESSION_COOKIE_SECURE"]
        self.module.production = True
        self.app.config["SESSION_COOKIE_SECURE"] = True
        try:
            client = self.app.test_client()
            self.assertEqual(client.get("/login").status_code, 400)
            response = client.get("/login", base_url="https://localhost")
            self.assertEqual(response.status_code, 200)
            cookie = response.headers["Set-Cookie"]
            for flag in ("Secure", "HttpOnly", "SameSite=Lax"):
                self.assertIn(flag, cookie)
            self.assertIn("Strict-Transport-Security", response.headers)
        finally:
            self.module.production = False
            self.app.config["SESSION_COOKIE_SECURE"] = previous_secure

    def test_seed_and_password_storage(self):
        self.module.seed_admin()
        with self.module.connect_db() as connection:
            admins = connection.execute("SELECT * FROM users WHERE username = ?", ("admin",)).fetchall()
            self.assertEqual(len(admins), 1)
            self.assertTrue(admins[0]["password_hash"].startswith("scrypt:"))
            self.assertNotEqual(admins[0]["password_hash"], self.admin_password)
            memos = connection.execute("SELECT id FROM memos WHERE user_id = ?", (admins[0]["id"],)).fetchall()
        self.assertEqual(len(memos), 1)
        self.assertEqual(self.other.get("/memos/" + str(memos[0]["id"])).status_code, 404)

    def test_configuration_fails_closed(self):
        base = {
            "SECRET_KEY": secrets.token_hex(32), "ADMIN_PASSWORD": self.admin_password,
            "APP_ENV": "development", "TRUSTED_HOSTS": "localhost", "FLASK_DEBUG": "0",
        }
        for changes in ({"SECRET_KEY": ""}, {"APP_ENV": "production", "TRUSTED_HOSTS": ""}, {"FLASK_DEBUG": "1"}):
            namespace = {"__name__": self.module.__name__, "__file__": self.module.__file__}
            with patch.dict(os.environ, {**base, **changes}):
                with self.assertRaises(RuntimeError):
                    exec(compile(SOURCE, self.module.__file__, "exec"), namespace)

    def test_legacy_database_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "memo.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL)")
            connection.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("legacy", self.module.DUMMY_PASSWORD_HASH))
            connection.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO settings VALUES (?, ?)", ("secret_key", "obsolete-test-key"))
            connection.commit()
            connection.close()
            namespace = {"__name__": self.module.__name__, "__file__": str(Path(directory) / "app.py")}
            fresh_key = secrets.token_hex(32)
            with patch.dict(os.environ, {"SECRET_KEY": fresh_key, "ADMIN_PASSWORD": self.admin_password, "APP_ENV": "development", "TRUSTED_HOSTS": "localhost", "FLASK_DEBUG": "0"}):
                exec(compile(SOURCE, namespace["__file__"], "exec"), namespace)
            self.assertEqual(namespace["app"].secret_key, fresh_key)
            with namespace["connect_db"]() as connection:
                legacy = connection.execute("SELECT is_admin FROM users WHERE username = ?", ("legacy",)).fetchone()
                self.assertEqual(legacy["is_admin"], 0)
                self.assertEqual(connection.execute("SELECT value FROM settings WHERE key = ?", ("secret_key",)).fetchone()[0], "obsolete-test-key")

    def test_api_contract_and_existing_pages(self):
        response = self.owner.get("/api/notes")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"notes": []})
        response = self.owner.post("/api/notes", json={"title": "meeting"})
        self.assertEqual(response.status_code, 201)
        note = response.get_json()
        self.assertIsInstance(note["id"], int)
        self.assertEqual(note["body"], "")
        for field in ("title", "body", "created_at", "updated_at"):
            self.assertIsInstance(note[field], str)
        self.assertEqual(self.owner.get("/api/notes").get_json(), {"notes": [note]})
        self.assertEqual(self.owner.get(f"/api/notes/{note['id']}").get_json(), note)
        self.assertEqual(self.owner.get(f"/memos/{note['id']}").status_code, 200)
        self.assertEqual(self.post(self.owner, f"/memos/{note['id']}/edit", title="changed", content="new body").status_code, 302)
        updated = self.owner.get(f"/api/notes/{note['id']}").get_json()
        self.assertEqual(updated["body"], "new body")
        self.assertEqual(self.post(self.owner, f"/memos/{note['id']}/delete").status_code, 302)
        self.assertEqual(self.owner.get(f"/api/notes/{note['id']}").status_code, 404)

    def test_api_auth_and_ownership_json_errors(self):
        response = self.owner.post("/api/notes", json={"title": "private", "body": "owner only"})
        note_id = response.get_json()["id"]
        for method, path in (("GET", "/api/notes"), ("POST", "/api/notes"), ("GET", f"/api/notes/{note_id}")):
            response = self.guest.open(path, method=method)
            self.assertEqual(response.status_code, 401)
            self.assertTrue(response.is_json)
            self.assertNotIn("Location", response.headers)
        for client in (self.other, self.admin):
            response = client.get(f"/api/notes/{note_id}")
            self.assertEqual(response.status_code, 404)
            self.assertTrue(response.is_json)
        self.assertEqual(self.other.get("/api/notes").get_json(), {"notes": []})
        self.post(self.owner, "/logout")
        self.assertEqual(self.owner.get("/api/notes").status_code, 401)

    def test_api_validation_and_json_csrf_protection(self):
        for payload in ({}, {"title": ""}, {"title": " "}, {"title": None}, {"title": 12}, {"title": "ok", "body": []}, []):
            response = self.owner.post("/api/notes", json=payload)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.is_json)
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
            response = self.owner.post("/api/notes", data='{"title":"test"}', content_type=content_type)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(response.is_json)
        for headers in ({"Origin": "https://other.invalid"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
            response = self.owner.post("/api/notes", json={"title": "test"}, headers=headers)
            self.assertEqual(response.status_code, 201)
            self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        response = self.owner.post("/api/notes", json={"title": "ok", "body": ""}, headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
        preflight = self.guest.options("/api/notes", headers={
            "Origin": "https://other.invalid", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        self.assertNotIn("Access-Control-Allow-Origin", preflight.headers)
        self.assertNotIn("Access-Control-Allow-Credentials", preflight.headers)
        response = self.owner.post("/api/notes", json={"title": "a" * 101, "body": "b" * 10001})
        self.assertEqual(response.status_code, 201)

    def test_login_browser_csrf_and_cookie_client_contract(self):
        for headers in (
            {"Origin": "http://localhost"}, {"Origin": "https://other.invalid"},
            {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Mode": "navigate"},
            {"Referer": "https://other.invalid/"},
        ):
            client = self.app.test_client()
            response = client.post("/login", data={"username": "admin", "password": self.admin_password}, headers=headers)
            self.assertEqual(response.status_code, 400)
        client = self.app.test_client()
        response = client.post("/login", data={"username": "admin", "password": self.admin_password, "csrf_token": "incorrect"})
        self.assertEqual(response.status_code, 400)
        response = client.post("/login", data={"username": "admin", "password": self.admin_password})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get("/api/notes").status_code, 200)
        browser = self.app.test_client()
        browser.get("/login")
        with browser.session_transaction() as state:
            token = state["csrf_token"]
        response = browser.post("/login", data={"username": "admin", "password": self.admin_password, "csrf_token": token}, headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 302)

    def test_api_methods_errors_and_csp(self):
        for method in ("PUT", "PATCH", "DELETE"):
            response = self.owner.open("/api/notes/1", method=method, json={})
            self.assertEqual(response.status_code, 405)
            self.assertTrue(response.is_json)
        for path in ("/api/notes/999999", "/api/notes/not-an-id", "/api/notes/" + "9" * 40):
            response = self.owner.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertTrue(response.is_json)
        with patch.object(self.module, "connect_db", side_effect=sqlite3.OperationalError("private")):
            response = self.owner.get("/api/notes")
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.is_json)
        self.assertNotIn("private", response.get_data(as_text=True))
        self.assertIn("connect-src 'self'", self.owner.get("/").headers["Content-Security-Policy"])

    def test_api_plain_text_and_legacy_memos(self):
        detail = self.create_memo(content="legacy content")
        note_id = int(detail.rsplit("/", 1)[1])
        self.assertEqual(self.owner.get(f"/api/notes/{note_id}").get_json()["body"], "legacy content")
        content = "<script>alert(1)</script>"
        response = self.owner.post("/api/notes", json={"title": "literal text", "body": content})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["body"], content)
        note_id = response.get_json()["id"]
        html = self.owner.get(f"/memos/{note_id}").get_data(as_text=True)
        self.assertNotIn(content, html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
