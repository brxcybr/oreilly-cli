import json
import stat
import tempfile
import unittest
from pathlib import Path

from cli.cookies import CookieImportError, import_cookie_text, parse_cookie_input


class CookieImportTests(unittest.TestCase):
    def test_parse_raw_cookie_header_filters_akamai_cookies(self):
        cookies = parse_cookie_input("Cookie: orm-jwt=dummy; bm_sz=noise; other=value")
        self.assertEqual(cookies, {"orm-jwt": "dummy", "other": "value"})

    def test_parse_json_object(self):
        cookies = parse_cookie_input('{"orm-jwt": "dummy", "_abck": "noise"}')
        self.assertEqual(cookies, {"orm-jwt": "dummy"})

    def test_parse_json_string_containing_json_object(self):
        cookies = parse_cookie_input(json.dumps('{"orm-jwt": "dummy", "_abck": "noise"}'))
        self.assertEqual(cookies, {"orm-jwt": "dummy"})

    def test_parse_json_string_containing_cookie_header(self):
        cookies = parse_cookie_input(json.dumps("orm-jwt=dummy; bm_sz=noise"))
        self.assertEqual(cookies, {"orm-jwt": "dummy"})

    def test_parse_json_array(self):
        cookies = parse_cookie_input(
            json.dumps(
                [
                    {"name": "orm-jwt", "value": "dummy"},
                    {"name": "ak_bmsc", "value": "noise"},
                ]
            )
        )
        self.assertEqual(cookies, {"orm-jwt": "dummy"})

    def test_invalid_cookie_input_raises_without_secret_echo(self):
        with self.assertRaises(CookieImportError) as ctx:
            parse_cookie_input("not a cookie")
        self.assertNotIn("not a cookie", str(ctx.exception))

    def test_import_cookie_text_writes_owner_only_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cookie_path = Path(tmpdir) / "cookies" / "cookies.json"
            written = import_cookie_text("orm-jwt=dummy", cookie_path)
            self.assertEqual(written, cookie_path)
            self.assertEqual(stat.S_IMODE(cookie_path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(cookie_path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(cookie_path.read_text()), {"orm-jwt": "dummy"})


if __name__ == "__main__":
    unittest.main()
