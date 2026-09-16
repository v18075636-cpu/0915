import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import unittest

from werkzeug.serving import make_server

import test_security


class CurlContractTests(unittest.TestCase):
    def test_verbatim_spec_examples(self):
        spec_path = Path(os.environ.get("API_SPEC_PATH", Path.home() / "Downloads" / "API_SPEC.md"))
        spec = spec_path.read_text(encoding="utf-8")
        examples = re.search(r"```bash\n(.*?)```", spec, re.S).group(1)
        bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
        test_security.SecurityTests.setUpClass()
        fixture = test_security.SecurityTests
        responses = []
        server = None
        worker = None
        try:
            with fixture.module.connect_db() as connection:
                connection.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    ("test", fixture.module.generate_password_hash("1234", method="scrypt")),
                )

            def observe(environ, start_response):
                def capture(status, headers, exc_info=None):
                    responses.append((environ["PATH_INFO"], int(status.split()[0])))
                    return start_response(status, headers, exc_info)
                return fixture.app(environ, capture)

            server = make_server("127.0.0.1", 8000, observe)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            result = subprocess.run(
                [bash, "--noprofile", "--norc"], input=examples, text=True,
                encoding="utf-8", capture_output=True, cwd=fixture.directory.name, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            print("Unmodified curl examples:", responses, flush=True)
            self.assertEqual(responses, [
                ("/login", 302), ("/api/notes", 200),
                ("/api/notes", 201), ("/api/notes/2", 200),
            ])
            payloads = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            self.assertEqual(payloads[0], {"notes": []})
            self.assertEqual(payloads[1], payloads[2])
            self.assertEqual(payloads[1]["id"], 2)
            self.assertEqual(payloads[1]["title"], "meeting")
            self.assertEqual(payloads[1]["body"], "3pm")
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if worker is not None:
                worker.join(timeout=5)
            fixture.tearDownClass()


if __name__ == "__main__":
    unittest.main()
