#!/usr/bin/env python3
"""Local stdio MCP server for O'Reilly Ingest.

This module intentionally stays thin: it adapts MCP tool calls to the existing
kernel plugins and never exposes cookie/session material to clients.
"""

from __future__ import annotations

import os
import re
import stat
import threading
from pathlib import Path
from typing import Any

import config
from plugins.downloader import DownloaderPlugin

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only when MCP SDK is absent.
    FastMCP = None


AUTH_REFRESH_MESSAGE = (
    "Authentication is missing or expired. Refresh cookies manually through your "
    "browser and rerun the existing cookie-import workflow."
)
_SECRET_PATTERNS = (
    re.compile(r"orm-jwt=[^;\s]+", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"(cookie|authorization|x-api-key)\s*[:=]\s*[^,\s]+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
)
_export_lock = threading.Lock()


def _new_kernel():
    from core import create_default_kernel

    return create_default_kernel()


def _sanitize_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub("[redacted]", message)
    if "cookie" in message.lower() or "token" in message.lower() or "authenticated" in message.lower():
        if "expired" in message.lower() or "authenticated" in message.lower():
            return AUTH_REFRESH_MESSAGE
    return message


def _safe_call(fn):
    try:
        return fn()
    except Exception as exc:
        raise RuntimeError(_sanitize_error(exc)) from None


def _permission_warnings() -> list[str]:
    warnings: list[str] = []
    if not os.environ.get("OREILLY_COOKIES_FILE"):
        return warnings

    cookie_path = config.COOKIES_FILE
    parent = cookie_path.parent

    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        warnings.append(f"Could not create cookie directory: {parent}")

    if parent.exists():
        try:
            parent.chmod(0o700)
        except OSError:
            warnings.append(f"Cookie directory should be readable only by the current user: {parent}")
        else:
            mode = stat.S_IMODE(parent.stat().st_mode)
            if mode & 0o077:
                warnings.append(f"Cookie directory permissions are broader than 0700: {parent}")

    if cookie_path.exists():
        try:
            cookie_path.chmod(0o600)
        except OSError:
            warnings.append(f"Cookie file should be readable only by the current user: {cookie_path}")
        else:
            mode = stat.S_IMODE(cookie_path.stat().st_mode)
            if mode & 0o077:
                warnings.append(f"Cookie file permissions are broader than 0600: {cookie_path}")

    return warnings


def _validate_formats(formats: list[str]) -> tuple[list[str], list[str]]:
    if not formats:
        raise ValueError("At least one export format is required.")

    canonical: list[str] = []
    warnings: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()

    for raw in formats:
        fmt = str(raw).strip().lower()
        if not fmt:
            continue
        if fmt == "all":
            invalid.append(raw)
            continue

        resolved = DownloaderPlugin.FORMAT_ALIASES.get(fmt, fmt)
        if resolved not in DownloaderPlugin.SUPPORTED_FORMATS:
            invalid.append(raw)
            continue

        if resolved == "jsonl" and "json" not in seen:
            canonical.append("json")
            seen.add("json")
            warnings.append("jsonl also generates the base json export.")

        if resolved not in seen:
            canonical.append(resolved)
            seen.add(resolved)

    if invalid:
        supported = ", ".join(sorted(DownloaderPlugin.SUPPORTED_FORMATS))
        raise ValueError(f"Unsupported format(s): {', '.join(map(str, invalid))}. Supported formats: {supported}.")
    if not canonical:
        raise ValueError("At least one valid export format is required.")

    return canonical, warnings


def _validate_chapters(formats: list[str], chapters: list[int] | None) -> list[str]:
    if chapters is None:
        return []
    if not isinstance(chapters, list) or any(not isinstance(ch, int) or ch < 0 for ch in chapters):
        raise ValueError("chapters must be a list of zero-based non-negative integers.")

    warnings = []
    unsupported = [fmt for fmt in formats if not DownloaderPlugin.supports_chapter_selection(fmt)]
    if unsupported:
        raise ValueError(
            "Chapter selection is not supported for book-only format(s): "
            + ", ".join(sorted(unsupported))
        )
    return warnings


def _chapter_summary(chapter: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "title": chapter.get("title", f"Chapter {index + 1}"),
        "filename": chapter.get("filename"),
        "pages": chapter.get("virtual_pages"),
        "minutes": chapter.get("minutes_required"),
    }


def _file_paths(files: Any) -> Any:
    if isinstance(files, dict):
        return {key: _file_paths(value) for key, value in files.items()}
    if isinstance(files, list):
        return [_file_paths(value) for value in files]
    if isinstance(files, Path):
        return str(files)
    return files


def oreilly_status() -> dict[str, Any]:
    """Return safe authentication/session status."""
    def call():
        kernel = _new_kernel()
        status = dict(kernel["auth"].get_status())
        safe = {
            "valid": bool(status.get("valid")),
            "reason": status.get("reason"),
            "expires_at": status.get("expires_at"),
            "cookies_file": str(config.COOKIES_FILE),
            "warnings": _permission_warnings(),
        }
        if not safe["valid"]:
            safe["message"] = AUTH_REFRESH_MESSAGE
        return safe

    return _safe_call(call)


def oreilly_list_formats() -> dict[str, Any]:
    """Return export formats from the downloader source of truth."""
    return DownloaderPlugin.get_formats_info()


def oreilly_search(query: str, limit: int = 10) -> dict[str, Any]:
    """Search for books and return concise metadata only."""
    if not query or not query.strip():
        raise ValueError("query is required.")
    limit = max(1, min(int(limit), 25))

    def call():
        kernel = _new_kernel()
        results = []
        for item in kernel["book"].search(query.strip(), limit=limit):
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
        return {"query": query, "limit": limit, "results": results}

    return _safe_call(call)


def oreilly_get_book(book_id: str) -> dict[str, Any]:
    """Fetch metadata and chapter list for one book without chapter bodies."""
    if not book_id or not book_id.strip():
        raise ValueError("book_id is required.")

    def call():
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
            "chapters": [_chapter_summary(chapter, index) for index, chapter in enumerate(chapters)],
        }

    return _safe_call(call)


