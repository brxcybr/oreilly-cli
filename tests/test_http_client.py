import json
import tempfile
import unittest
from pathlib import Path

from core.http_client import HttpClient


class HttpClientTests(unittest.TestCase):
    def test_capture_auth_cookies_persists_rotated_non_akamai_cookies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cookies_file = Path(tmpdir) / "cookies.json"
            cookies_file.write_text(json.dumps({"orm-jwt": "old"}), encoding="utf-8")

            client = HttpClient(cookies_file=cookies_file)
            client.session.cookies.update({"orm-jwt": "new", "_abck": "akamai"})
            client._capture_auth_cookies()

            saved = json.loads(cookies_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["orm-jwt"], "new")
            self.assertNotIn("_abck", saved)


if __name__ == "__main__":
    unittest.main()
