import base64
import json
import time

from .base import Plugin


def _decode_jwt_payload(token: str) -> dict | None:
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.b64decode(padded))
    except Exception:
        return None


class AuthPlugin(Plugin):
    def _check_jwt(self) -> dict | None:
        """Return JWT status from cookies.json without an HTTP round-trip.

        Returns None if no orm-jwt cookie is present.
        Returns dict with valid/reason/expires_at otherwise.
        """
        if not (jwt_token := self.http._auth_cookies.get("orm-jwt")):
            return None

        payload = _decode_jwt_payload(jwt_token)
        if not payload:
            return {"valid": False, "reason": "invalid_token"}

        exp = payload.get("exp", 0)
        expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))

        if time.time() > exp - 60:
            return {"valid": False, "reason": "token_expired", "expires_at": expires_at}

        return {"valid": True, "reason": None, "expires_at": expires_at}

    def validate_session(self) -> bool:
        jwt_status = self._check_jwt()
        if jwt_status is not None:
            return jwt_status["valid"]
        response = self.http.get("/profile/")
        return (
            "login" not in response.url
            and "signin" not in response.url
            and response.status_code == 200
            and '"user_type":"Expired"' not in response.text
        )

    def get_status(self) -> dict:
        jwt_status = self._check_jwt()
        if jwt_status is not None:
            return jwt_status

        response = self.http.get("/profile/")

        if "login" in response.url or "signin" in response.url:
            return {"valid": False, "reason": "not_authenticated"}

        if response.status_code != 200:
            return {"valid": False, "reason": "not_authenticated", "status_code": response.status_code}

        if '"user_type":"Expired"' in response.text:
            return {"valid": False, "reason": "subscription_expired"}

        return {"valid": True, "reason": None}