def oreilly_export_book(
    book_id: str,
    formats: list[str],
    chapters: list[int] | None = None,
    output_dir: str | None = None,
    skip_images: bool = False,
) -> dict[str, Any]:
    """Export one authorized book and return paths to generated files."""
    if not book_id or not book_id.strip():
        raise ValueError("book_id is required.")

    canonical_formats, warnings = _validate_formats(formats)
    warnings.extend(_validate_chapters(canonical_formats, chapters))

    def call():
        kernel = _new_kernel()
        output_plugin = kernel["output"]
        if output_dir:
            success, message, resolved_output_dir = output_plugin.validate_dir(output_dir)
        else:
            success, message, resolved_output_dir = output_plugin.validate_dir(config.OUTPUT_DIR)
        if not success or resolved_output_dir is None:
            raise ValueError(message)

        if not _export_lock.acquire(blocking=False):
            raise RuntimeError("Another export is already running. Try again after it completes.")
        try:
            result = kernel["downloader"].download(
                book_id=book_id.strip(),
                output_dir=resolved_output_dir,
                formats=canonical_formats,
                selected_chapters=chapters,
                skip_images=skip_images,
            )
        finally:
            _export_lock.release()

        return {
            "status": "completed",
            "title": result.title,
            "book_id": result.book_id,
            "output_dir": str(result.output_dir),
            "generated_files": _file_paths(result.files),
            "chapters_count": result.chapters_count,
            "warnings": warnings,
        }

    return _safe_call(call)


if FastMCP is not None:
    mcp = FastMCP("oreilly-ingest")
    mcp.tool()(oreilly_status)
    mcp.tool()(oreilly_list_formats)
    mcp.tool()(oreilly_search)
    mcp.tool()(oreilly_get_book)
    mcp.tool()(oreilly_export_book)
else:
    mcp = None


def main() -> None:
    if mcp is None:
        raise SystemExit("The MCP Python SDK is not installed. Run: pip install mcp")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
