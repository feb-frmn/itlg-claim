"""Encryption helpers for secrets stored in SQLite.

A Fernet key is derived from the SECRET_KEY environment variable when set,
otherwise a random key is generated once and stored in the data volume
(``/app/data/.secret``, chmod 600).
"""

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet

DATA_DIR = Path(os.environ.get("ITLG_DATA_DIR") or "/app/data")
SECRET_FILE = DATA_DIR / ".secret"

_fernet = None


def _get_key() -> bytes:
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        # Deterministic key from the environment secret.
        return base64.urlsafe_b64encode(hashlib.sha256(env_key.encode()).digest())

    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    SECRET_FILE.write_bytes(key)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except Exception:
        pass
    return key


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_get_key())
    return _fernet


def encrypt(value):
    """Encrypt a string. Empty/None values are stored as-is."""
    if value is None:
        return None
    if value == "":
        return ""
    return _f().encrypt(str(value).encode()).decode()


def decrypt(value):
    """Decrypt a string. Returns "" when the value cannot be decrypted."""
    if value is None:
        return None
    if value == "":
        return ""
    try:
        return _f().decrypt(str(value).encode()).decode()
    except Exception:
        return ""


def mask(value):
    """Mask a secret for API responses."""
    if not value:
        return ""
    return "•" * 8
