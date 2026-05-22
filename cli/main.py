"""Command-line wrapper for the O'Reilly export tool."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import config
from cli.cookies import CookieImportError, import_cookie_text, cookie_permission_warnings
from cli.resolver import is_playlist_source, resolve_sources
from plugins.chunking import ChunkConfig
from plugins.downloader import DownloaderPlugin


AUTH_REFRESH_MESSAGE = (
    "Authentication is missing or expired. Refresh cookies manually through your "
    "browser and paste fresh cookies when prompted."
)
COOKIE_COPY_SNIPPET = """copy(JSON.stringify(
  document.cookie
    .split(';')
    .map(c => {
      const [k, ...v] = c.split('=');
      return [k.trim(), v.join('=').trim()];
    })
    .reduce((r, [k, v]) => ({ ...r, [k]: v }), {})
))"""
_SECRET_PATTERNS = (
    re.compile(r"orm-jwt=[^;\s]+", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"(cookie|authorization|x-api-key)\s*[:=]\s*[^,\s]+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    argv = _repair_split_cookie_path(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    _apply_runtime_config(args)

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {_sanitize_error(exc)}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search and export authorized O'Reilly books.",
        epilog="Run `python oreilly_cli.py export --help` for export flags including --resume.",
    )
    parser.add_argument("-c", "--cookies-file", help="Path to local cookies JSON file.")
    parser.add_argument("-o", "--output-dir", help="Default export directory.")
    parser.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON output.")

    subparsers = parser.add_subparsers(dest="command")

    status = subparsers.add_parser("status", help="Check authentication status.")
    _add_runtime_options(status)
    status.set_defaults(func=cmd_status)

    login = subparsers.add_parser(
        "login",
        help="Paste and store browser cookies.",
        description=(
            "Import O'Reilly cookies from stdin, clipboard, file, or an interactive prompt. "
            "Use the documented browser console JSON copy command and prefer --clipboard "
            "or --stdin for long cookie strings."
        ),
    )
    _add_runtime_options(login)
    login_source = login.add_mutually_exclusive_group()
    login_source.add_argument("-s", "--stdin", action="store_true", help="Read cookie data from stdin.")
    login_source.add_argument("-l", "--clipboard", action="store_true", help="Read cookie data from the system clipboard.")
    login_source.add_argument("-i", "--file", help="Read cookie data from a file.")
    login.set_defaults(func=cmd_login)

    formats = subparsers.add_parser("formats", help="List supported export formats.")
    _add_runtime_options(formats)
    formats.set_defaults(func=cmd_formats)

    search = subparsers.add_parser("search", help="Search O'Reilly books.")
    _add_runtime_options(search)
    search.add_argument("query")
    search.add_argument("-n", "--limit", type=int, default=10)
    search.set_defaults(func=cmd_search)

    book = subparsers.add_parser("book", help="Show book metadata and chapters.")
    _add_runtime_options(book)
    book.add_argument("book_id")
    book.set_defaults(func=cmd_book)

    export = subparsers.add_parser(
        "export",
        help="Export one or more authorized books.",
        description=(
            "Export book IDs, ISBNs, book URLs, or playlist URLs. Playlist exports write "
            "a destination manifest that --resume can use after timeouts."
        ),
    )
    _add_runtime_options(export)
    export.add_argument(
        "sources",
        nargs="+",
        help="Book ID, ISBN, book URL, or playlist URL. Multiple sources are exported serially.",
    )
    export.add_argument("--format", "-f", action="append", help="Export format. Repeat or comma-separate.")
    export.add_argument("-C", "--chapters", help="Comma-separated zero-based chapter indexes.")
    export.add_argument(
        "--output-style",
        choices=("combined", "separate"),
        default="combined",
        help="Write combined output or separate chapter files where supported.",
    )
    export.add_argument("-S", "--separate", action="store_true", help="Shortcut for --output-style separate.")
    export.add_argument("-x", "--skip-images", action="store_true")
    cookie_source = export.add_mutually_exclusive_group()
    cookie_source.add_argument(
        "--login-stdin",
        action="store_true",
        help="Import fresh cookies from stdin before validating and exporting.",
    )
    cookie_source.add_argument(
        "-l",
        "--login",
        "--login-clipboard",
        action="store_true",
        dest="login_clipboard",
        help="Import fresh cookies from the system clipboard before validating and exporting.",
    )
    cookie_source.add_argument(
        "--login-file",
        help="Import fresh cookies from a file before validating and exporting.",
    )
    export.add_argument("--chunk-size", type=int, default=4000, help="Chunk size for --format chunks.")
    export.add_argument("--chunk-overlap", type=int, default=200, help="Chunk overlap for --format chunks.")
    export.add_argument(
        "-k",
        "--keepalive-interval",
        type=int,
        default=0,
        help="Best-effort session keepalive interval in seconds during export.",
    )
    export.add_argument("-m", "--max-items", type=int, default=20, help="Maximum resolved books to export.")
    export.add_argument("-n", "--dry-run", action="store_true", help="Resolve sources but do not export.")
    export.add_argument("-r", "--resume", action="store_true", help="Skip playlist items already marked completed in the output manifest.")
    export.add_argument("-a", "--continue-on-error", action="store_true", help="Continue exporting remaining books after a failure.")
    export.set_defaults(func=cmd_export)

    resolve = subparsers.add_parser("resolve", help="Resolve book IDs, ISBNs, book URLs, or playlist URLs.")
    _add_runtime_options(resolve)
    resolve.add_argument("sources", nargs="+")
    resolve.add_argument("-m", "--max-items", type=int, default=20)
    resolve.set_defaults(func=cmd_resolve)

    menu = subparsers.add_parser("menu", help="Open the interactive menu.")
    _add_runtime_options(menu)
    menu.set_defaults(func=cmd_menu)

    parser.set_defaults(func=cmd_menu)
    return parser


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--cookies-file", default=argparse.SUPPRESS, help="Path to local cookies JSON file.")
    parser.add_argument("-o", "--output-dir", default=argparse.SUPPRESS, help="Default export directory.")
    parser.add_argument("-j", "--json", action="store_true", default=argparse.SUPPRESS, help="Print machine-readable JSON output.")


def cmd_status(args) -> int:
    status = get_auth_status()
    _print_result(args, status, _print_status)
    return 0 if status.get("valid") else 2


def cmd_login(args) -> int:
    cookie_text = _read_cookie_text(args)
    path = import_cookie_text(cookie_text, config.COOKIES_FILE)
    status = get_auth_status()
    result = {
        "cookies_file": str(path),
        "valid": status.get("valid", False),
        "reason": status.get("reason"),
        "expires_at": status.get("expires_at"),
        "warnings": cookie_permission_warnings(path),
    }
    _print_result(args, result, _print_login_result)
    return 0 if result["valid"] else 2


def cmd_formats(args) -> int:
    info = DownloaderPlugin.get_formats_info()
    _print_result(args, info, _print_formats)
    return 0


def cmd_search(args) -> int:
    if not ensure_authenticated(prompt=sys.stdin.isatty()):
        return 2
    kernel = _new_kernel()
    limit = max(1, min(args.limit, 25))
    results = []
    for item in kernel["book"].search(args.query, limit=limit):
        book_id = item.get("id")
        results.append(
            {
                "book_id": book_id,
                "title": item.get("title"),
                "authors": item.get("authors", []),
                "publishers": item.get("publishers", []),
                "url": f"{config.BASE_URL}/library/view/-/{book_id}/" if book_id else None,
                "content_type": "book",
            }
        )
    _print_result(args, {"query": args.query, "results": results}, _print_search_results)
    return 0


def cmd_book(args) -> int:
    if not ensure_authenticated(prompt=sys.stdin.isatty()):
        return 2
    result = get_book_metadata(args.book_id)
    _print_result(args, result, _print_book)
    return 0


def cmd_export(args) -> int:
    _import_export_cookies(args)
    if not ensure_authenticated(prompt=sys.stdin.isatty()):
        return 2

    formats = _validate_formats(args.format or ["epub"])
    output_style = "separate" if args.separate else args.output_style
    formats = _apply_output_style(formats, output_style)
    chapters = _parse_chapters(args.chapters)
    _validate_chapter_selection(formats, chapters)
    chunk_config = _build_chunk_config(args) if "chunks" in formats else None

    kernel = _new_kernel()
    output_plugin = kernel["output"]
    success, message, output_dir = output_plugin.validate_dir(config.OUTPUT_DIR)
    if not success or output_dir is None:
        raise ValueError(message)

    resolved, warnings = resolve_sources(kernel, args.sources, max_items=max(1, args.max_items))
    if not resolved:
        raise ValueError("No valid book sources were resolved.")

    manifest = _prepare_playlist_manifest(resolved, output_dir)

    skipped: list[dict[str, Any]] = []
    if args.resume and manifest:
        pending = []
        for item in resolved:
            if _manifest_status(manifest, item.book_id) == "completed":
                skipped.append(_resolved_payload(item) | {"status": "skipped_completed"})
            else:
                pending.append(item)
        resolved = pending

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    if not args.dry_run:
        keepalive_stop = _start_keepalive(args.keepalive_interval, enabled=not getattr(args, "json", False))
        try:
            total = len(resolved)
            for index, item in enumerate(resolved, start=1):
                try:
                    if manifest:
                        _update_playlist_manifest(manifest, item.book_id, status="in_progress")
                    if not getattr(args, "json", False):
                        title = f" - {item.title}" if item.title else ""
                        print(f"Exporting book {index}/{total}: {item.book_id}{title}")
                    result = kernel["downloader"].download(
                        book_id=item.book_id,
                        output_dir=output_dir,
                        formats=formats,
                        selected_chapters=chapters,
                        skip_images=args.skip_images,
                        chunk_config=chunk_config,
                        progress_callback=(
                            None
                            if getattr(args, "json", False)
                            else _make_progress_callback(index, total)
                        ),
                    )
                except Exception as exc:
                    error = _sanitize_error(exc)
                    errors.append({"source": item.source, "book_id": item.book_id, "error": error})
                    if manifest:
                        _update_playlist_manifest(manifest, item.book_id, status="failed", error=error)
                    if not args.continue_on_error:
                        break
                    continue
                payload = _download_result_payload(result)
                results.append(payload)
                if manifest:
                    _update_playlist_manifest(
                        manifest,
                        item.book_id,
                        status="completed",
                        output_dir=payload.get("output_dir"),
                        generated_files=payload.get("generated_files"),
                        error="",
                    )
        finally:
            keepalive_stop()

    payload = {
        "status": "resolved" if args.dry_run else ("completed" if not errors else "partial_error"),
        "sources": [_resolved_payload(item) for item in resolved],
        "exports": results,
        "errors": errors,
        "skipped": skipped,
        "playlist_manifest": _manifest_payload(manifest) if manifest else None,
        "warnings": warnings,
    }
    _print_result(args, payload, _print_batch_export_result)
    return 1 if errors else 0


def cmd_resolve(args) -> int:
    if not ensure_authenticated(prompt=sys.stdin.isatty()):
        return 2
    kernel = _new_kernel()
    resolved, warnings = resolve_sources(kernel, args.sources, max_items=max(1, args.max_items))
    payload = {
        "sources": [_resolved_payload(item) for item in resolved],
        "warnings": warnings,
    }
    _print_result(args, payload, _print_resolved_sources)
    return 0 if resolved else 1


def cmd_menu(args) -> int:
    print("O'Reilly CLI")
    print(f"Cookies: {config.COOKIES_FILE}")
    print(f"Output:  {config.OUTPUT_DIR}")

    if not ensure_authenticated(prompt=True):
        return 2

    last_results: list[dict[str, Any]] = []
    while True:
        print("\nMenu")
        print("1. Search books")
        print("2. View book metadata and chapters")
        print("3. Export book or playlist")
        print("4. List formats")
        print("5. Refresh cookies")
        print("6. Status")
        print("0. Quit")
        choice = input("> ").strip()

        try:
            if choice == "1":
                if not ensure_authenticated(prompt=True):
                    continue
                query = input("Search query: ").strip()
                if not query:
                    continue
                limit = _input_int("Limit", default=10, minimum=1, maximum=25)
                kernel = _new_kernel()
                last_results = kernel["book"].search(query, limit=limit)
                _print_search_results({"query": query, "results": _normalize_search_results(last_results)})
            elif choice == "2":
                if not ensure_authenticated(prompt=True):
                    continue
                book_id = _choose_book_id(last_results)
                if book_id:
                    _print_book(get_book_metadata(book_id))
            elif choice == "3":
                if not ensure_authenticated(prompt=True):
                    continue
                source = _choose_export_source(last_results)
                if source:
                    _menu_export(source)
            elif choice == "4":
                _print_formats(DownloaderPlugin.get_formats_info())
            elif choice == "5":
                _interactive_cookie_refresh()
            elif choice == "6":
                _print_status(get_auth_status())
            elif choice == "0":
                return 0
            else:
                print("Choose a listed option.")
        except Exception as exc:
            print(f"Error: {_sanitize_error(exc)}")


def ensure_authenticated(prompt: bool) -> bool:
    while True:
        status = get_auth_status()
        if status.get("valid"):
            return True
        print(AUTH_REFRESH_MESSAGE)
        if status.get("reason"):
            print(f"Reason: {status['reason']}")
        if status.get("expires_at"):
            print(f"Expires: {status['expires_at']}")
        if not prompt:
            return False
        if not _interactive_cookie_refresh():
            return False


def get_auth_status() -> dict[str, Any]:
    kernel = _new_kernel()
    status = dict(kernel["auth"].get_status())
    safe = {
        "valid": bool(status.get("valid")),
        "reason": status.get("reason"),
        "expires_at": status.get("expires_at"),
        "cookies_file": str(config.COOKIES_FILE),
        "warnings": cookie_permission_warnings(config.COOKIES_FILE),
    }
    if not safe["valid"]:
        safe["message"] = AUTH_REFRESH_MESSAGE
    return safe


def get_book_metadata(book_id: str) -> dict[str, Any]:
    if not book_id.strip():
        raise ValueError("book_id is required.")
    kernel = _new_kernel()
    clean_id = book_id.strip()
    info = kernel["book"].fetch(clean_id)
    chapters = kernel["chapters"].fetch_list(clean_id)
    toc = kernel["chapters"].fetch_toc(clean_id)
    chapters = kernel["chapters"].reorder_by_toc(chapters, toc)
    return {
        "book_id": clean_id,
        "title": info.get("title"),
        "authors": info.get("authors", []),
        "publisher": ", ".join(info.get("publishers", [])),
        "publishers": info.get("publishers", []),
        "publication_date": info.get("publication_date"),
        "description": info.get("description"),
        "isbn": info.get("isbn"),
        "chapters": [
            {
                "index": index,
                "title": chapter.get("title", f"Chapter {index + 1}"),
                "filename": chapter.get("filename"),
                "pages": chapter.get("virtual_pages"),
                "minutes": chapter.get("minutes_required"),
            }
            for index, chapter in enumerate(chapters)
        ],
    }


def _interactive_cookie_refresh() -> bool:
    try:
        cookie_text = _prompt_cookie_source()
        import_cookie_text(cookie_text, config.COOKIES_FILE)
        status = get_auth_status()
    except (CookieImportError, RuntimeError, ValueError) as exc:
        print(f"Cookie import failed: {_sanitize_error(exc)}")
        return False

    if status.get("valid"):
        print("Session validated.")
        return True

    print(AUTH_REFRESH_MESSAGE)
    return False


def _read_cookie_text(args) -> str:
    if getattr(args, "stdin", False):
        return sys.stdin.read()
    if getattr(args, "clipboard", False):
        return _read_clipboard()
    if getattr(args, "file", None):
        return Path(args.file).expanduser().read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return _prompt_cookie_source()


def _import_export_cookies(args) -> None:
    if getattr(args, "login_stdin", False):
        cookie_text = sys.stdin.read()
    elif getattr(args, "login_clipboard", False):
        cookie_text = _read_clipboard()
    elif getattr(args, "login_file", None):
        cookie_text = Path(args.login_file).expanduser().read_text(encoding="utf-8")
    else:
        return

    import_cookie_text(cookie_text, config.COOKIES_FILE)


def _read_clipboard() -> str:
    attempted: list[str] = []
    for command in _clipboard_commands():
        executable = command[0]
        if shutil.which(executable) is None:
            continue

        attempted.append(_format_clipboard_command(command))
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue

        if result.stdout.strip():
            return result.stdout

    tried = ", ".join(attempted) if attempted else "no supported clipboard command found"
    raise RuntimeError(
        "Could not read cookie data from the system clipboard. "
        f"Tried {tried}. Install/use pbpaste on macOS, PowerShell Get-Clipboard on "
        "Windows or WSL, wl-paste on Wayland Linux, xclip or xsel on X11 Linux, "
        "or use --stdin/--file."
    )


def _clipboard_commands() -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pbpaste"]]

    if os.name == "nt":
        return [
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            ["pwsh", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        ]

    commands: list[list[str]] = []
    if _is_wsl():
        commands.extend(
            [
                ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                ["pwsh.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            ]
        )
    if os.environ.get("WAYLAND_DISPLAY"):
        commands.extend([["wl-paste", "--no-newline"], ["wl-paste"]])
    if os.environ.get("DISPLAY"):
        commands.extend(
            [
                ["xclip", "-selection", "clipboard", "-out"],
                ["xsel", "--clipboard", "--output"],
            ]
        )

    for fallback in (
        ["wl-paste", "--no-newline"],
        ["wl-paste"],
        ["xclip", "-selection", "clipboard", "-out"],
        ["xsel", "--clipboard", "--output"],
    ):
        if fallback not in commands:
            commands.append(fallback)

    return commands


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True

    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _format_clipboard_command(command: list[str]) -> str:
    executable = command[0].lower()
    if executable in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return f"{command[0]} Get-Clipboard"
    return command[0]


def _prompt_cookie_text() -> str:
    print("\nCookie refresh")
    print("1. Open https://learning.oreilly.com in your browser and confirm you are signed in.")
    print("2. Open browser DevTools Console and run this command to copy a JSON cookie object:")
    print(COOKIE_COPY_SNIPPET)
    print("3. For large cookie blobs, prefer clipboard import instead of manual paste.")
    print("4. You can also copy the request Cookie header for an O'Reilly page/API request.")
    print("5. Paste the Cookie header, cookie JSON object, or exported cookie array below.")
    print("6. Press Enter on a blank line to finish. Cookie values will not be printed back.")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line:
            break
        lines.append(line)
    return "\n".join(lines)


def _prompt_cookie_source() -> str:
    while True:
        print("\nCookie import")
        print("Open https://learning.oreilly.com, confirm you are signed in, then run this in the browser console:")
        print(COOKIE_COPY_SNIPPET)
        print("\nChoose how to import the copied cookie data:")
        print("1. Read from system clipboard (recommended)")
        print("2. Read from file")
        print("3. Paste manually")
        print("0. Cancel")
        choice = input("> ").strip() or "1"

        if choice == "1":
            return _read_clipboard()
        if choice == "2":
            path = input("Cookie file path: ").strip()
            if path:
                return Path(path).expanduser().read_text(encoding="utf-8")
            print("Path is required.")
        elif choice == "3":
            return _prompt_cookie_text()
        elif choice == "0":
            raise CookieImportError("Cookie import cancelled.")
        else:
            print("Choose a listed option.")


def _choose_export_source(last_results: list[dict[str, Any]]) -> str:
    if last_results:
        print("Recent search results:")
        for index, item in enumerate(last_results, start=1):
            print(f"{index}. {item.get('title')} ({item.get('id')})")
        raw = input("Book ID, result number, book URL, or playlist URL: ").strip()
        if raw.isdigit():
            result_index = int(raw) - 1
            if 0 <= result_index < len(last_results):
                return str(last_results[result_index].get("id") or "")
        return raw
    return input("Book ID, ISBN, book URL, or playlist URL: ").strip()


def _menu_export(source: str) -> None:
    _print_formats(DownloaderPlugin.get_formats_info())
    raw_formats = input("Formats [epub]: ").strip() or "epub"
    raw_chapters = input("Chapter indexes, comma-separated, blank for all: ").strip()
    output_style = input("Output style combined/separate [combined]: ").strip().lower() or "combined"
    if output_style not in {"combined", "separate"}:
        output_style = "combined"
    skip_images = input("Skip images? [y/N]: ").strip().lower() in {"y", "yes"}
    resume = False
    if is_playlist_source(source):
        resume = input("Resume completed playlist items from manifest? [y/N]: ").strip().lower() in {"y", "yes"}
    max_items = _input_int("Max resolved items", default=20, minimum=1, maximum=1000)
    keepalive_interval = _input_int("Keepalive interval seconds, 0 to disable", default=0, minimum=0, maximum=86400)
    continue_on_error = input("Continue after item failures? [y/N]: ").strip().lower() in {"y", "yes"}

    args = argparse.Namespace(
        sources=[source],
        format=[raw_formats],
        chapters=raw_chapters or None,
        output_style=output_style,
        separate=False,
        skip_images=skip_images,
        login_stdin=False,
        login_clipboard=False,
        login_file=None,
        chunk_size=4000,
        chunk_overlap=200,
        keepalive_interval=keepalive_interval,
        max_items=max_items,
        dry_run=False,
        resume=resume,
        continue_on_error=continue_on_error,
        json=False,
    )
    cmd_export(args)


def _choose_book_id(last_results: list[dict[str, Any]]) -> str:
    if last_results:
        print("Recent search results:")
        for index, item in enumerate(last_results, start=1):
            print(f"{index}. {item.get('title')} ({item.get('id')})")
        raw = input("Book ID or result number: ").strip()
        if raw.isdigit():
            result_index = int(raw) - 1
            if 0 <= result_index < len(last_results):
                return str(last_results[result_index].get("id") or "")
        return raw
    return input("Book ID: ").strip()


def _normalize_search_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for item in results:
        book_id = item.get("id")
        normalized.append(
            {
                "book_id": book_id,
                "title": item.get("title"),
                "authors": item.get("authors", []),
                "publishers": item.get("publishers", []),
                "url": f"{config.BASE_URL}/library/view/-/{book_id}/" if book_id else None,
                "content_type": "book",
            }
        )
    return normalized


def _apply_runtime_config(args) -> None:
    if getattr(args, "cookies_file", None):
        config.COOKIES_FILE = _normalize_cookie_file_path(args.cookies_file)
    if getattr(args, "output_dir", None):
        config.OUTPUT_DIR = Path(args.output_dir).expanduser()


def _new_kernel():
    try:
        from core import create_default_kernel
    except ModuleNotFoundError as exc:
        if exc.name == "curl_cffi":
            raise RuntimeError(_missing_dependency_message("curl_cffi")) from None
        raise

    return create_default_kernel()


def _normalize_cookie_file_path(raw_path: str | Path) -> Path:
    raw_text = str(raw_path)
    path = Path(raw_text).expanduser()
    if raw_text.endswith("/") or path.is_dir() or path.name == ".oreilly-cli":
        return path / "cookies.json"
    return path


def _repair_split_cookie_path(argv: list[str]) -> list[str]:
    repaired: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        repaired.append(item)
        if item in {"--cookies-file", "-c"} and index + 2 < len(argv):
            base = argv[index + 1]
            tail = argv[index + 2]
            if _looks_like_split_cookie_tail(tail):
                repaired.append(str(Path(base).expanduser() / tail.lstrip("/")))
                index += 3
                continue
        index += 1
    return repaired


def _looks_like_split_cookie_tail(value: str) -> bool:
    normalized = value.strip()
    return normalized in {"/cookies.json", "cookies.json"} or normalized.endswith("/cookies.json")


def _missing_dependency_message(package: str) -> str:
    return (
        f"Missing required dependency `{package}` for O'Reilly HTTP access. "
        "Activate the project environment and install requirements:\n"
        "  source .venv/bin/activate\n"
        "  python -m pip install -r requirements.txt\n"
        "If activation did not take, run `.venv/bin/python -m pip install -r requirements.txt` directly.\n"
        "Then rerun the command with the same `python`. "
        f"Current Python: {sys.executable}"
    )


def _validate_formats(raw_formats: list[str]) -> list[str]:
    raw: list[str] = []
    for item in raw_formats:
        raw.extend(part.strip().lower() for part in str(item).split(",") if part.strip())
    if not raw:
        raw = ["epub"]

    formats: list[str] = []
    seen: set[str] = set()
    invalid: list[str] = []
    for fmt in raw:
        if fmt == "all":
            for expanded in DownloaderPlugin.ALL_FORMATS:
                if expanded not in seen:
                    formats.append(expanded)
                    seen.add(expanded)
            continue
        canonical = DownloaderPlugin.FORMAT_ALIASES.get(fmt, fmt)
        if canonical not in DownloaderPlugin.SUPPORTED_FORMATS:
            invalid.append(fmt)
            continue
        if canonical == "jsonl" and "json" not in seen:
            formats.append("json")
            seen.add("json")
        if canonical not in seen:
            formats.append(canonical)
            seen.add(canonical)

    if invalid:
        supported = ", ".join(sorted(DownloaderPlugin.SUPPORTED_FORMATS))
        raise ValueError(f"Unsupported format(s): {', '.join(invalid)}. Supported formats: {supported}.")
    return formats


def _apply_output_style(formats: list[str], output_style: str) -> list[str]:
    if output_style == "combined":
        return formats
    if output_style != "separate":
        raise ValueError("output_style must be 'combined' or 'separate'.")

    separate_formats = {
        "markdown": "markdown-chapters",
        "pdf": "pdf-chapters",
        "plaintext": "plaintext-chapters",
    }
    styled: list[str] = []
    seen: set[str] = set()
    for fmt in formats:
        canonical = separate_formats.get(fmt, fmt)
        if canonical not in seen:
            styled.append(canonical)
            seen.add(canonical)
    return styled


def _parse_chapters(value: str | None) -> list[int] | None:
    if value is None or not value.strip():
        return None
    chapters: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if not item.isdigit():
            raise ValueError("chapters must be comma-separated zero-based integers.")
        chapters.append(int(item))
    return chapters


def _validate_chapter_selection(formats: list[str], chapters: list[int] | None) -> None:
    if chapters is None:
        return
    unsupported = [fmt for fmt in formats if not DownloaderPlugin.supports_chapter_selection(fmt)]
    if unsupported:
        raise ValueError(
            "Chapter selection is not supported for book-only format(s): "
            + ", ".join(sorted(unsupported))
        )


def _build_chunk_config(args) -> ChunkConfig:
    if args.chunk_size < 1:
        raise ValueError("chunk-size must be greater than zero.")
    if args.chunk_overlap < 0:
        raise ValueError("chunk-overlap must be zero or greater.")
    if args.chunk_overlap >= args.chunk_size:
        raise ValueError("chunk-overlap must be smaller than chunk-size.")
    return ChunkConfig(
        chunk_size=args.chunk_size,
        overlap=args.chunk_overlap,
        respect_boundaries=True,
    )


def _prepare_playlist_manifest(resolved: list, output_dir: Path) -> dict[str, Any] | None:
    playlist_items = []
    playlist_ids: list[str] = []
    for position, item in enumerate(resolved, start=1):
        playlist_id = _playlist_id_from_reason(item.reason)
        if not playlist_id:
            continue
        playlist_items.append((position, playlist_id, item))
        if playlist_id not in playlist_ids:
            playlist_ids.append(playlist_id)

    if not playlist_items:
        return None

    stem = f"playlist-{playlist_ids[0]}-isbns" if len(playlist_ids) == 1 else "playlists-isbns"
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"
    previous = _load_playlist_manifest(json_path)

    books = []
    for position, playlist_id, item in playlist_items:
        old = previous.get(item.book_id, {})
        books.append(
            {
                "position": position,
                "playlist_id": playlist_id,
                "isbn": item.book_id,
                "book_id": item.book_id,
                "title": item.title or old.get("title") or "",
                "source": item.source,
                "reason": item.reason,
                "status": old.get("status") or "pending",
                "output_dir": old.get("output_dir") or "",
                "generated_files": old.get("generated_files") or {},
                "error": old.get("error") or "",
            }
        )

    manifest = {
        "json_path": json_path,
        "csv_path": csv_path,
        "payload": {
            "kind": "oreilly_playlist_manifest",
            "playlist_ids": playlist_ids,
            "total": len(books),
            "books": books,
        },
    }
    _write_playlist_manifest(manifest)
    return manifest


def _load_playlist_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    books = data.get("books")
    if not isinstance(books, list):
        return {}
    previous: dict[str, dict[str, Any]] = {}
    for item in books:
        if not isinstance(item, dict):
            continue
        book_id = str(item.get("book_id") or item.get("isbn") or "")
        if book_id:
            previous[book_id] = item
    return previous


def _playlist_id_from_reason(reason: str | None) -> str | None:
    if not reason or not reason.startswith("playlist"):
        return None
    _, _, playlist_id = reason.partition(":")
    return playlist_id or None


def _manifest_record(manifest: dict[str, Any], book_id: str) -> dict[str, Any] | None:
    for record in manifest["payload"]["books"]:
        if record.get("book_id") == book_id or record.get("isbn") == book_id:
            return record
    return None


def _manifest_status(manifest: dict[str, Any], book_id: str) -> str | None:
    record = _manifest_record(manifest, book_id)
    if not record:
        return None
    return str(record.get("status") or "")


def _update_playlist_manifest(
    manifest: dict[str, Any],
    book_id: str,
    *,
    status: str,
    output_dir: str | None = None,
    generated_files: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    record = _manifest_record(manifest, book_id)
    if not record:
        return
    record["status"] = status
    if output_dir is not None:
        record["output_dir"] = output_dir
    if generated_files is not None:
        record["generated_files"] = generated_files
    if error is not None:
        record["error"] = error
    _write_playlist_manifest(manifest)


def _write_playlist_manifest(manifest: dict[str, Any]) -> None:
    json_path: Path = manifest["json_path"]
    csv_path: Path = manifest["csv_path"]
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(manifest["payload"], indent=2), encoding="utf-8")

    fields = ["position", "playlist_id", "isbn", "title", "status", "output_dir", "error"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for record in manifest["payload"]["books"]:
            writer.writerow({field: record.get(field, "") for field in fields})


def _manifest_payload(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not manifest:
        return None
    return {
        "json_path": str(manifest["json_path"]),
        "csv_path": str(manifest["csv_path"]),
        "total": manifest["payload"]["total"],
        "playlist_ids": manifest["payload"]["playlist_ids"],
    }


def _start_keepalive(interval: int, enabled: bool = True):
    if interval <= 0:
        return lambda: None

    stop_event = threading.Event()

    def worker() -> None:
        while not stop_event.wait(interval):
            try:
                kernel = _new_kernel()
                response = kernel.http.get("/profile/")
                valid = (
                    response.status_code == 200
                    and "login" not in response.url
                    and "signin" not in response.url
                    and '"user_type":"Expired"' not in response.text
                )
                if enabled and not valid:
                    print("Keepalive warning: session no longer validates.", file=sys.stderr)
            except Exception as exc:
                if enabled:
                    print(f"Keepalive warning: {_sanitize_error(exc)}", file=sys.stderr)

    thread = threading.Thread(target=worker, name="oreilly-keepalive", daemon=True)
    thread.start()

    def stop() -> None:
        stop_event.set()
        thread.join(timeout=1)

    return stop


def _make_progress_callback(book_index: int, total_books: int):
    last_line = {"value": ""}
    last_asset_percentage = {"value": None}

    asset_re = re.compile(r"Downloading (?:images|CSS) \(\s*(\d+)/(\d+)\)")

    def callback(progress) -> None:
        if progress.status == "downloading_assets" and progress.message:
            match = asset_re.search(progress.message)
            if match:
                current = int(match.group(1))
                total = int(match.group(2))
                is_terminal = current == total
                if (
                    progress.percentage == last_asset_percentage["value"]
                    and not is_terminal
                    and current % 25 != 0
                ):
                    return
                last_asset_percentage["value"] = progress.percentage

        parts = [f"[{book_index}/{total_books}]", f"{progress.percentage:3d}%", progress.status]
        if progress.current_chapter and progress.total_chapters:
            parts.append(f"chapter {progress.current_chapter}/{progress.total_chapters}")
        if progress.chapter_title:
            title = progress.chapter_title
            if len(title) > 72:
                title = title[:69] + "..."
            parts.append(title)
        if progress.eta_seconds:
            parts.append(f"ETA {_format_seconds(progress.eta_seconds)}")
        if progress.message:
            parts.append(progress.message)

        line = " | ".join(str(part) for part in parts if part)
        if line != last_line["value"]:
            print(line)
            last_line["value"] = line

    return callback


def _format_seconds(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remaining}s" if remaining else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _input_int(prompt: str, default: int, minimum: int, maximum: int) -> int:
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _print_result(args, payload: dict[str, Any], printer) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        printer(payload)


def _print_status(status: dict[str, Any]) -> None:
    print(f"Authenticated: {'yes' if status.get('valid') else 'no'}")
    if status.get("reason"):
        print(f"Reason: {status['reason']}")
    if status.get("expires_at"):
        print(f"Expires: {status['expires_at']}")
    print(f"Cookies: {status.get('cookies_file')}")
    for warning in status.get("warnings", []):
        print(f"Warning: {warning}")


def _print_login_result(result: dict[str, Any]) -> None:
    print(f"Cookies saved: {result['cookies_file']}")
    _print_status(result)


def _print_formats(info: dict[str, Any]) -> None:
    descriptions = info.get("descriptions", {})
    for fmt in info.get("formats", []):
        suffix = " [book-only]" if fmt in info.get("book_only", []) else ""
        print(f"{fmt}{suffix}: {descriptions.get(fmt, '')}")


def _print_search_results(payload: dict[str, Any]) -> None:
    results = payload.get("results", [])
    if not results:
        print("No results.")
        return
    for index, item in enumerate(results, start=1):
        authors = ", ".join(item.get("authors") or [])
        print(f"{index}. {item.get('title')} ({item.get('book_id')})")
        if authors:
            print(f"   {authors}")
        if item.get("url"):
            print(f"   {item['url']}")


def _print_book(book: dict[str, Any]) -> None:
    print(f"{book.get('title')} ({book.get('book_id')})")
    authors = ", ".join(book.get("authors") or [])
    if authors:
        print(f"Authors: {authors}")
    if book.get("publisher"):
        print(f"Publisher: {book['publisher']}")
    if book.get("publication_date"):
        print(f"Published: {book['publication_date']}")
    chapters = book.get("chapters", [])
    print(f"Chapters: {len(chapters)}")
    for chapter in chapters:
        print(f"  {chapter['index']}. {chapter.get('title')}")


def _print_export_result(result: dict[str, Any]) -> None:
    print(f"Exported: {result.get('title')} ({result.get('book_id')})")
    print(f"Output: {result.get('output_dir')}")
    for fmt, paths in result.get("generated_files", {}).items():
        if isinstance(paths, list):
            print(f"{fmt}:")
            for path in paths:
                print(f"  {path}")
        else:
            print(f"{fmt}: {paths}")


def _print_batch_export_result(result: dict[str, Any]) -> None:
    for warning in result.get("warnings", []):
        print(f"Warning: {warning}")
    manifest = result.get("playlist_manifest")
    if manifest:
        print(f"Playlist manifest: {manifest.get('json_path')}")
        print(f"Playlist ISBN CSV: {manifest.get('csv_path')}")
    if result.get("status") == "resolved":
        _print_resolved_sources(result)
        return
    for skipped in result.get("skipped", []):
        print(f"Skipped completed: {skipped.get('book_id')}")
    for export in result.get("exports", []):
        _print_export_result(export)
    for error in result.get("errors", []):
        print(f"Error exporting {error.get('book_id')} from {error.get('source')}: {error.get('error')}")


def _print_resolved_sources(result: dict[str, Any]) -> None:
    for warning in result.get("warnings", []):
        print(f"Warning: {warning}")
    sources = result.get("sources", [])
    if not sources:
        print("No book sources resolved.")
        return
    for index, item in enumerate(sources, start=1):
        title = f" - {item['title']}" if item.get("title") else ""
        print(f"{index}. {item['book_id']}{title}")
        print(f"   source: {item['source']}")
        print(f"   reason: {item['reason']}")


def _download_result_payload(result) -> dict[str, Any]:
    return {
        "status": "completed",
        "book_id": result.book_id,
        "title": result.title,
        "output_dir": str(result.output_dir),
        "generated_files": _paths_to_strings(result.files),
        "chapters_count": result.chapters_count,
    }


def _resolved_payload(item) -> dict[str, Any]:
    return {
        "source": item.source,
        "book_id": item.book_id,
        "title": item.title,
        "reason": item.reason,
    }


def _paths_to_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _paths_to_strings(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_paths_to_strings(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _sanitize_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("[redacted]", message)
    if "cookie" in message.lower() or "token" in message.lower() or "authenticated" in message.lower():
        if "expired" in message.lower() or "authenticated" in message.lower():
            return AUTH_REFRESH_MESSAGE
    return message


if __name__ == "__main__":
    raise SystemExit(main())
