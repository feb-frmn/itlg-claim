"""Account configuration: validation, encryption, masking, import/export."""

import json
import os
import secrets
import time
import uuid
from pathlib import Path

from web import crypto, database

DATA_DIR = Path(os.environ.get("ITLG_DATA_DIR") or "/app/data")
LEGACY_CONFIG = Path(os.environ.get("ITLG_CONFIG_FILE") or "/app/config.json")

# Fields that must never be returned in plain text.
SECRET_FIELDS = ("passcode", "imapPassword", "tgBotToken")

# camelCase (API) <-> snake_case (DB)
FIELD_MAP = {
    "name": "name",
    "loginId": "login_id",
    "passcode": "passcode",
    "email": "email",
    "imapPassword": "imap_password",
    "facePhoto": "face_photo",
    "deviceId": "device_id",
    "deviceModel": "device_model",
    "deviceBrand": "device_brand",
    "tgBotToken": "tg_bot_token",
    "tgChatId": "tg_chat_id",
}

DEVICE_CHOICES = [
    ("Redmi Note 8 Pro", "XiaoMi"),
    ("Redmi Note 11", "XiaoMi"),
    ("SM-G991B", "samsung"),
    ("SM-A525F", "samsung"),
    ("Pixel 6", "Google"),
    ("Pixel 7", "Google"),
    ("CPH2247", "OPPO"),
    ("V2057A", "vivo"),
    ("RMX3081", "Realme"),
    ("M2101K6G", "POCO"),
]


def _public_field(db_key):
    for api_key, db_col in FIELD_MAP.items():
        if db_col == db_key:
            return api_key
    return db_key


def account_public(row: dict) -> dict:
    """Safe representation for API responses (secrets masked)."""
    out = {"id": row.get("id"), "enabled": bool(row.get("enabled", 1))}
    for api_key, db_col in FIELD_MAP.items():
        value = row.get(db_col)
        if api_key in SECRET_FIELDS:
            out[api_key] = crypto.mask(value)
        else:
            out[api_key] = value or ""
    return out


def account_to_cfg(row: dict) -> dict:
    """Decrypt a DB row into the ``cfg`` dict expected by bot.py functions."""
    cfg = {}
    for api_key, db_col in FIELD_MAP.items():
        value = row.get(db_col)
        if api_key in SECRET_FIELDS:
            value = crypto.decrypt(value)
        cfg[api_key] = value or ""
    cfg["id"] = row.get("id")
    cfg["enabled"] = bool(row.get("enabled", 1))
    # Device defaults expected by bot.headers()
    if not cfg.get("deviceModel"):
        cfg["deviceModel"] = "Redmi Note 8 Pro"
    if not cfg.get("deviceBrand"):
        cfg["deviceBrand"] = "XiaoMi"
    return cfg


def validate_payload(payload: dict, partial: bool = False) -> dict:
    """Validate and normalise an account payload (camelCase in, camelCase out)."""
    errors = []
    data = {}

    def get(key):
        v = payload.get(key)
        return v.strip() if isinstance(v, str) else v

    name = get("name")
    if not partial or "name" in payload:
        if not name:
            errors.append("Nama akun wajib diisi")
        data["name"] = name or ""

    login_id = get("loginId")
    if not partial or "loginId" in payload:
        if not login_id:
            errors.append("Login ID wajib diisi")
        data["loginId"] = str(login_id or "")

    passcode = get("passcode")
    if not partial:
        if not passcode:
            errors.append("Passcode wajib diisi")
        data["passcode"] = str(passcode or "")
    elif "passcode" in payload and passcode:
        # Partial update: empty means "keep the existing secret".
        data["passcode"] = str(passcode)

    email = get("email")
    if not partial or "email" in payload:
        data["email"] = email or ""
        if email and "@" not in email:
            errors.append("Format email tidak valid")

    imap = get("imapPassword")
    if not partial or "imapPassword" in payload:
        data["imapPassword"] = imap or ""

    for key in ("facePhoto", "deviceId", "deviceModel", "deviceBrand", "tgChatId"):
        if key in payload:
            data[key] = get(key) or ""

    if "tgBotToken" in payload:
        data["tgBotToken"] = get("tgBotToken") or ""

    if errors:
        raise ValueError("; ".join(errors))
    return data


