import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).with_name("app.py").read_text(encoding="utf-8")


class DatabasePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.secret = secrets.token_hex(32)
        self.password = secrets.token_urlsafe(24)

    def load_app(self, location, database=None, production=False):
        location.mkdir(exist_ok=True)
        name = "database_test_" + secrets.token_hex(6)
        module = types.ModuleType(name)
        module.__file__ = str(location / "app.py")
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        with patch.dict(os.environ, {
            "SECRET_KEY": self.secret, "ADMIN_PASSWORD": self.password,
            "APP_ENV": "production" if production else "development",
            "TRUSTED_HOSTS": "localhost", "FLASK_DEBUG": "0",
        }):
            if database is None:
                os.environ.pop("DATABASE_PATH", None)
            else:
                os.environ["DATABASE_PATH"] = str(database)
            exec(compile(SOURCE, module.__file__, "exec"), module.__dict__)
        return module

    def test_unset_path_keeps_local_default(self):
        module = self.load_app(self.root / "local")
        self.assertEqual(module.DATABASE, self.root / "local" / "memo.db")
        self.assertTrue(module.DATABASE.is_file())

    def test_injected_path_ignores_local_database(self):
        local = self.root / "code"
        local.mkdir()
        original = local / "memo.db"
        original.write_bytes(b"untouched local file")
        database = self.root / "injected.db"
        module = self.load_app(local, database)
        self.assertEqual(module.DATABASE, database)
        self.assertTrue(database.is_file())
        self.assertEqual(original.read_bytes(), b"untouched local file")

    def test_production_database_and_session_survive_app_restart(self):
        volume = self.root / "data"
        volume.mkdir()
        database = volume / "memo.db"
        first = self.load_app(self.root / "container_one", database, production=True)
        client = first.app.test_client()
        response = client.post("/login", base_url="https://localhost", data={
            "username": "admin", "password": self.password,
        })
        self.assertEqual(response.status_code, 302)
        created = client.post("/api/notes", base_url="https://localhost", json={
            "title": "persistent title", "body": "persistent content",
        })
        self.assertEqual(created.status_code, 201)
        note = created.get_json()
        cookie_name = first.app.config["SESSION_COOKIE_NAME"]
        cookie = client.get_cookie(cookie_name).value
        with first.connect_db() as connection:
            before_users = [tuple(row) for row in connection.execute("SELECT * FROM users ORDER BY id")]
            before_memos = [tuple(row) for row in connection.execute("SELECT * FROM memos ORDER BY id")]
        self.password = secrets.token_urlsafe(24)
        second = self.load_app(self.root / "container_two", database, production=True)
        resumed = second.app.test_client()
        resumed.set_cookie(cookie_name, cookie)
        response = resumed.get(f"/api/notes/{note['id']}", base_url="https://localhost")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), note)
        with second.connect_db() as connection:
            self.assertEqual(before_users, [tuple(row) for row in connection.execute("SELECT * FROM users ORDER BY id")])
            self.assertEqual(before_memos, [tuple(row) for row in connection.execute("SELECT * FROM memos ORDER BY id")])
        self.assertFalse((self.root / "container_one" / "memo.db").exists())
        self.assertFalse((self.root / "container_two" / "memo.db").exists())

    def test_invalid_path_fails_without_fallback(self):
        location = self.root / "invalid"
        with self.assertRaises(sqlite3.OperationalError):
            self.load_app(location, self.root / "missing" / "memo.db")
        self.assertFalse((location / "memo.db").exists())
        self.assertFalse((self.root / "missing").exists())


if __name__ == "__main__":
    unittest.main()
