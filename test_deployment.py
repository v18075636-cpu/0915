import ast
import os
from pathlib import Path
import secrets
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from flask import request


ROOT = Path(__file__).resolve().parent


class ProductionProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.module = types.ModuleType("production_proxy_test_app")
        cls.module.__file__ = str(Path(cls.directory.name) / "app.py")
        sys.modules[cls.module.__name__] = cls.module
        with patch.dict(os.environ, {
            "SECRET_KEY": secrets.token_hex(32), "ADMIN_PASSWORD": secrets.token_urlsafe(24),
            "APP_ENV": "production", "TRUSTED_HOSTS": "0915.monster", "FLASK_DEBUG": "0",
        }):
            source = (ROOT / "app.py").read_text(encoding="utf-8")
            exec(compile(source, cls.module.__file__, "exec"), cls.module.__dict__)
        cls.observed = {}

        @cls.module.app.before_request
        def observe_proxy_values():
            cls.observed.update(
                host=request.host, remote_addr=request.remote_addr,
                scheme=request.scheme, script_root=request.script_root,
            )

        with patch.dict(sys.modules, {"app": cls.module}):
            exec(compile((ROOT / "wsgi.py").read_text(encoding="utf-8"), "wsgi.py", "exec"), {})

    @classmethod
    def tearDownClass(cls):
        del sys.modules[cls.module.__name__]
        cls.directory.cleanup()

    def test_caddy_https_and_production_cookie(self):
        response = self.module.app.test_client().get(
            "/login", base_url="http://0915.monster", headers={"X-Forwarded-Proto": "https"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.observed["scheme"], "https")
        cookie = response.headers["Set-Cookie"]
        for value in ("__Host-memo_session=", "Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
            self.assertIn(value, cookie)
        self.assertIn("Strict-Transport-Security", response.headers)

    def test_only_proto_header_is_trusted(self):
        response = self.module.app.test_client().get(
            "/login", base_url="http://0915.monster", headers={
                "X-Forwarded-Proto": "https", "X-Forwarded-For": "192.0.2.77",
                "X-Forwarded-Host": "untrusted.invalid", "X-Forwarded-Port": "1234",
                "X-Forwarded-Prefix": "/unexpected",
            }, environ_overrides={"REMOTE_ADDR": "172.20.0.2"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.observed, {
            "host": "0915.monster", "remote_addr": "172.20.0.2",
            "scheme": "https", "script_root": "",
        })

    def test_missing_or_non_https_proto_rejected(self):
        for headers in ({}, {"X-Forwarded-Proto": "http"}, {"X-Forwarded-Ssl": "on"}):
            response = self.module.app.test_client().get(
                "/login", base_url="http://0915.monster", headers=headers
            )
            self.assertEqual(response.status_code, 400)

    def test_forwarded_host_cannot_override_host_validation(self):
        response = self.module.app.test_client().get(
            "/login", base_url="http://untrusted.invalid", headers={
                "X-Forwarded-Proto": "https", "X-Forwarded-Host": "0915.monster",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_development_wsgi_does_not_trust_proxy_headers(self):
        plain_app = types.SimpleNamespace(wsgi_app=object())
        original = plain_app.wsgi_app
        module = types.SimpleNamespace(app=plain_app, production=False)
        with patch.dict(sys.modules, {"app": module}):
            exec(compile((ROOT / "wsgi.py").read_text(encoding="utf-8"), "wsgi.py", "exec"), {})
        self.assertIs(plain_app.wsgi_app, original)


class DeploymentStaticTests(unittest.TestCase):
    def test_single_worker_wsgi_and_no_implicit_header_trust(self):
        tree = ast.parse((ROOT / "gunicorn.conf.py").read_text(encoding="utf-8"))
        settings = {statement.targets[0].id: ast.literal_eval(statement.value) for statement in tree.body}
        self.assertEqual(settings["workers"], 1)
        self.assertEqual(settings["threads"], 1)
        self.assertEqual(settings["worker_class"], "sync")
        self.assertFalse(settings["preload_app"])
        self.assertEqual(settings["forwarded_allow_ips"], "")
        self.assertEqual(settings["secure_scheme_headers"], {})
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]', dockerfile)
        self.assertNotIn('CMD ["python", "app.py"]', dockerfile)

    def test_build_context_is_explicit_allowlist(self):
        patterns = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(patterns[0], "*")
        self.assertEqual(set(patterns[1:]), {
            "!Dockerfile", "!requirements.txt", "!app.py", "!wsgi.py", "!gunicorn.conf.py",
        })
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        copies = [line for line in dockerfile.splitlines() if line.startswith("COPY ")]
        self.assertEqual(copies, ["COPY requirements.txt .", "COPY app.py wsgi.py gunicorn.conf.py ./"])

    def test_caddy_tls_upstream_and_overwrite(self):
        caddy = (ROOT / "Caddyfile").read_text(encoding="utf-8")
        self.assertEqual(caddy.split(), [
            "0915.monster", "{", "reverse_proxy", "app:8000", "{",
            "header_up", "X-Forwarded-Proto", "{scheme}", "}", "}",
        ])

    def test_compose_boundary_and_unchanged_database_volume(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        app_section = compose.split("  app:\n", 1)[1].split("  caddy:\n", 1)[0]
        self.assertNotIn("ports:", app_section)
        self.assertNotIn("network_mode:", compose)
        self.assertIn("APP_ENV: production", app_section)
        self.assertIn("TRUSTED_HOSTS: 0915.monster", app_section)
        self.assertIn("./data:/app/data", app_section)
        self.assertIn('DATABASE = Path(__file__).with_name("memo.db")', (ROOT / "app.py").read_text(encoding="utf-8"))
        self.assertIn('"80:80"', compose)
        self.assertIn('"443:443"', compose)

    def test_ssh_action_release_commit_is_pinned(self):
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        self.assertIn("appleboy/ssh-action@7eaf76671a0d7eec5d98ee897acda4f968735a17", workflow)
        self.assertNotIn("ssh-action@master", workflow)


if __name__ == "__main__":
    unittest.main()
