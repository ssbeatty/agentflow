"""
Auth primitives — all stdlib, no extra dependencies.

  * Password hashing      : PBKDF2-HMAC-SHA256 (salted, encoded as a single string)
  * Admin session tokens  : compact HMAC-SHA256 signed `<payload>.<sig>` (JWT-ish)
  * API keys              : random `af_...` tokens, only the SHA-256 hash is stored

The signing secret comes from `settings.secret_key`; if unset, a random key is
generated once and persisted to `data/.secret_key` so issued tokens survive a
restart. Both backend (this module) and the deps layer (`app/auth_deps.py`)
import from here so the crypto lives in exactly one place.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from app.config import DEFAULT_DATA_DIR, settings

# ── signing secret ────────────────────────────────────────────────────────────

_SECRET_FILE = DEFAULT_DATA_DIR / ".secret_key"


def _load_secret() -> bytes:
    if settings.secret_key:
        return settings.secret_key.encode()
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _SECRET_FILE.exists():
        val = _SECRET_FILE.read_text(encoding="utf-8").strip()
        if val:
            return val.encode()
    val = secrets.token_hex(32)
    _SECRET_FILE.write_text(val, encoding="utf-8")
    try:
        os.chmod(_SECRET_FILE, 0o600)
    except OSError:
        pass  # best-effort on platforms that don't support it (e.g. Windows)
    return val.encode()


_SECRET = _load_secret()

# ── password hashing (PBKDF2) ─────────────────────────────────────────────────

_PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ── session tokens (HMAC-signed, stateless) ───────────────────────────────────

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload_b64: str) -> str:
    return _b64e(hmac.new(_SECRET, payload_b64.encode(), hashlib.sha256).digest())


def create_session_token(subject: str, ttl_hours: int | None = None) -> str:
    ttl = settings.session_ttl_hours if ttl_hours is None else ttl_hours
    now = int(time.time())
    payload = {"sub": subject, "iat": now, "exp": now + ttl * 3600}
    payload_b64 = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_session_token(token: str | None) -> dict | None:
    """Return the decoded payload if the token is valid and unexpired, else None."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(payload_b64)):
            return None
        payload = json.loads(_b64d(payload_b64))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except (ValueError, json.JSONDecodeError):
        return None


# ── API keys ──────────────────────────────────────────────────────────────────

API_KEY_PREFIX = "af"


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, display_prefix, sha256_hash). Store only the hash."""
    full = f"{API_KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    return full, full[:11], hash_api_key(full)


def hash_api_key(full: str) -> str:
    return hashlib.sha256(full.encode()).hexdigest()


def looks_like_api_key(value: str) -> bool:
    return value.startswith(f"{API_KEY_PREFIX}_")
