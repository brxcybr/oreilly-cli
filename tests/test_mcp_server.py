import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mcp_server


class _FakeKernel:
    def __init__(self, plugins):
        self.plugins = plugins

    def __getitem__(self, name):
        return self.plugins[name]


class _FakeOutputPlugin:
    def __init__(self):
        self.requested_path = None

    def validate_dir(self, path):
        self.requested_path = Path(path)
        self.requested_path.mkdir(parents=True, exist_ok=True)
        return True, "Directory is valid", self.requested_path


class McpServerTests(unittest.TestCase):
    def test_validate_formats_rejects_unknown_formats(self):
        with self.assertRaisesRegex(ValueError, "Unsupported format"):
            mcp_server._validate_formats(["epub", "bad-format"])

    def test_validate_formats_expands_aliases_and_jsonl(self):
        formats, warnings = mcp_server._validate_formats(["md", "jsonl"])
        self.assertEqual(formats, ["markdown", "json", "jsonl"])
        self.assertTrue(any("jsonl" in warning for warning in warnings))

    def test_chapter_selection_rejects_book_only_formats(self):
        with self.assertRaisesRegex(ValueError, "book-only"):
            mcp_server._validate_chapters(["epub"], [0])

    def test_empty_book_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "book_id is required"):
            mcp_server.oreilly_get_book(" ")

    def test_missing_auth_status_returns_refresh_message_without_secrets(self):
        auth = SimpleNamespace(
            get_status=lambda: {
                "valid": False,
                "reason": "not_authenticated",
                "orm-jwt": "dummy",
                "cookie": "private=value",
            }
        )

        with patch.object(mcp_server, "_new_kernel", return_value=_FakeKernel({"auth": auth})):
            result = mcp_server.oreilly_status()

        serialized = repr(result)
        self.assertFalse(result["valid"])
        self.assertIn("refresh cookies manually", result["message"].lower())
        self.assertNotIn("dummy", serialized)
        self.assertNotIn("private=value", serialized)

    def test_sanitize_error_redacts_secret_material(self):
        fake_jwt = "eyJ" + "abc.def.ghi"
        error = RuntimeError(f"authorization: Bearer abc123 cookie=orm-jwt={fake_jwt}")
        message = mcp_server._sanitize_error(error)
        self.assertNotIn("abc123", message)
        self.assertNotIn(fake_jwt, message)

    def test_export_uses_requested_output_dir_and_returns_paths_only(self):
        output_plugin = _FakeOutputPlugin()
        download_result = SimpleNamespace(
            title="Example Book",
            book_id="1234567890",
            output_dir=Path("/tmp/example-book"),
            files={"epub": "/tmp/example-book/example.epub"},
            chapters_count=2,
        )
        downloader = SimpleNamespace(download=lambda **kwargs: download_result)
        kernel = _FakeKernel({"output": output_plugin, "downloader": downloader})

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(mcp_server, "_new_kernel", return_value=kernel):
                result = mcp_server.oreilly_export_book(
                    book_id="1234567890",
                    formats=["epub"],
                    output_dir=tmpdir,
                    skip_images=True,
                )

            self.assertEqual(output_plugin.requested_path, Path(tmpdir))
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["generated_files"], {"epub": "/tmp/example-book/example.epub"})
            self.assertNotIn("contents", result)


if __name__ == "__main__":
    unittest.main()
