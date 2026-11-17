"""Multi-account claim engine.

Each enabled Interlink account runs in its own thread and has its own
token / claim-state / log files. The engine is intentionally decoupled from
the HTTP layer: API handlers only set events or read cached status.
"""

import os
import threading
import time
from pathlib import Path

import bot
from web import config_manager, database, system

DATA_DIR = Path(os.environ.get("ITLG_DATA_DIR") or "/app/data")
TOKENS_DIR = DATA_DIR / "tokens"
STATE_DIR = DATA_DIR / "claim_state"
LOGS_DIR = DATA_DIR / "logs"
UPLOADS_DIR = DATA_DIR / "uploads"

STATUS_CACHE_TTL = 20  # seconds


def ensure_dirs():
    for directory in (DATA_DIR, TOKENS_DIR, STATE_DIR, LOGS_DIR, UPLOADS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


class AccountRunner:
    """Runs the claim loop for a single Interlink account."""

    def __init__(self, engine: "Engine", account_id: str):
        self.engine = engine
        self.account_id = account_id
        self.lock = threading.RLock()
        self.status_lock = threading.Lock()
        self._login_lock = threading.Lock()
        self.thread = None
        self.stop_event = threading.Event()
        self.force_claim = threading.Event()
        self.force_group = threading.Event()
        self.force_recovery = threading.Event()

        self.status = "stopped"
        self.status_message = ""
        self.last_error = None
        self.started_at = None
        self.last_claim = None
        self.next_mining_at = None
        self.next_group_at = None
        self.token = None
        self.token_updated_at = 0
        self.restart_count = 0
        self.status_cache = {"ts": 0, "data": None}

    # ── Paths ─────────────────────────────────────────────────────────────────
    def paths(self) -> dict:
        return {
            "token_file": str(TOKENS_DIR / f"{self.account_id}.json"),
            "token_backup": str(TOKENS_DIR / f"{self.account_id}.backup.json"),
            "state_file": str(STATE_DIR / f"{self.account_id}.json"),
            "log_file": str(LOGS_DIR / f"{self.account_id}.log"),
        }

    def log_path(self) -> Path:
        return LOGS_DIR / f"{self.account_id}.log"

    def _with_context(self, fn, *args, **kwargs):
        """Run a bot.py function with this account's file context."""
        prev = bot.get_context()
        bot.set_context(**self.paths())
        try:
            return fn(*args, **kwargs)
        finally:
            bot.set_context(**prev)

    # ── Configuration ────────────────────────────────────────────────────────
    def get_cfg(self):
        row = database.get_account(self.account_id)
        if not row:
            return None
        return config_manager.account_to_cfg(row)

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> bool:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            self.stop_event.clear()
            self.force_claim.clear()
            self.force_group.clear()
            self.force_recovery.clear()
            self.status = "starting"
            self.status_message = ""
            self.last_error = None
            self.started_at = None
            self.restart_count = 0
            self.thread = threading.Thread(
                target=self._run, name=f"acct-{self.account_id}", daemon=True
            )
            self.thread.start()
            return True

    def stop(self):
        self.stop_event.set()

    def restart(self) -> bool:
        self.stop()
        thread = self.thread
        if thread:
            thread.join(timeout=15)
        with self.lock:
            self.status = "stopped"
            self.status_message = ""
            self.last_error = None
            self.restart_count = 0
            # Allow a fresh thread even if the old one is still finishing a claim.
            self.thread = None
        return self.start()

    def _run(self):
        bot.set_context(**self.paths())
        self.started_at = time.time()
        self.status = "running"
        bot.log("info", "Akun dimulai")
        try:
            while not self.stop_event.is_set():
                try:
                    self._tick()
                except Exception as e:
                    self.restart_count += 1
                    self.status = "error"
                    self.status_message = str(e)
                    self.last_error = str(e)
                    bot.log("err", f"Crash #{self.restart_count}: {e}")
                    if self.restart_count >= 50:
                        bot.log("err", "Max restart tercapai. Akun berhenti.")
                        break
                    self.stop_event.wait(30)
                self.stop_event.wait(10)
        finally:
            # Only the current thread may flip the status (a restart may have
            # already started a new thread).
            if threading.current_thread() is self.thread:
                self.status = "stopped"
                self.status_message = ""
                bot.log("info", "Akun berhenti")

    # ── Claim loop ───────────────────────────────────────────────────────────
    def _tick(self):
        cfg = self.get_cfg()
        if not cfg:
            self.status = "error"
            self.status_message = "Akun tidak ditemukan"
            return
        if not cfg.get("enabled", True):
            self.status = "disabled"
            self.status_message = ""
            return

        # Avoid noisy "no token" warnings every tick: check the token store
        # first and only call get_session (which logs) when a token exists.
        access, refresh = bot.load_tokens()
        if not access and not refresh:
            self.status = "auth_required"
            self.status_message = "Token tidak valid. Login OTP/face diperlukan."
            return

        token = self.ensure_token(cfg)
        if not token:
            self.status = "auth_required"
            self.status_message = "Token tidak valid. Login OTP/face diperlukan."
            return

        now = time.time()

        if self.force_claim.is_set():
            self.force_claim.clear()
            self.status = "claiming"
            self.status_message = "Memproses klaim mining..."
            token, claimed = bot.attempt_claim(cfg, token)
            self._after_mining(cfg, token, claimed)

        if self.force_group.is_set():
            self.force_group.clear()
            self.status = "claiming"
            self.status_message = "Memproses klaim group..."
            token, _claimed, gnext = bot.attempt_group_claim(cfg, token)
            self._after_group(gnext)

        if self.force_recovery.is_set():
            self.force_recovery.clear()
            self.status = "claiming"
            self.status_message = "Memproses recovery..."
            token, recovered = bot.attempt_recovery(cfg, token)
            if recovered > 0:
                self.last_claim = {"amount": recovered, "at": time.time(), "type": "recovery"}

        if self.stop_event.is_set():
            return

        if self.next_mining_at is None or now >= self.next_mining_at:
            self.status = "claiming"
            self.status_message = "Waktu mining tiba..."
            token, claimed = bot.attempt_claim(cfg, token)
            self._after_mining(cfg, token, claimed)

        if self.next_group_at is None or now >= self.next_group_at:
            self.status = "claiming"
            self.status_message = "Waktu group mining tiba..."
            token, _claimed, gnext = bot.attempt_group_claim(cfg, token)
            self._after_group(gnext)

        self.status = "running"
        self.status_message = ""

    def _after_mining(self, cfg, token, claimed):
        if self.stop_event.is_set():
            return
        try:
            ic = bot.check_claimable(token, cfg.get("deviceId", ""))
            nf = ic.get("nextFrame")
            self.next_mining_at = (nf / 1000.0) if nf else time.time() + 4 * 3600
        except Exception:
            self.next_mining_at = time.time() + 4 * 3600

        if self.stop_event.is_set():
            return
        if claimed:
            # bot.attempt_claim() returns a boolean; the real amount is stored
            # in the claim-state file by save_claim_state().
            try:
                state = bot.load_claim_state()
                amount = state.get("last_claim")
            except Exception:
                amount = None
            self.last_claim = {"amount": amount, "at": time.time(), "type": "mine"}
            self.status = "claiming"
            self.status_message = "Memproses recovery pasca klaim..."
            token, recovered = bot.attempt_recovery(cfg, token)
            if recovered > 0:
                self.last_claim = {"amount": recovered, "at": time.time(), "type": "recovery"}

    def _after_group(self, gnext):
        if self.stop_event.is_set():
            return
        self.next_group_at = (gnext / 1000.0) if gnext else time.time() + 24 * 3600

    # ── Tokens ───────────────────────────────────────────────────────────────
    def ensure_token(self, cfg=None):
        with self._login_lock:
            if cfg is None:
                cfg = self.get_cfg()
            if not cfg:
                return None
            if self.token and (time.time() - self.token_updated_at) < 60:
                return self.token
            token = bot.get_session(cfg, allow_login=False)
            if token:
                self.token = token
                self.token_updated_at = time.time()
            return token

    # ── Status ────────────────────────────────────────────────────────────────
    def public_status(self) -> dict:
        return {
            "id": self.account_id,
            "status": self.status,
            "status_message": self.status_message,
            "last_error": self.last_error,
            "uptime": int(time.time() - self.started_at) if self.started_at else 0,
            "last_claim": self.last_claim,
            "next_mining_at": self.next_mining_at,
            "next_group_at": self.next_group_at,
            "token_valid": bool(self.token),
        }

    def invalidate_status(self):
        with self.status_lock:
            self.status_cache = {"ts": 0, "data": None}

    def get_status(self, force: bool = False):
        now = time.time()
        with self.status_lock:
            cached = self.status_cache
            if (
                not force
                and cached.get("data")
                and now - cached.get("ts", 0) < STATUS_CACHE_TTL
            ):
                return cached["data"]

        cfg = self.get_cfg()
        if not cfg:
            return None

        data = self._with_context(self._fetch_status, cfg)
        with self.status_lock:
            self.status_cache = {"ts": now, "data": data}
        return data

    def _fetch_status(self, cfg) -> dict:
        token = self.ensure_token(cfg)
        result = {
            "id": self.account_id,
            "name": cfg.get("name", ""),
            "loginId": cfg.get("loginId", ""),
            "enabled": cfg.get("enabled", True),
            "token_valid": bool(token),
            "status": self.status,
            "status_message": self.status_message,
            "last_error": self.last_error,
            "uptime": int(time.time() - self.started_at) if self.started_at else 0,
            "last_claim": self.last_claim,
            "next_mining_at": self.next_mining_at,
            "next_group_at": self.next_group_at,
            "balance": 0,
            "username": None,
            "mining": {"claimable": False, "next_at": None, "next_in": None},
            "group": {
                "claimable": False,
                "claimed_today": False,
                "groups": 0,
                "pool": 0,
                "next_at": None,
                "next_in": None,
            },
            "recovery": {"available": False, "amount": 0},
            "rates": {},
            "referrals": {"total": 0, "hashrate": 0},
            "streak": 0,
            "burned": 0,
            "history": [],
            "last_claim_state": 0,
            "last_claim_at": None,
        }

        try:
            state = bot.load_claim_state()
            result["history"] = state.get("history", [])
            result["last_claim_state"] = state.get("last_claim", 0)
            result["last_claim_at"] = state.get("updated_at")
            if state.get("balance") is not None:
                result["balance"] = state.get("balance", 0)
        except Exception:
            pass

        if not token:
            return result

        device_id = cfg.get("deviceId", "")

        try:
            user = bot.get_user_info(token, device_id) or {}
            ui = user.get("userInfo", {}) or {}
            ti = user.get("token", {}) or {}
            ic = user.get("isClaimable", {}) or {}

            result["username"] = ui.get("username")
            result["balance"] = ti.get("interlinkGoldTokenAmount", result["balance"])
            result["streak"] = ti.get("burningStreak", 0)
            result["burned"] = ti.get("burnedCycles", 0)
            result["rates"] = {
                "mining": ti.get("dailyMiningRate", 0) or 0,
                "group": ti.get("groupMiningRate", 0) or 0,
                "ref_direct": ti.get("directReferralsHashRate", 0)
                or ti.get("directReferralHashRate", 0)
                or 0,
                "ref_indirect": ti.get("indirectReferralsHashRate", 0)
                or ti.get("indirectReferralHashRate", 0)
                or 0,
            }
            result["referrals"] = {
                "total": ti.get("totalReferral", 0),
                "hashrate": round(
                    result["rates"]["ref_direct"] + result["rates"]["ref_indirect"], 2
                ),
            }
            result["recovery"]["amount"] = (
                ti.get("itlgRecoverable", 0) or ti.get("itlgBisa dipulihkan", 0) or 0
            )

            if not ic:
                ic = bot.check_claimable(token, device_id) or {}
            result["mining"]["claimable"] = bool(ic.get("isClaimable"))
            nf = ic.get("nextFrame")
            if nf:
                result["mining"]["next_at"] = nf / 1000.0
                result["mining"]["next_in"] = max(0, nf / 1000.0 - time.time())

            history = result["history"]
            if history:
                avg = sum(history) / len(history)
                result["rates"]["avg_per_claim"] = round(avg, 1)
                result["rates"]["avg_per_day"] = round(avg * 6, 1)
        except Exception as e:
            result["api_error"] = str(e)

        try:
            gdata = bot.get_group_mining_list(token, device_id) or {}
            groups = gdata.get("groups", []) or []
            next_claim = gdata.get("nextTimeClaim")
            result["group"] = {
                "claimable": bool(gdata.get("isClaimable")),
                "claimed_today": bool(gdata.get("requesterHasClaimedToday")),
                "groups": len(groups),
                "pool": sum(g.get("totalReward", 0) for g in groups),
                "next_at": (next_claim / 1000.0) if next_claim else None,
                "next_in": (
                    max(0, next_claim / 1000.0 - time.time()) if next_claim else None
                ),
            }
        except Exception as e:
            result["group_error"] = str(e)

        try:
            can, total = bot.check_recovery(token, device_id)
            result["recovery"] = {"available": bool(can), "amount": total or 0}
        except Exception:
            pass

        return result


class LoginManager:
    """Handles OTP and face login flows for accounts."""

    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.pending = {}
        self.lock = threading.Lock()

    def _get_pending(self, account_id):
        with self.lock:
            p = self.pending.get(account_id)
            if p and p.get("expires_at", 0) < time.time():
                self.pending.pop(account_id, None)
                return None
            return p

    def request_otp(self, account_id):
        runner = self.engine.get_runner(account_id)
        if not runner:
            raise ValueError("Akun tidak ditemukan")
        cfg = runner.get_cfg()
        if not cfg:
            raise ValueError("Akun tidak ditemukan")
        if not cfg.get("loginId") or not cfg.get("passcode"):
            raise ValueError("Login ID / passcode belum diisi")
        if not cfg.get("imapPassword"):
            raise ValueError("Gmail App Password (imapPassword) belum diisi")

        email = cfg.get("email")
        if not email:
            try:
                email = runner._with_context(bot.check_passcode, cfg)
            except Exception:
                email = None
            if not email:
                raise ValueError("Email tidak ditemukan. Isi email pada konfigurasi akun.")

        send_ts = time.time()
        pending = {
            "status": "sending",
            "message": "Mengirim OTP...",
            "email": email,
            "send_ts": send_ts,
            # Samakan dengan batas tunggu grab_otp (bot.OTP_TIMEOUT = 180 dtk)
            # agar countdown UI akurat.
            "expires_at": send_ts + bot.OTP_TIMEOUT,
        }
        with self.lock:
            self.pending[account_id] = pending

        def set_status(status, message):
            """Update status, tapi jangan timpa hasil sukses (mis. verifikasi manual)."""
            with self.lock:
                if self.pending.get(account_id) is not pending:
                    return False
                if pending.get("status") == "success":
                    return False
                pending["status"] = status
                pending["message"] = message
            return True

        def job():
            bot.set_context(**runner.paths())
            try:
                if not bot.send_otp(cfg, email):
                    set_status("failed", "Gagal mengirim OTP. Periksa konfigurasi.")
                    return
                if not set_status("waiting", "OTP terkirim. Menunggu kode masuk..."):
                    return
                otp = bot.grab_otp(cfg, email, send_ts)
                # Job lama (sebelum "kirim ulang") tidak boleh lanjut.
                with self.lock:
                    if self.pending.get(account_id) is not pending:
                        return
                if not otp:
                    set_status(
                        "timeout",
                        "OTP belum masuk. Masukkan kode secara manual atau kirim ulang.",
                    )
                    return
                access, refresh = bot.verify_otp(cfg, otp)
                if access:
                    bot.save_tokens(access, refresh)
                    runner.invalidate_status()
                    set_status("success", "Login OTP berhasil (otomatis)!")
                else:
                    set_status("manual", "OTP otomatis gagal. Masukkan kode secara manual.")
            except Exception as e:
                set_status("failed", str(e))
            finally:
                bot.reset_context()

        threading.Thread(target=job, name=f"otp-{account_id}", daemon=True).start()
        return pending

    def verify_otp(self, account_id, code):
        runner = self.engine.get_runner(account_id)
        if not runner:
            raise ValueError("Akun tidak ditemukan")
        cfg = runner.get_cfg()
        if not cfg:
            raise ValueError("Akun tidak ditemukan")

        def _verify(cfg, code):
            access, refresh = bot.verify_otp(cfg, code)
            if access:
                bot.save_tokens(access, refresh)
                runner.invalidate_status()
                return True, "Login OTP berhasil!"
            return False, "Kode OTP salah atau kedaluwarsa."

        ok, message = runner._with_context(_verify, cfg, code)
        if ok:
            # Tandai pending sukses agar thread auto-grab tidak menimpanya.
            with self.lock:
                p = self.pending.get(account_id)
                if p:
                    p["status"] = "success"
                    p["message"] = "Login OTP berhasil!"
        return ok, message

    def login_face(self, account_id, photo_path):
        runner = self.engine.get_runner(account_id)
        if not runner:
            raise ValueError("Akun tidak ditemukan")
        cfg = runner.get_cfg()
        if not cfg:
            raise ValueError("Akun tidak ditemukan")
        cfg = dict(cfg)
        cfg["facePhoto"] = photo_path

        def _face(cfg):
            access, _refresh = bot.do_face_login(cfg)
            if access:
                runner.invalidate_status()
                return True, "Face login berhasil!"
            return False, "Face login gagal. Periksa foto dan konfigurasi."

        return runner._with_context(_face, cfg)


class Engine:
    """Owns all account runners and exposes a thread-safe API."""

    def __init__(self):
        self.runners = {}
        self.lock = threading.RLock()
        self.login_manager = LoginManager(self)
        self._started = False

    # ── Registry ─────────────────────────────────────────────────────────────
    def sync_accounts(self):
        with self.lock:
            rows = database.list_accounts()
            ids = {row["id"] for row in rows}
            for row in rows:
                if row["id"] not in self.runners:
                    self.runners[row["id"]] = AccountRunner(self, row["id"])
            for account_id in list(self.runners):
                if account_id not in ids:
                    self.runners[account_id].stop()
                    del self.runners[account_id]

    def get_runner(self, account_id):
        with self.lock:
            return self.runners.get(account_id)

    def get_status_all(self):
        with self.lock:
            runners = list(self.runners.values())

        results = {}

        def worker(runner):
            try:
                results[runner.account_id] = runner.get_status(force=False)
            except Exception as e:
                results[runner.account_id] = {
                    "id": runner.account_id,
                    "status": "error",
                    "last_error": str(e),
                }

        threads = [
            threading.Thread(target=worker, args=(r,), daemon=True) for r in runners
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        accounts = []
        for runner in runners:
            data = results.get(runner.account_id) or runner.public_status()
            accounts.append(data)
        return accounts

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def start(self):
        with self.lock:
            if self._started:
                return
            self._started = True
            self.sync_accounts()
            if database.get_setting("autostart", "true") == "true":
                for account_id in list(self.runners):
                    self.start_account(account_id)

    def stop_all(self):
        with self.lock:
            for runner in self.runners.values():
                runner.stop()
            self._started = False

    def start_account(self, account_id):
        runner = self.get_runner(account_id)
        if not runner:
            return False
        return runner.start()

    def stop_account(self, account_id):
        runner = self.get_runner(account_id)
        if not runner:
            return False
        runner.stop()
        return True

    def restart_account(self, account_id):
        runner = self.get_runner(account_id)
        if not runner:
            return False
        return runner.restart()

    def restart_all(self):
        with self.lock:
            for runner in self.runners.values():
                runner.stop()
            for account_id, runner in list(self.runners.items()):
                runner.restart()

    def on_account_created(self, account_id):
        self.sync_accounts()
        if database.get_setting("autostart", "true") == "true":
            self.start_account(account_id)

    # ── Aggregated status ────────────────────────────────────────────────────
    def global_status(self):
        accounts = self.get_status_all()
        total_balance = 0
        active = 0
        auth_required = 0
        for acc in accounts:
            total_balance += acc.get("balance", 0) or 0
            if acc.get("status") == "running":
                active += 1
            elif acc.get("status") == "auth_required":
                auth_required += 1

        return {
            "accounts": accounts,
            "totals": {
                "balance": total_balance,
                "active": active,
                "auth_required": auth_required,
                "count": len(accounts),
            },
            "system": system.metrics(),
        }
