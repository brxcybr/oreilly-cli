"""Resolve CLI source inputs into O'Reilly book IDs."""

from __future__ import annotations

import re
import json
from dataclasses import dataclass
from urllib.parse import urlparse

import config


BOOK_URL_RE = re.compile(r"/library/view/[^/]+/([^/?#]+)/?")
API_BOOK_RE = re.compile(r"/api/v1/book/([^/?#]+)/?")
PLAYLIST_URL_RE = re.compile(r"/playlists/([0-9a-fA-F-]{36})/?")
ISBN_RE = re.compile(r"^(?:97[89])?\d{9}[\dXx]$")


@dataclass(frozen=True)
class ResolvedSource:
    source: str
    book_id: str
    title: str | None = None
    reason: str = "direct"


def is_playlist_source(source: str) -> bool:
    return _playlist_id_from_source(source) is not None


def resolve_sources(kernel, sources: list[str], max_items: int = 20) -> tuple[list[ResolvedSource], list[str]]:
    """Resolve mixed book IDs, book URLs, ISBNs, and playlist URLs."""
    resolved: list[ResolvedSource] = []
    warnings: list[str] = []

    for source in sources:
        source = source.strip()
        if not source:
            continue
        if playlist_id := _playlist_id_from_source(source):
            playlist_items, playlist_warnings = resolve_playlist(kernel, playlist_id, source, max_items=max_items)
            resolved.extend(playlist_items)
            warnings.extend(playlist_warnings)
            continue
        resolved.append(resolve_book_source(kernel, source))

    deduped: list[ResolvedSource] = []
    seen: set[str] = set()
    for item in resolved:
        if item.book_id in seen:
            continue
        seen.add(item.book_id)
        deduped.append(item)

    if len(deduped) > max_items:
        warnings.append(f"Resolved {len(deduped)} books; limiting to first {max_items}.")
        deduped = deduped[:max_items]

    return deduped, warnings


def resolve_book_source(kernel, source: str) -> ResolvedSource:
    """Resolve a single non-playlist source to a book ID."""
    if book_id := _book_id_from_url(source):
        return ResolvedSource(source=source, book_id=book_id, reason="book_url")

    if _looks_like_isbn(source):
        return _resolve_isbn(kernel, source)

    return ResolvedSource(source=source, book_id=source, reason="book_id")


def resolve_playlist(kernel, playlist_id: str, source: str, max_items: int = 20) -> tuple[list[ResolvedSource], list[str]]:
    """Resolve a playlist through authenticated JSON endpoints.

    This intentionally avoids browser-page scraping. O'Reilly may change these
    private JSON endpoint shapes; failures are reported as warnings.
    """
    warnings: list[str] = []
    candidates = [
        f"{config.BASE_URL}/api/web/playlists/{playlist_id}/",
        f"{config.BASE_URL}/api/web/playlists/{playlist_id}",
        f"{config.API_V2}/playlists/{playlist_id}/",
        f"{config.API_V2}/playlists/{playlist_id}/items/",
        f"{config.API_V1}/playlists/{playlist_id}/",
        f"{config.API_V1}/playlists/{playlist_id}/items/",
    ]

    for url in candidates:
        try:
            data = kernel.http.get_json(url)
        except Exception:
            continue

        books = _extract_book_entries(data)
        if books:
            if len(books) > max_items:
                warnings.append(f"Playlist contains {len(books)} books; limiting to first {max_items}.")
                books = books[:max_items]
            return [
                ResolvedSource(
                    source=source,
                    book_id=book_id,
                    title=title,
                    reason=f"playlist:{playlist_id}",
                )
                for book_id, title in books
            ], warnings

    try:
        html = kernel.http.get_text(f"{config.BASE_URL}/playlists/{playlist_id}/")
        books = _extract_book_entries(_extract_playlist_from_html(html))
        if books:
            if len(books) > max_items:
                warnings.append(f"Playlist contains {len(books)} books; limiting to first {max_items}.")
                books = books[:max_items]
            return [
                ResolvedSource(
                    source=source,
                    book_id=book_id,
                    title=title,
                    reason=f"playlist_html:{playlist_id}",
                )
                for book_id, title in books
            ], warnings
    except Exception:
        pass

    warnings.append(f"Could not resolve playlist through known JSON endpoints: {playlist_id}")
    return [], warnings


