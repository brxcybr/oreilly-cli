import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import config
from cli import main as cli_main
from cli.resolver import ResolvedSource
from plugins.downloader import DownloadProgress


class CliMainTests(unittest.TestCase):
    def test_validate_formats_rejects_unknown_format(self):
        with self.assertRaisesRegex(ValueError, "Unsupported format"):
            cli_main._validate_formats(["epub,bad-format"])

    def test_validate_formats_expands_aliases_and_jsonl(self):
        self.assertEqual(cli_main._validate_formats(["md", "jsonl"]), ["markdown", "json", "jsonl"])

    def test_validate_formats_expands_all(self):
        self.assertEqual(
            cli_main._validate_formats(["all"]),
            ["epub", "markdown", "pdf", "plaintext", "json", "chunks"],
        )

    def test_output_style_separate_maps_chapter_formats(self):
        self.assertEqual(
            cli_main._apply_output_style(["markdown", "pdf", "plaintext", "epub"], "separate"),
            ["markdown-chapters", "pdf-chapters", "plaintext-chapters", "epub"],
        )

    def test_parse_chapters(self):
        self.assertEqual(cli_main._parse_chapters("0, 2,4"), [0, 2, 4])
        self.assertIsNone(cli_main._parse_chapters(None))

    def test_validate_formats_defaults_to_epub(self):
        self.assertEqual(cli_main._validate_formats([]), ["epub"])

    def test_chapter_selection_rejects_book_only_formats(self):
        with self.assertRaisesRegex(ValueError, "book-only"):
            cli_main._validate_chapter_selection(["epub"], [0])

    def test_apply_runtime_config_uses_cli_paths(self):
        original_cookies = config.COOKIES_FILE
        original_output = config.OUTPUT_DIR
        try:
            args = SimpleNamespace(cookies_file="~/cookies.json", output_dir="~/exports")
            cli_main._apply_runtime_config(args)
            self.assertEqual(config.COOKIES_FILE, Path("~/cookies.json").expanduser())
            self.assertEqual(config.OUTPUT_DIR, Path("~/exports").expanduser())
        finally:
            config.COOKIES_FILE = original_cookies
            config.OUTPUT_DIR = original_output

    def test_output_dir_is_accepted_after_export_command(self):
        parser = cli_main._build_parser()
        args = parser.parse_args(
            [
                "export",
                "9781492056355",
                "--format",
                "pdf",
                "--output-dir",
                "~/exports",
            ]
        )
        self.assertEqual(args.output_dir, "~/exports")
        self.assertEqual(args.sources, ["9781492056355"])

    def test_export_accepts_inline_cookie_import_options(self):
        parser = cli_main._build_parser()
        args = parser.parse_args(
            [
                "export",
                "9781492056355",
                "--login-stdin",
                "--keepalive-interval",
                "300",
                "--output-style",
                "combined",
            ]
        )
        self.assertTrue(args.login_stdin)
        self.assertEqual(args.keepalive_interval, 300)
        self.assertEqual(args.output_style, "combined")

    def test_export_accepts_resume_option(self):
        parser = cli_main._build_parser()
        args = parser.parse_args(["export", "9781492056355", "--resume"])
        self.assertTrue(args.resume)

    def test_export_help_mentions_resume(self):
        parser = cli_main._build_parser()
        with self.assertRaises(SystemExit):
            with patch.object(cli_main.sys, "argv", ["oreilly_cli.py", "export", "--help"]):
                with patch("sys.stdout") as stdout:
                    parser.parse_args(["export", "--help"])
        self.assertIn("--resume", "".join(call.args[0] for call in stdout.write.call_args_list))

    def test_playlist_manifest_writes_json_and_csv(self):
        resolved = [
            ResolvedSource(
                source="https://learning.oreilly.com/playlists/abc/",
                book_id="9781492050032",
                title="Learning Spark",
                reason="playlist:00000000-0000-4000-8000-000000000000",
            ),
            ResolvedSource(
                source="https://learning.oreilly.com/playlists/abc/",
                book_id="9798868802188",
                title="Azure Data Factory",
                reason="playlist:00000000-0000-4000-8000-000000000000",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = cli_main._prepare_playlist_manifest(resolved, Path(tmpdir))

            self.assertIsNotNone(manifest)
            self.assertTrue(manifest["json_path"].exists())
            self.assertTrue(manifest["csv_path"].exists())
            data = json.loads(manifest["json_path"].read_text(encoding="utf-8"))
            self.assertEqual(data["total"], 2)
            self.assertEqual([book["isbn"] for book in data["books"]], ["9781492050032", "9798868802188"])
            self.assertIn("9781492050032", manifest["csv_path"].read_text(encoding="utf-8"))

    def test_playlist_manifest_preserves_completed_status_for_resume(self):
        resolved = [
            ResolvedSource(
                source="playlist",
                book_id="9781492050032",
                title="Learning Spark",
                reason="playlist:00000000-0000-4000-8000-000000000000",
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = cli_main._prepare_playlist_manifest(resolved, Path(tmpdir))
            cli_main._update_playlist_manifest(
                manifest,
                "9781492050032",
                status="completed",
                output_dir="/tmp/book",
            )

            reloaded = cli_main._prepare_playlist_manifest(resolved, Path(tmpdir))

            self.assertEqual(cli_main._manifest_status(reloaded, "9781492050032"), "completed")

    def test_login_file_reads_cookie_text(self):
        with patch.object(Path, "read_text", return_value="orm-jwt=dummy") as read_text:
            args = SimpleNamespace(stdin=False, clipboard=False, file="~/cookies.txt")
            self.assertEqual(cli_main._read_cookie_text(args), "orm-jwt=dummy")
            read_text.assert_called_once_with(encoding="utf-8")

    def test_login_without_flag_reads_piped_stdin(self):
        args = SimpleNamespace(stdin=False, clipboard=False, file=None)
        with patch.object(cli_main.sys.stdin, "isatty", return_value=False):
            with patch.object(cli_main.sys.stdin, "read", return_value="orm-jwt=dummy"):
                self.assertEqual(cli_main._read_cookie_text(args), "orm-jwt=dummy")

    def test_interactive_cookie_source_defaults_to_clipboard(self):
        with patch("builtins.input", return_value=""):
            with patch("builtins.print"):
                with patch.object(cli_main, "_read_clipboard", return_value="orm-jwt=dummy"):
                    self.assertEqual(cli_main._prompt_cookie_source(), "orm-jwt=dummy")

    def test_clipboard_commands_use_macos_pbpaste(self):
        with patch.object(cli_main.sys, "platform", "darwin"):
            self.assertEqual(cli_main._clipboard_commands(), [["pbpaste"]])

    def test_clipboard_commands_use_windows_powershell(self):
        with patch.object(cli_main.sys, "platform", "win32"):
            with patch.object(cli_main.os, "name", "nt"):
                commands = cli_main._clipboard_commands()

        self.assertIn(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], commands)
        self.assertIn(["pwsh", "-NoProfile", "-Command", "Get-Clipboard -Raw"], commands)

    def test_clipboard_commands_use_wayland_then_linux_fallbacks(self):
        with patch.object(cli_main.sys, "platform", "linux"):
            with patch.object(cli_main.os, "name", "posix"):
                with patch.dict(cli_main.os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
                    with patch.object(cli_main, "_is_wsl", return_value=False):
                        commands = cli_main._clipboard_commands()

        self.assertEqual(commands[0], ["wl-paste", "--no-newline"])
        self.assertIn(["xclip", "-selection", "clipboard", "-out"], commands)
        self.assertIn(["xsel", "--clipboard", "--output"], commands)

    def test_clipboard_commands_use_wsl_powershell_before_linux_fallbacks(self):
        with patch.object(cli_main.sys, "platform", "linux"):
            with patch.object(cli_main.os, "name", "posix"):
                with patch.dict(cli_main.os.environ, {}, clear=True):
                    with patch.object(cli_main, "_is_wsl", return_value=True):
                        commands = cli_main._clipboard_commands()

        self.assertEqual(commands[0], ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"])
        self.assertIn(["xclip", "-selection", "clipboard", "-out"], commands)

    def test_read_clipboard_uses_first_available_command(self):
        with patch.object(cli_main, "_clipboard_commands", return_value=[["missingclip"], ["clipcmd", "--read"]]):
            with patch.object(cli_main.shutil, "which", side_effect=lambda command: f"/usr/bin/{command}" if command == "clipcmd" else None):
                with patch.object(cli_main.subprocess, "run", return_value=SimpleNamespace(stdout="orm-jwt=dummy\n")) as run:
                    self.assertEqual(cli_main._read_clipboard(), "orm-jwt=dummy\n")

        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["clipcmd", "--read"])

    def test_read_clipboard_explains_fallbacks_when_unavailable(self):
        with patch.object(cli_main, "_clipboard_commands", return_value=[["missingclip"]]):
            with patch.object(cli_main.shutil, "which", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "system clipboard"):
                    cli_main._read_clipboard()

    def test_import_export_cookies_from_stdin(self):
        args = SimpleNamespace(login_stdin=True, login_clipboard=False, login_file=None)
        with patch.object(cli_main.sys.stdin, "read", return_value="orm-jwt=dummy"):
            with patch.object(cli_main, "import_cookie_text") as import_cookie_text:
                cli_main._import_export_cookies(args)
        import_cookie_text.assert_called_once_with("orm-jwt=dummy", config.COOKIES_FILE)

    def test_progress_callback_throttles_asset_updates(self):
        callback = cli_main._make_progress_callback(1, 1)

        with patch("builtins.print") as mock_print:
            for current in range(1, 31):
                callback(
                    DownloadProgress(
                        status="downloading_assets",
                        percentage=80,
                        message=f"80% - Downloading images ({current}/100)",
                    )
                )

        printed = [call.args[0] for call in mock_print.call_args_list]
        self.assertEqual(len(printed), 2)
        self.assertIn("images (1/100)", printed[0])
        self.assertIn("images (25/100)", printed[1])

    def test_ensure_authenticated_prompts_until_cookie_refresh_validates(self):
        statuses = iter([{"valid": False}, {"valid": True}])
        with patch.object(cli_main, "get_auth_status", side_effect=lambda: next(statuses)):
            with patch.object(cli_main, "_interactive_cookie_refresh", return_value=True):
                with patch("builtins.print"):
                    self.assertTrue(cli_main.ensure_authenticated(prompt=True))


if __name__ == "__main__":
    unittest.main()
