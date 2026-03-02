from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import secrets
from typing import Optional

from scheduler.config import Settings


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


@dataclass
class AuthClaims:
    user_id: int
    username: str
    role: str
    participant_id: Optional[int]
    exp: int


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.iterations = 120_000

    def hash_password(self, raw_password: str) -> str:
        if not raw_password or len(raw_password) < 6:
            raise ValueError("密码长度至少 6 位")
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            raw_password.encode("utf-8"),
            salt.encode("utf-8"),
            self.iterations,
        )
        return f"pbkdf2_sha256${self.iterations}${salt}${digest.hex()}"

    def verify_password(self, raw_password: str, password_hash: str) -> bool:
        try:
            algo, iterations_str, salt, digest_hex = password_hash.split("$", 3)
        except ValueError:
            return False
        if algo != "pbkdf2_sha256":
            return False

        iterations = int(iterations_str)
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            raw_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(expected, digest_hex)

    def issue_token(self, user_id: int, username: str, role: str, participant_id: Optional[int]) -> str:
        expires = datetime.now(tz=timezone.utc) + timedelta(minutes=self.settings.auth_token_ttl_minutes)
        payload = {
            "uid": user_id,
            "username": username,
            "role": role,
            "pid": participant_id,
            "exp": int(expires.timestamp()),
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        sig = hmac.new(
            self.settings.auth_secret.encode("utf-8"),
            payload_bytes,
            digestmod=hashlib.sha256,
        ).digest()
        return f"{_b64_encode(payload_bytes)}.{_b64_encode(sig)}"

    def parse_token(self, token: str) -> Optional[AuthClaims]:
        try:
            encoded_payload, encoded_sig = token.split(".", 1)
            payload_bytes = _b64_decode(encoded_payload)
            given_sig = _b64_decode(encoded_sig)
        except Exception:  # noqa: BLE001
            return None

        expected_sig = hmac.new(
            self.settings.auth_secret.encode("utf-8"),
            payload_bytes,
            digestmod=hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(given_sig, expected_sig):
            return None

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
            claims = AuthClaims(
                user_id=int(payload["uid"]),
                username=str(payload["username"]),
                role=str(payload["role"]),
                participant_id=int(payload["pid"]) if payload.get("pid") is not None else None,
                exp=int(payload["exp"]),
            )
        except Exception:  # noqa: BLE001
            return None

        now_ts = int(datetime.now(tz=timezone.utc).timestamp())
        if claims.exp < now_ts:
            return None
        return claims
