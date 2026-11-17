"""SQLite persistence: admin, sessions, settings, accounts, audit log."""

import os
import sqlite3
import threading
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("ITLG_DATA_DIR") or "/app/data")
DB_PATH = DATA_DIR / "app.db"

_lock = threading.RLock()


def _conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS admin (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    usergate_id   TEXT,
    username      TEXT,
    email         TEXT,
    full_name     TEXT,
    roles         TEXT,
    snapshot      TEXT,
    created_at    INTEGER,
    last_login_at INTEGER
);

CREATE TABLE IF NOT EXISTS session (
    token      TEXT PRIMARY KEY,
    admin_id   INTEGER,
    created_at INTEGER,
    expires_at INTEGER,
    ip         TEXT,
    user_agent TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    login_id      TEXT,
    passcode      TEXT,
    email         TEXT,
    imap_password TEXT,
    face_photo    TEXT,
    device_id     TEXT,
    device_model  TEXT,
    device_brand  TEXT,
    tg_bot_token  TEXT,
    tg_chat_id    TEXT,
    enabled       INTEGER DEFAULT 1,
    created_at    INTEGER,
    updated_at    INTEGER
);

CREATE TABLE IF NOT EXISTS audit (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      INTEGER,
    admin_id INTEGER,
    action  TEXT,
    detail  TEXT,
    ip      TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts DESC);
CREATE INDEX IF NOT EXISTS idx_session_expires ON session(expires_at);
"""


def init_db():
    with _lock, _conn() as conn:
        conn.executescript(SCHEMA)


# ─── Admin ────────────────────────────────────────────────────────────────────

def get_admin():
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM admin WHERE id = 1").fetchone()
        return dict(row) if row else None


def create_admin(user: dict):
    now = int(time.time())
    roles = user.get("roles")
    if isinstance(roles, list):
        roles = ",".join(str(r) for r in roles)
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO admin
               (id, usergate_id, username, email, full_name, roles, snapshot, created_at, last_login_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(user.get("id") or ""),
                user.get("username") or "",
                user.get("email") or "",
                user.get("full_name") or "",
                roles or "",
                __import__("json").dumps(user),
                now,
                now,
            ),
        )
        conn.commit()


def update_admin_last_login():
    with _lock, _conn() as conn:
        conn.execute("UPDATE admin SET last_login_at = ? WHERE id = 1", (int(time.time()),))
        conn.commit()


# ─── Sessions ─────────────────────────────────────────────────────────────────

def create_session(token, admin_id, expires_at, ip, user_agent):
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO session (token, admin_id, created_at, expires_at, ip, user_agent)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token, admin_id, int(time.time()), int(expires_at), ip, user_agent[:200] if user_agent else ""),
        )
        conn.commit()


def get_session(token):
    with _lock, _conn() as conn:
        row = conn.execute(
            """SELECT s.*, a.username AS admin_username, a.email AS admin_email,
                      a.full_name AS admin_full_name, a.usergate_id AS admin_usergate_id
               FROM session s LEFT JOIN admin a ON a.id = s.admin_id
               WHERE s.token = ?""",
            (token,),
        ).fetchone()
        return dict(row) if row else None


def delete_session(token):
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM session WHERE token = ?", (token,))
        conn.commit()


def delete_expired_sessions():
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM session WHERE expires_at < ?", (int(time.time()),))
        conn.commit()


# ─── Settings ─────────────────────────────────────────────────────────────────

def get_setting(key, default=None):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()


# ─── Accounts ─────────────────────────────────────────────────────────────────

def list_accounts():
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]


def get_account(account_id):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None


def count_accounts():
    with _lock, _conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]


def create_account(data: dict):
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO accounts
               (id, name, login_id, passcode, email, imap_password, face_photo,
                device_id, device_model, device_brand, tg_bot_token, tg_chat_id,
                enabled, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["id"], data.get("name") or "", data.get("login_id") or "",
                data.get("passcode") or "", data.get("email") or "",
                data.get("imap_password") or "", data.get("face_photo") or "",
                data.get("device_id") or "", data.get("device_model") or "",
                data.get("device_brand") or "", data.get("tg_bot_token") or "",
                data.get("tg_chat_id") or "", 1 if data.get("enabled", True) else 0,
                data.get("created_at") or int(time.time()),
                data.get("updated_at") or int(time.time()),
            ),
        )
        conn.commit()


def update_account(account_id, data: dict):
    fields = [k for k in data if k != "id"]
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    values = [data[k] for k in fields]
    values.append(int(time.time()))
    values.append(account_id)
    with _lock, _conn() as conn:
        conn.execute(
            f"UPDATE accounts SET {assignments}, updated_at = ? WHERE id = ?",
            values,
        )
        conn.commit()


def delete_account(account_id):
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()


def set_account_enabled(account_id, enabled: bool):
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE accounts SET enabled = ?, updated_at = ? WHERE id = ?",
            (1 if enabled else 0, int(time.time()), account_id),
        )
        conn.commit()


# ─── Audit ────────────────────────────────────────────────────────────────────

def add_audit(admin_id, action, detail="", ip=""):
    try:
        with _lock, _conn() as conn:
            conn.execute(
                "INSERT INTO audit (ts, admin_id, action, detail, ip) VALUES (?,?,?,?,?)",
                (int(time.time()), admin_id, action, str(detail)[:500], ip or ""),
            )
            conn.commit()
    except Exception:
        pass


def list_audit(limit=100):
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(r) for r in rows]
