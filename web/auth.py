"""UserGate client, session handling, rate limiting and auth dependencies."""

import os
import secrets
import threading
import time

import requests
from fastapi import HTTPException, Request

from web import crypto, database

DEFAULT_BASE_URL = "https://usergate.sandalgurun.web.id/api/v1"

AUTH_MODE_AUTO = "auto"
AUTH_MODE_USERGATE = "usergate"
AUTH_MODE_NONE = "none"
AUTH_MODES = (AUTH_MODE_AUTO, AUTH_MODE_USERGATE, AUTH_MODE_NONE)
DEFAULT_AUTH_MODE = AUTH_MODE_AUTO

# In-memory login rate limiter: ip -> list of timestamps.
_login_attempts = {}
_login_lock = threading.Lock()


class UserGateError(Exception):
    pass


def get_api_key() -> str:
    env_key = (os.environ.get("USERGATE_API_KEY") or "").strip()
    if env_key:
        return env_key
    stored = database.get_setting("usergate_api_key", "") or ""
    if not stored:
        return ""
    # Keys saved from the UI are encrypted. Plain-text values written by older
    # versions are still accepted as-is.
    if stored.startswith("gAAAA"):
        return (crypto.decrypt(stored) or "").strip()
    return stored.strip()


def env_auth_mode() -> str:
    return (os.environ.get("AUTH_MODE") or "").strip().lower()


def get_auth_mode_setting() -> str:
    """Configured mode: environment overrides the value stored in settings."""
    mode = env_auth_mode() or (database.get_setting("auth_mode", DEFAULT_AUTH_MODE) or "")
    mode = str(mode).strip().lower()
    return mode if mode in AUTH_MODES else DEFAULT_AUTH_MODE


def usergate_configured() -> bool:
    """True when a key is present, even if it later turns out to be unusable.

    Auto mode must fail closed: a corrupt/undecryptable stored key should keep
    login required instead of silently opening the dashboard.
    """
    if (os.environ.get("USERGATE_API_KEY") or "").strip():
        return True
    return bool((database.get_setting("usergate_api_key", "") or "").strip())


def get_auth_mode() -> str:
    """Effective mode: ``auto`` means UserGate when a key exists, otherwise none."""
    mode = get_auth_mode_setting()
    if mode == AUTH_MODE_AUTO:
        return AUTH_MODE_USERGATE if usergate_configured() else AUTH_MODE_NONE
    return mode


def auth_required() -> bool:
    return get_auth_mode() != AUTH_MODE_NONE


def local_admin() -> dict:
    """Virtual admin used when login is disabled."""
    return {
        "id": 1,
        "admin_id": 1,
        "username": "local",
        "email": "",
        "full_name": "Akses Lokal",
        "usergate_id": None,
        "roles": "",
        "created_at": None,
        "last_login_at": None,
        "local": True,
        "auth_mode": AUTH_MODE_NONE,
    }


def auth_status() -> dict:
    mode = get_auth_mode()
    return {
        "admin_exists": database.get_admin() is not None,
        "auth_mode": mode,
        "auth_mode_setting": get_auth_mode_setting(),
        "env_auth_mode": env_auth_mode(),
        "login_required": mode != AUTH_MODE_NONE,
        "usergate_configured": usergate_configured(),
    }


def get_base_url() -> str:
    value = (
        os.environ.get("USERGATE_BASE_URL")
        or database.get_setting("usergate_base_url", DEFAULT_BASE_URL)
        or DEFAULT_BASE_URL
    )
    return value.rstrip("/")


def cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def usergate_login(username: str, password: str) -> dict:
    """Call UserGate /auth/login and return the data payload."""
    api_key = get_api_key()
    if not api_key:
        raise UserGateError(
            "API key UserGate belum dikonfigurasi atau tidak dapat dibaca. "
            "Set USERGATE_API_KEY atau isi ulang lewat halaman Pengaturan."
        )

    base = get_base_url()
    try:
        resp = requests.post(
            f"{base}/auth/login",
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            json={"username": username, "password": password},
            timeout=20,
        )
    except requests.RequestException as e:
        raise UserGateError(f"Tidak dapat terhubung ke UserGate: {e}")

    try:
        payload = resp.json()
    except Exception:
        raise UserGateError(f"Respons UserGate tidak valid (HTTP {resp.status_code})")

    if resp.status_code == 200 and payload.get("status") is True:
        return payload.get("data") or {}

    message = payload.get("message") or f"HTTP {resp.status_code}"
    raise UserGateError(message)


def public_admin() -> dict:
    mode = get_auth_mode()
    if mode == AUTH_MODE_NONE:
        admin = local_admin()
        return {
            "username": admin["username"],
            "email": admin["email"],
            "full_name": admin["full_name"],
            "usergate_id": None,
            "created_at": None,
            "last_login_at": None,
            "local": True,
            "auth_mode": mode,
        }

    admin = database.get_admin()
    if not admin:
        return None
    return {
        "username": admin.get("username"),
        "email": admin.get("email"),
        "full_name": admin.get("full_name"),
        "usergate_id": admin.get("usergate_id"),
        "created_at": admin.get("created_at"),
        "last_login_at": admin.get("last_login_at"),
        "local": False,
        "auth_mode": mode,
    }


# ─── Sessions ─────────────────────────────────────────────────────────────────

def create_session(admin_id: int, ip: str, user_agent: str, remember: bool = False):
    token = secrets.token_urlsafe(32)
    try:
        timeout = int(database.get_setting("session_timeout", "43200"))
    except (TypeError, ValueError):
        timeout = 43200
    if remember:
        timeout = 30 * 24 * 3600
    now = int(time.time())
    expires_at = now + max(300, timeout)
    database.create_session(token, admin_id, expires_at, ip, user_agent)
    return token, expires_at


def get_current_admin(request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    row = database.get_session(token)
    if not row:
        return None
    if row.get("expires_at", 0) < time.time():
        database.delete_session(token)
        return None
    return row


def require_admin(request: Request):
    if not auth_required():
        return local_admin()
    admin = get_current_admin(request)
    if not admin:
        raise HTTPException(status_code=401, detail="Autentikasi diperlukan")
    # Normalise: handlers use admin["id"] for the audit log.
    admin["id"] = admin.get("admin_id")
    return admin


def check_rate_limit(ip: str, max_attempts: int = 5, window: int = 300):
    now = time.time()
    with _login_lock:
        attempts = [t for t in _login_attempts.get(ip, []) if now - t < window]
        if len(attempts) >= max_attempts:
            _login_attempts[ip] = attempts
            raise HTTPException(
                status_code=429,
                detail="Terlalu banyak percobaan login. Coba lagi dalam 5 menit.",
            )
        attempts.append(now)
        _login_attempts[ip] = attempts


def validate_csrf(request: Request):
    cookie = request.cookies.get("csrf", "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="CSRF token tidak valid")
