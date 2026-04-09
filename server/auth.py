"""
Stock Arena - Authentication Module
JWT tokens + bcrypt password hashing
"""

from datetime import datetime, timedelta
from typing import Optional
import hashlib
import hmac
import json
import base64
import os

# ── 설정 ──────────────────────────────────────
SECRET_KEY = os.environ.get("SA_SECRET_KEY", "stock-arena-secret-change-me-2026")
TOKEN_EXPIRE_HOURS = 24 * 365  # 1년

# ── 비밀번호 (bcrypt 없으면 sha256 fallback) ──
try:
    from passlib.context import CryptContext
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    def hash_password(password: str) -> str:
        return pwd_ctx.hash(password)
    def verify_password(password: str, hashed: str) -> bool:
        return pwd_ctx.verify(password, hashed)
except ImportError:
    # passlib 없으면 sha256 + salt fallback
    import secrets
    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"sha256${salt}${h}"
    def verify_password(password: str, hashed: str) -> bool:
        parts = hashed.split("$")
        if len(parts) == 3 and parts[0] == "sha256":
            salt, stored = parts[1], parts[2]
            h = hashlib.sha256((salt + password).encode()).hexdigest()
            return hmac.compare_digest(h, stored)
        # passlib bcrypt format - can't verify without passlib
        return False


# ── JWT (python-jose 없으면 수동 구현) ────────
try:
    from jose import jwt as jose_jwt
    def create_token(data: dict) -> str:
        payload = data.copy()
        payload["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
        return jose_jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    def decode_token(token: str) -> Optional[dict]:
        try:
            return jose_jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except Exception:
            return None
except ImportError:
    # 수동 JWT 구현 (HS256)
    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    def _b64url_decode(s: str) -> bytes:
        s += "=" * (4 - len(s) % 4)
        return base64.urlsafe_b64decode(s)

    def create_token(data: dict) -> str:
        header = _b64url_encode(json.dumps({"alg":"HS256","typ":"JWT"}).encode())
        payload_data = data.copy()
        payload_data["exp"] = int((datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)).timestamp())
        payload = _b64url_encode(json.dumps(payload_data).encode())
        sig_input = f"{header}.{payload}".encode()
        sig = _b64url_encode(hmac.new(SECRET_KEY.encode(), sig_input, hashlib.sha256).digest())
        return f"{header}.{payload}.{sig}"

    def decode_token(token: str) -> Optional[dict]:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            sig_input = f"{parts[0]}.{parts[1]}".encode()
            expected_sig = _b64url_encode(hmac.new(SECRET_KEY.encode(), sig_input, hashlib.sha256).digest())
            if not hmac.compare_digest(parts[2], expected_sig):
                return None
            payload = json.loads(_b64url_decode(parts[1]))
            if payload.get("exp", 0) < datetime.utcnow().timestamp():
                return None
            return payload
        except Exception:
            return None
