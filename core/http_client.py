import base64
import contextlib
import json
import time
from pathlib import Path

from curl_cffi import requests

import config


class HttpClient:
    # Akamai bot-management cookies are tied to the original browser TLS session.
    # Sending them from a non-browser client causes Akamai to return 403.
    _AKAMAI_COOKIE_PREFIXES = ("_abck", "bm_", "ak_", "akaalb_")

    def __init__(self, cookies_file: Path | None = None):
        self._auth_cookies: dict = {}
        self.session = requests.Session(impersonate="safari17_0")
        self.session.headers.update(config.HEADERS)
        self.last_request_time = 0

        cookies_path = cookies_file or config.COOKIES_FILE
        if cookies_path.exists():
            self._load_cookies(cookies_path)

    def _load_cookies(self, path: Path):
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            with open(path) as f:
                cookies = json.load(f)
            if isinstance(cookies, dict):
                self._auth_cookies = {
                    k: v for k, v in cookies.items()
                    if not k.startswith(self._AKAMAI_COOKIE_PREFIXES)
                }

    def _apply_auth_cookies(self):
        """Reset session to only auth cookies, discarding any Akamai cookies
        injected by previous responses."""
        self.session.cookies.clear()
        self.session.cookies.update(self._auth_cookies)

    def _rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < config.REQUEST_DELAY:
            time.sleep(config.REQUEST_DELAY - elapsed)
        self.last_request_time = time.time()

    def get(self, url: str, **kwargs) -> requests.Response:
        self._rate_limit()
        if not url.startswith("http"):
            url = config.BASE_URL + url
        kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
        self._apply_auth_cookies()
        return self.session.get(url, **kwargs)

    def get_json(self, url: str, **kwargs) -> dict:
        response = self.get(url, **kwargs)
        if response.status_code == 403 and self._jwt_expired():
            raise RuntimeError(
                "Session token expired. Please copy fresh cookies from your browser and POST them to /api/cookies."
            )
        response.raise_for_status()
        return response.json()

    def get_text(self, url: str, **kwargs) -> str:
        response = self.get(url, **kwargs)
        response.raise_for_status()
        return response.text

    def get_bytes(self, url: str, **kwargs) -> bytes:
        response = self.get(url, **kwargs)
        response.raise_for_status()
        return response.content

    def _jwt_expired(self) -> bool:
        token = self._auth_cookies.get("orm-jwt")
        if not token:
            return False
        try:
            payload_b64 = token.split(".")[1]
            padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.b64decode(padded))
            return time.time() > payload.get("exp", 0) - 60
        except Exception:
            return False

    def reload_cookies(self):
        """Clear and reload cookies from file. Used after browser login."""
        self._auth_cookies = {}
        self.session.cookies.clear()
        if config.COOKIES_FILE.exists():
            self._load_cookies(config.COOKIES_FILE)