def _resolve_isbn(kernel, isbn: str) -> ResolvedSource:
    results = kernel["book"].search(isbn, limit=5)
    for item in results:
        book_id = str(item.get("id") or "")
        if book_id == isbn:
            return ResolvedSource(source=isbn, book_id=book_id, title=item.get("title"), reason="isbn")
    if results:
        item = results[0]
        return ResolvedSource(
            source=isbn,
            book_id=str(item.get("id")),
            title=item.get("title"),
            reason="isbn_search",
        )
    return ResolvedSource(source=isbn, book_id=isbn, reason="isbn_direct")


def _book_id_from_url(source: str) -> str | None:
    parsed = urlparse(source)
    if not parsed.scheme and not parsed.netloc:
        return None
    match = BOOK_URL_RE.search(parsed.path)
    return match.group(1) if match else None


def _book_id_from_api_url(source: str) -> str | None:
    match = API_BOOK_RE.search(source)
    return match.group(1) if match else None


def _playlist_id_from_source(source: str) -> str | None:
    parsed = urlparse(source)
    path = parsed.path if parsed.scheme or parsed.netloc else source
    match = PLAYLIST_URL_RE.search(path)
    return match.group(1) if match else None


def _looks_like_isbn(source: str) -> bool:
    compact = source.replace("-", "").replace(" ", "")
    return bool(ISBN_RE.fullmatch(compact))


def _extract_book_entries(data) -> list[tuple[str, str | None]]:
    entries: list[tuple[str, str | None]] = []

    def walk(value):
        if isinstance(value, dict):
            book_id = _book_id_from_dict(value)
            if book_id:
                entries.append((book_id, _title_from_dict(value)))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    deduped: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for book_id, title in entries:
        if book_id in seen:
            continue
        seen.add(book_id)
        deduped.append((book_id, title))
    return deduped


def _book_id_from_dict(value: dict) -> str | None:
    for key in ("archive_id", "book_id", "identifier", "isbn", "api_url", "ourn", "id"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            candidate = _normalize_book_candidate(candidate)
            if candidate:
                return candidate

    for key in ("url", "web_url", "canonical_url", "content_url", "absolute_url"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            if book_id := _book_id_from_url(candidate):
                return book_id
    return None


def _normalize_book_candidate(candidate: str) -> str | None:
    if candidate.startswith("urn:orm:book:"):
        parts = candidate.split(":")
        return parts[3] if len(parts) >= 4 else None
    if _book_id_from_api_url(candidate):
        return _book_id_from_api_url(candidate)
    if _book_id_from_url(candidate):
        return _book_id_from_url(candidate)
    if _looks_like_isbn(candidate) or candidate.isdigit():
        return candidate.replace("-", "").replace(" ", "")
    return None


def _title_from_dict(value: dict) -> str | None:
    for key in ("title", "name", "display_title"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    content = value.get("content")
    if isinstance(content, dict):
        return _title_from_dict(content)
    return None


def _extract_playlist_from_html(html: str) -> dict:
    store = _extract_js_object(html, "initialStoreData")
    return store["playlistsCoreState"]["playlistSSR"]["playlist"]


def _extract_js_object(html: str, var_name: str) -> dict:
    marker = f"{var_name} ="
    start = html.find(marker)
    if start == -1:
        raise ValueError(f"Could not find JavaScript variable assignment: {var_name}")

    brace_start = html.find("{", start)
    if brace_start == -1:
        raise ValueError(f"Could not find object start for: {var_name}")

    depth = 0
    in_string = False
    string_quote = ""
    escaped = False

    for i in range(brace_start, len(html)):
        ch = html[i]

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == string_quote:
                in_string = False
            continue

        if ch in ('"', "'"):
            in_string = True
            string_quote = ch
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(html[brace_start : i + 1])

    raise ValueError(f"Could not find object end for: {var_name}")