def _encrypt_secrets(data: dict) -> dict:
    out = dict(data)
    for key in SECRET_FIELDS:
        if key in out and out[key]:
            out[key] = crypto.encrypt(out[key])
    return out


def prepare_create(payload: dict) -> dict:
    data = validate_payload(payload, partial=False)
    now = int(time.time())
    account_id = uuid.uuid4().hex[:12]

    device_id = data.get("deviceId") or secrets.token_hex(8)
    model = data.get("deviceModel")
    brand = data.get("deviceBrand")
    if not model or not brand:
        model, brand = DEVICE_CHOICES[secrets.randbelow(len(DEVICE_CHOICES))]

    db_data = {
        "id": account_id,
        "name": data.get("name") or "Akun",
        "login_id": data.get("loginId") or "",
        "passcode": crypto.encrypt(data.get("passcode") or ""),
        "email": data.get("email") or "",
        "imap_password": crypto.encrypt(data.get("imapPassword") or ""),
        "face_photo": data.get("facePhoto") or "",
        "device_id": device_id,
        "device_model": model,
        "device_brand": brand,
        "tg_bot_token": crypto.encrypt(data.get("tgBotToken") or ""),
        "tg_chat_id": data.get("tgChatId") or "",
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    return db_data


def prepare_update(row: dict, payload: dict) -> dict:
    """Merge a partial payload into an existing DB row."""
    data = validate_payload(payload, partial=True)
    # Jangan hapus device ID bila dikirim kosong (dipakai API Interlink).
    if not data.get("deviceId"):
        data.pop("deviceId", None)
    out = {}
    for api_key, value in data.items():
        db_col = FIELD_MAP.get(api_key)
        if not db_col:
            continue
        if api_key in SECRET_FIELDS:
            # Keep the existing secret when the client sends the masked value.
            if not value or set(value) <= {"•"}:
                existing = crypto.decrypt(row.get(db_col))
                out[db_col] = crypto.encrypt(existing) if existing else ""
            else:
                out[db_col] = crypto.encrypt(value)
        else:
            out[db_col] = value
    return out


def import_from_config_json():
    """On first run, import the legacy config.json as the initial account."""
    if database.count_accounts() > 0:
        return False
    if not LEGACY_CONFIG.exists():
        return False
    try:
        with open(LEGACY_CONFIG) as f:
            cfg = json.load(f)
    except Exception:
        return False
    if not cfg.get("loginId"):
        return False

    now = int(time.time())
    device_id = cfg.get("deviceId") or secrets.token_hex(8)
    model = cfg.get("deviceModel")
    brand = cfg.get("deviceBrand")
    if not model or not brand:
        model, brand = DEVICE_CHOICES[secrets.randbelow(len(DEVICE_CHOICES))]

    account_id = uuid.uuid4().hex[:12]
    database.create_account(
        {
            "id": account_id,
            "name": cfg.get("name") or "Akun Utama",
            "login_id": str(cfg.get("loginId") or ""),
            "passcode": crypto.encrypt(cfg.get("passcode") or ""),
            "email": cfg.get("email") or "",
            "imap_password": crypto.encrypt(cfg.get("imapPassword") or ""),
            "face_photo": cfg.get("facePhoto") or "",
            "device_id": device_id,
            "device_model": model,
            "device_brand": brand,
            "tg_bot_token": crypto.encrypt(cfg.get("tgBotToken") or ""),
            "tg_chat_id": str(cfg.get("tgChatId") or ""),
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
    )

    # Bring the legacy token along so the imported account keeps working.
    import shutil

    tokens_dir = DATA_DIR / "tokens"
    tokens_dir.mkdir(parents=True, exist_ok=True)
    token_src = LEGACY_CONFIG.parent / "token.json"
    if token_src.exists():
        try:
            shutil.copy2(token_src, tokens_dir / f"{account_id}.json")
        except Exception:
            pass
    backup_src = LEGACY_CONFIG.parent / "token-backup.json"
    if backup_src.exists():
        try:
            shutil.copy2(backup_src, tokens_dir / f"{account_id}.backup.json")
        except Exception:
            pass

    return True
