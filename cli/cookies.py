"""Cookie import helpers for CLI workflows."""

from __future__ import annotations

import json
import stat
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any


AKAMAI_COOKIE_PREFIXES = ("_abck", "bm_", "ak_", "akaalb_")


class CookieImportError(ValueError):
    """Raised when pasted cookie input cannot be parsed."""


def parse_cookie_input(text: str) -> dict[str, str]:
    """Parse browser-copied cookies into the JSON shape used by the repo.

    Supported inputs:
    - Raw Cookie header, optionally prefixed with "Cookie:"
    - JSON object mapping cookie name to value
    - JSON array of browser cookie objects with name/value fields
    """
    text = text.strip()
    if not text:
        raise CookieImportError("No cookie data was provided.")

    if text.startswith("{") or text.startswith("[") or text.startswith('"'):
        cookies = _parse_json_cookies(text)
    else:
        cookies = _parse_cookie_header(text)

    cookies = _filter_cookies(cookies)
    if not cookies:
        raise CookieImportError(
            "No usable authentication cookies were found. Refresh the O'Reilly page, "
            "copy cookies again, and if the browser console output only contains bot-management "
            "cookies, copy the request Cookie header from an authenticated O'Reilly network request."
        )

    return cookies


def write_cookie_file(cookies: dict[str, str], path: str | Path) -> Path:
    """Write cookie JSON with owner-only permissions where possible."""
    cookie_path = Path(path).expanduser()
    cookie_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_if_possible(cookie_path.parent, 0o700)
    cookie_path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    _chmod_if_possible(cookie_path, 0o600)
    return cookie_path


def import_cookie_text(text: str, path: str | Path) -> Path:
    """Parse and store pasted cookie data."""
    return write_cookie_file(parse_cookie_input(text), path)


def cookie_permission_warnings(path: str | Path) -> list[str]:
    warnings: list[str] = []
    cookie_path = Path(path).expanduser()
    parent = cookie_path.parent
    if parent.exists() and stat.S_IMODE(parent.stat().st_mode) & 0o077:
        warnings.append(f"Cookie directory permissions are broader than 0700: {parent}")
    if cookie_path.exists() and stat.S_IMODE(cookie_path.stat().st_mode) & 0o077:
        warnings.append(f"Cookie file permissions are broader than 0600: {cookie_path}")
    return warnings


def _parse_json_cookies(text: str) -> dict[str, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CookieImportError(f"Invalid cookie JSON: {exc.msg}.") from None

    if isinstance(data, str):
        return parse_cookie_input(data)

    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items() if value is not None}

    if isinstance(data, list):
        cookies: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            name = _first_present(item, ("name", "Name", "key"))
            value = _first_present(item, ("value", "Value"))
            if name and value is not None:
                cookies[str(name)] = str(value)
        if cookies:
            return cookies

    raise CookieImportError("Cookie JSON must be an object or an array of name/value objects.")


def _parse_cookie_header(text: str) -> dict[str, str]:
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    try:
        parsed = SimpleCookie()
        parsed.load(text)
    except Exception:
        parsed = SimpleCookie()

    cookies = {key: morsel.value for key, morsel in parsed.items()}
    if cookies:
        return cookies

    fallback: dict[str, str] = {}
    for part in text.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            fallback[name] = value
    if fallback:
        return fallback

    raise CookieImportError("Could not parse cookie data.")


def _filter_cookies(cookies: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in cookies.items()
        if name and value and not name.startswith(AKAMAI_COOKIE_PREFIXES)
    }


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _chmod_if_possible(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass
