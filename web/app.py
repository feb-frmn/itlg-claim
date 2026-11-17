"""FastAPI application: REST API + static SPA for the ITLG Claim dashboard."""

import os
import re
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from web import auth, config_manager, crypto, database, system
from web import engine as engine_module
from web.engine import LOGS_DIR, STATE_DIR, TOKENS_DIR, UPLOADS_DIR, Engine

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

engine = Engine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine_module.ensure_dirs()
    database.init_db()
    config_manager.import_from_config_json()
    engine.sync_accounts()
    engine.start()
    yield
    engine.stop_all()


app = FastAPI(title="ITLG Claim", version="3.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_account_or_404(account_id: str):
    row = database.get_account(account_id)
    if not row:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    return row


def filter_lines(raw_lines, level: str, query: str, limit: int):
    out = []
    for line in reversed(raw_lines):
        low = line.lower()
        if level and level not in low:
            continue
        if query and query not in low:
            continue
        out.append(line.rstrip("\n"))
        if len(out) >= limit:
            break
    out.reverse()
    return out


# ─── Middleware (CSRF) ────────────────────────────────────────────────────────

@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path.startswith("/api"):
        if request.url.path == "/api/auth/login":
            return await call_next(request)
        cookie = request.cookies.get("csrf", "")
        header = request.headers.get("x-csrf-token", "")
        if not cookie or not header or not secrets.compare_digest(cookie, header):
            return JSONResponse({"detail": "CSRF token tidak valid"}, status_code=403)
    return await call_next(request)


# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.get("/api/auth/status")
async def auth_status():
    return auth.auth_status()


@app.post("/api/auth/login")
async def login(request: Request, payload: dict):
    if not auth.auth_required():
        raise HTTPException(
            status_code=400,
            detail="Mode tanpa login aktif. Login UserGate tidak diperlukan.",
        )

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username dan password wajib diisi")

    auth.check_rate_limit(client_ip(request))

    try:
        data = auth.usergate_login(username, password)
    except auth.UserGateError as e:
        database.add_audit(None, "login_failed", f"{username}: {e}", client_ip(request))
        raise HTTPException(status_code=401, detail=str(e))

    user = data.get("user") or {}
    usergate_id = str(user.get("id") or "")
    ug_username = user.get("username") or username

    admin = database.get_admin()
    created = False
    if admin is None:
        try:
            database.create_admin(user)
            created = True
            admin = database.get_admin()
        except Exception:
            # Race: request lain sudah membuat admin lebih dulu.
            admin = database.get_admin()

    if admin is None:
        raise HTTPException(status_code=500, detail="Gagal membuat administrator")

    same_user = (usergate_id and str(admin.get("usergate_id")) == usergate_id) or (
        admin.get("username") == ug_username
    )
    if not same_user:
        database.add_audit(
            admin["id"], "login_denied", f"UserGate: {ug_username}", client_ip(request)
        )
        raise HTTPException(
            status_code=403,
            detail="Hanya administrator yang dapat mengakses instance ini.",
        )

    if created:
        database.add_audit(1, "admin_created", f"Admin awal: {ug_username}", client_ip(request))
    else:
        database.add_audit(admin["id"], "login_success", f"Admin: {ug_username}", client_ip(request))
    database.update_admin_last_login()

    token, expires_at = auth.create_session(
        1, client_ip(request), request.headers.get("user-agent", ""), payload.get("remember", False)
    )
    database.add_audit(1, "login_success", f"Admin: {ug_username}", client_ip(request))

    csrf_token = secrets.token_urlsafe(32)
    response = JSONResponse({"ok": True, "admin": auth.public_admin()})
    response.set_cookie(
        "session", token, expires=expires_at, httponly=True,
        samesite="lax", secure=auth.cookie_secure(), path="/",
    )
    response.set_cookie(
        "csrf", csrf_token, expires=expires_at, httponly=False,
        samesite="lax", secure=auth.cookie_secure(), path="/",
    )
    return response


@app.post("/api/auth/logout")
async def logout(request: Request, admin=Depends(auth.require_admin)):
    token = request.cookies.get("session")
    if token:
        database.delete_session(token)
    database.add_audit(admin["id"], "logout", "", client_ip(request))
    response = JSONResponse({"ok": True})
    response.delete_cookie("session", path="/")
    response.delete_cookie("csrf", path="/")
    return response


@app.get("/api/auth/me")
async def me(request: Request, response: Response, admin=Depends(auth.require_admin)):
    if not request.cookies.get("csrf"):
        csrf_token = secrets.token_urlsafe(32)
        response.set_cookie(
            "csrf", csrf_token, max_age=30 * 24 * 3600, httponly=False,
            samesite="lax", secure=auth.cookie_secure(), path="/",
        )
    accounts = database.list_accounts()
    return {
        "admin": auth.public_admin(),
        "accounts_count": len(accounts),
        "setup_complete": len(accounts) > 0,
        "auth_mode": auth.get_auth_mode(),
        "login_required": auth.auth_required(),
    }


# ─── Accounts CRUD ────────────────────────────────────────────────────────────

@app.get("/api/accounts")
async def list_accounts(admin=Depends(auth.require_admin)):
    result = []
    for row in database.list_accounts():
        pub = config_manager.account_public(row)
        runner = engine.get_runner(row["id"])
        if runner:
            detail = runner.get_status()
            if detail:
                keys = (
                    "status", "status_message", "last_error", "uptime", "last_claim",
                    "next_mining_at", "next_group_at", "token_valid", "balance",
                    "username", "mining", "group", "recovery", "rates", "referrals",
                    "streak", "burned", "history", "loginId",
                )
                pub.update({k: detail[k] for k in keys if k in detail})
            else:
                pub.update(runner.public_status())
        result.append(pub)
    return {"accounts": result}


@app.post("/api/accounts")
async def create_account(request: Request, payload: dict, admin=Depends(auth.require_admin)):
    try:
        data = config_manager.prepare_create(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    database.create_account(data)
    engine.on_account_created(data["id"])
    database.add_audit(admin["id"], "account_created", data.get("name") or "", client_ip(request))
    return {"ok": True, "id": data["id"]}


@app.get("/api/accounts/{account_id}")
async def get_account(account_id: str, admin=Depends(auth.require_admin)):
    row = get_account_or_404(account_id)
    pub = config_manager.account_public(row)
    runner = engine.get_runner(account_id)
    if runner:
        pub.update(runner.public_status())
    return pub


@app.put("/api/accounts/{account_id}")
async def update_account(
    account_id: str, request: Request, payload: dict, admin=Depends(auth.require_admin)
):
    row = get_account_or_404(account_id)
    try:
        data = config_manager.prepare_update(row, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    database.update_account(account_id, data)
    if "enabled" in payload:
        database.set_account_enabled(account_id, bool(payload["enabled"]))
    engine.sync_accounts()
    database.add_audit(admin["id"], "account_updated", row.get("name") or "", client_ip(request))
    return {"ok": True}


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, request: Request, admin=Depends(auth.require_admin)):
    row = get_account_or_404(account_id)
    runner = engine.get_runner(account_id)
    if runner:
        runner.stop()
    database.delete_account(account_id)
    engine.sync_accounts()

    for path in (
        TOKENS_DIR / f"{account_id}.json",
        TOKENS_DIR / f"{account_id}.backup.json",
        STATE_DIR / f"{account_id}.json",
        LOGS_DIR / f"{account_id}.log",
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    shutil.rmtree(UPLOADS_DIR / account_id, ignore_errors=True)

    database.add_audit(admin["id"], "account_deleted", row.get("name") or "", client_ip(request))
    return {"ok": True}


@app.post("/api/accounts/{account_id}/enable")
async def enable_account(
    account_id: str, request: Request, payload: dict, admin=Depends(auth.require_admin)
):
    get_account_or_404(account_id)
    enabled = bool(payload.get("enabled", True))
    database.set_account_enabled(account_id, enabled)
    engine.sync_accounts()
    if not enabled:
        engine.stop_account(account_id)
    database.add_audit(
        admin["id"], "account_enabled" if enabled else "account_disabled",
        account_id, client_ip(request),
    )
    return {"ok": True}


@app.post("/api/accounts/{account_id}/test")
async def test_account(account_id: str, admin=Depends(auth.require_admin)):
    import bot

    runner = engine.get_runner(account_id)
    if not runner:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    cfg = runner.get_cfg()
    if not cfg:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")

    def _test(cfg):
        out = {}
        try:
            out["login_id_valid"] = bool(bot.check_login_id(cfg))
        except Exception as e:
            out["login_id_error"] = str(e)
        try:
            email = bot.check_passcode(cfg)
            out["passcode_valid"] = bool(email)
            out["email"] = email
        except Exception as e:
            out["passcode_error"] = str(e)
        return out

    return runner._with_context(_test, cfg)


# ─── Account actions ──────────────────────────────────────────────────────────

def _runner_or_404(account_id: str):
    runner = engine.get_runner(account_id)
    if not runner:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    return runner


@app.post("/api/accounts/{account_id}/start")
async def start_account(account_id: str, request: Request, admin=Depends(auth.require_admin)):
    runner = _runner_or_404(account_id)
    ok = runner.start()
    database.add_audit(admin["id"], "account_start", account_id, client_ip(request))
    return {"ok": ok, "status": runner.status}


@app.post("/api/accounts/{account_id}/stop")
async def stop_account(account_id: str, request: Request, admin=Depends(auth.require_admin)):
    runner = _runner_or_404(account_id)
    runner.stop()
    database.add_audit(admin["id"], "account_stop", account_id, client_ip(request))
    return {"ok": True, "status": runner.status}


@app.post("/api/accounts/{account_id}/restart")
async def restart_account(account_id: str, request: Request, admin=Depends(auth.require_admin)):
    runner = _runner_or_404(account_id)
    ok = runner.restart()
    database.add_audit(admin["id"], "account_restart", account_id, client_ip(request))
    return {"ok": ok, "status": runner.status}


@app.post("/api/accounts/{account_id}/claim")
async def force_claim(account_id: str, request: Request, admin=Depends(auth.require_admin)):
    runner = _runner_or_404(account_id)
    runner.force_claim.set()
    database.add_audit(admin["id"], "account_claim", account_id, client_ip(request))
    return {"ok": True, "message": "Klaim mining dijadwalkan."}


@app.post("/api/accounts/{account_id}/group")
async def force_group(account_id: str, request: Request, admin=Depends(auth.require_admin)):
    runner = _runner_or_404(account_id)
    runner.force_group.set()
    database.add_audit(admin["id"], "account_group", account_id, client_ip(request))
    return {"ok": True, "message": "Klaim group dijadwalkan."}


@app.post("/api/accounts/{account_id}/recovery")
async def force_recovery(account_id: str, request: Request, admin=Depends(auth.require_admin)):
    runner = _runner_or_404(account_id)
    runner.force_recovery.set()
    database.add_audit(admin["id"], "account_recovery", account_id, client_ip(request))
    return {"ok": True, "message": "Recovery dijadwalkan."}


@app.post("/api/actions/start_all")
async def start_all(request: Request, admin=Depends(auth.require_admin)):
    engine.sync_accounts()
    for account_id in list(engine.runners):
        engine.start_account(account_id)
    database.add_audit(admin["id"], "start_all", "", client_ip(request))
    return {"ok": True}


@app.post("/api/actions/stop_all")
async def stop_all(request: Request, admin=Depends(auth.require_admin)):
    engine.stop_all()
    database.add_audit(admin["id"], "stop_all", "", client_ip(request))
    return {"ok": True}


@app.post("/api/actions/restart_all")
async def restart_all(request: Request, admin=Depends(auth.require_admin)):
    engine.restart_all()
    database.add_audit(admin["id"], "restart_all", "", client_ip(request))
    return {"ok": True}


# ─── Login (OTP / face) ───────────────────────────────────────────────────────

@app.post("/api/accounts/{account_id}/login/otp/request")
async def otp_request(account_id: str, request: Request, admin=Depends(auth.require_admin)):
    try:
        pending = engine.login_manager.request_otp(account_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    database.add_audit(admin["id"], "otp_request", account_id, client_ip(request))
    return pending


@app.get("/api/accounts/{account_id}/login/otp/status")
async def otp_status(account_id: str, admin=Depends(auth.require_admin)):
    return engine.login_manager._get_pending(account_id) or {"status": "none"}


@app.post("/api/accounts/{account_id}/login/otp/verify")
async def otp_verify(
    account_id: str, request: Request, payload: dict, admin=Depends(auth.require_admin)
):
    code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Kode OTP wajib diisi")
    try:
        ok, message = engine.login_manager.verify_otp(account_id, code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    database.add_audit(admin["id"], "otp_verify", account_id, client_ip(request))
    return {"ok": ok, "message": message}


@app.post("/api/accounts/{account_id}/login/face")
async def face_login(
    account_id: str, request: Request, file: UploadFile = File(...),
    admin=Depends(auth.require_admin),
):
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File harus berupa gambar")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        ext = ".jpg"

    directory = UPLOADS_DIR / account_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"login-{int(time.time())}{ext}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    os.chmod(path, 0o600)

    try:
        ok, message = engine.login_manager.login_face(account_id, str(path))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            path.unlink()
        except Exception:
            pass

    database.add_audit(admin["id"], "face_login", account_id, client_ip(request))
    return {"ok": ok, "message": message}


@app.post("/api/accounts/{account_id}/face-photo")
async def upload_face_photo(
    account_id: str, file: UploadFile = File(...), admin=Depends(auth.require_admin)
):
    get_account_or_404(account_id)
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File harus berupa gambar")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        ext = ".jpg"

    directory = UPLOADS_DIR / account_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"selfie{ext}"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    os.chmod(path, 0o600)

    database.update_account(account_id, {"face_photo": str(path)})
    engine.sync_accounts()
    return {"ok": True, "path": str(path)}


# ─── Status / logs / system ───────────────────────────────────────────────────

@app.get("/api/status")
async def global_status(admin=Depends(auth.require_admin)):
    return engine.global_status()


@app.get("/api/accounts/{account_id}/status")
async def account_status(account_id: str, admin=Depends(auth.require_admin)):
    runner = _runner_or_404(account_id)
    data = runner.get_status()
    if data is None:
        raise HTTPException(status_code=404, detail="Akun tidak ditemukan")
    return data


@app.get("/api/logs")
async def logs(request: Request, admin=Depends(auth.require_admin)):
    account_id = request.query_params.get("account_id", "").strip()
    try:
        lines = min(int(request.query_params.get("lines", "200")), 2000)
    except ValueError:
        lines = 200
    level = request.query_params.get("level", "").strip().lower()
    query = request.query_params.get("q", "").strip().lower()

    if account_id:
        path = LOGS_DIR / f"{account_id}.log"
        if not path.exists():
            return {"lines": [], "account_id": account_id}
        with open(path, "r", errors="ignore") as f:
            raw = f.readlines()
        return {"lines": filter_lines(raw, level, query, lines), "account_id": account_id}

    merged = []
    for path in sorted(LOGS_DIR.glob("*.log")):
        try:
            with open(path, "r", errors="ignore") as f:
                for line in f:
                    merged.append(line)
        except Exception:
            continue

    def ts_key(line):
        m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
        return m.group(1) if m else ""

    merged.sort(key=ts_key)
    return {"lines": filter_lines(merged, level, query, lines), "account_id": ""}


@app.get("/api/system")
async def system_metrics(admin=Depends(auth.require_admin)):
    return system.metrics()


@app.get("/api/audit")
async def audit(request: Request, admin=Depends(auth.require_admin)):
    try:
        limit = min(int(request.query_params.get("limit", "100")), 500)
    except ValueError:
        limit = 100
    return {"audit": database.list_audit(limit)}


# ─── Settings ─────────────────────────────────────────────────────────────────

@app.get("/api/settings")
async def get_settings(admin=Depends(auth.require_admin)):
    try:
        session_timeout = int(database.get_setting("session_timeout", "43200"))
    except (TypeError, ValueError):
        session_timeout = 43200
    return {
        "usergate_api_key": crypto.mask(database.get_setting("usergate_api_key", "")),
        "usergate_api_key_set": auth.usergate_configured(),
        "env_api_key_set": bool(os.environ.get("USERGATE_API_KEY")),
        "usergate_base_url": auth.get_base_url(),
        "auth_mode": auth.get_auth_mode(),
        "auth_mode_setting": auth.get_auth_mode_setting(),
        "env_auth_mode": auth.env_auth_mode(),
        "login_required": auth.auth_required(),
        "usergate_configured": auth.usergate_configured(),
        "autostart": database.get_setting("autostart", "true"),
        "session_timeout": session_timeout,
        "cookie_secure": auth.cookie_secure(),
        "version": "3.0.0",
    }


@app.put("/api/settings")
async def update_settings(request: Request, payload: dict, admin=Depends(auth.require_admin)):
    if "auth_mode" in payload:
        if auth.env_auth_mode():
            raise HTTPException(
                status_code=400,
                detail="Mode autentikasi diatur lewat environment AUTH_MODE.",
            )
        mode = str(payload.get("auth_mode") or "").strip().lower()
        if mode not in auth.AUTH_MODES:
            raise HTTPException(status_code=400, detail="Mode autentikasi tidak valid")
        if mode == auth.AUTH_MODE_USERGATE:
            # Validate against the key that will exist after this request.
            projected_key = auth.usergate_configured()
            if "usergate_api_key" in payload:
                new_key = payload.get("usergate_api_key")
                if new_key is not None:
                    new_key = str(new_key).strip()
                    if new_key == "":
                        projected_key = bool(
                            (os.environ.get("USERGATE_API_KEY") or "").strip()
                        )
                    elif set(new_key) != {"•"}:
                        projected_key = True
            if not projected_key:
                raise HTTPException(
                    status_code=400,
                    detail="API key UserGate wajib diisi untuk mode usergate.",
                )
        database.set_setting("auth_mode", mode)
        database.add_audit(admin["id"], "auth_mode_changed", mode, client_ip(request))
    if "usergate_api_key" in payload:
        value = payload.get("usergate_api_key")
        if value is not None:
            value = str(value).strip()
            if value == "":
                # Allow removing the key so auto mode can fall back to no login.
                database.set_setting("usergate_api_key", "")
            elif set(value) != {"•"}:
                database.set_setting("usergate_api_key", crypto.encrypt(value))
    if "usergate_base_url" in payload:
        database.set_setting(
            "usergate_base_url", str(payload.get("usergate_base_url") or "").rstrip("/")
        )
    if "autostart" in payload:
        value = payload.get("autostart")
        if isinstance(value, str):
            autostart = value.strip().lower() in ("1", "true", "yes", "on")
        else:
            autostart = bool(value)
        database.set_setting("autostart", "true" if autostart else "false")
    if "session_timeout" in payload:
        try:
            database.set_setting("session_timeout", str(int(payload.get("session_timeout"))))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Session timeout tidak valid")
    database.add_audit(admin["id"], "settings_updated", "", client_ip(request))
    return {
        "ok": True,
        "auth_mode": auth.get_auth_mode(),
        "login_required": auth.auth_required(),
    }


# ─── Health / static ──────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"ok": True, "time": int(time.time())}


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")
