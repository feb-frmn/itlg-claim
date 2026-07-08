#!/usr/bin/env python3
"""
Gateway Telegram ITLG v2.2 — Interface perintah untuk Bot Klaim ITLG.

v2.2 changelog:
  - /groupclaim command (force group mining claim)
  - Private bot guard (non-owner DM → rejected)
  - claim_type field in notifications (mine vs group)
  - Use bot.py's actual API functions (correct endpoints)
  - Use bot.py's STOP_FILE constant (correct stopfile name)
  - Token auto-refresh via ensure_token_valid()
  - Full claim flow: ads trigger → claim → save state → Telegram notif
  - Group mining + recovery status in /status
  - Claim history from claim_state.json
"""
import json, os, sys, time, signal, subprocess, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
TOKEN_FILE  = SCRIPT_DIR / "token.json"
PID_FILE    = SCRIPT_DIR / ".bot.pid"
WIB         = timezone(timedelta(hours=7))


_status_cache = {"ts": 0, "data": None}

def get_cached_status(tk, device_id):
    global _status_cache
    now = time.time()
    if now - _status_cache["ts"] < 45 and _status_cache["data"]:
        return _status_cache["data"]
    # Build fresh
    data = itlg.get_user_info(tk, device_id) or {}
    ic = itlg.check_claimable(tk, device_id) or {}
    g = itlg.get_group_mining_list(tk, device_id) or {}
    can_rec, tot_rec = itlg.check_recovery(tk, device_id)
    _status_cache = {"ts": now, "data": (data, ic, g, can_rec, tot_rec)}
    return _status_cache["data"]


# Import bot.py — gives us all API functions + constants
sys.path.insert(0, str(SCRIPT_DIR))
import bot as itlg
import requests

# Simple TTL cache for speed (avoid full API on every TG command)
_CACHE = {}
def _cached(key, fn, ttl=30):
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < ttl:
        return _CACHE[key][1]
    val = fn()
    _CACHE[key] = (now, val)
    return val

requests.packages.urllib3.disable_warnings()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def load_tokens():
    try:
        with open(TOKEN_FILE) as f:
            d = json.load(f)
        return d.get("access"), d.get("refresh")
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None

def fmt_wib():
    return datetime.now(WIB).strftime("%H:%M:%S")

def countdown(seconds):
    h, m, s = int(seconds//3600), int((seconds%3600)//60), int(seconds%60)
    return f"{h:02d}h {m:02d}m {s:02d}s"

def bot_pid():
    """Reliable detection if the ITLG bot daemon is running."""
    import subprocess, os

    # Try .bot.pid first
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return pid
        except Exception:
            pass

    # Strong pgrep fallback
    try:
        out = subprocess.getoutput('pgrep -f "python3 bot.py"').strip()
        pids = []
        for line in out.splitlines():
            try:
                p = int(line.strip())
                # Read cmdline to confirm it's the bot, not gateway or tests
                with open(f"/proc/{p}/cmdline", "rb") as fh:
                    cmd = fh.read().decode(errors="ignore")
                if "bot.py" in cmd and "tg_gateway" not in cmd and "test" not in cmd:
                    pids.append(p)
            except Exception:
                continue
        if pids:
            return min(pids)  # oldest one is usually the main daemon
    except Exception:
        pass
    return None


def get_valid_token(cfg):
    """Get a valid token, refreshing if needed. Returns token or None. Cached 25s for speed."""
    def _do():
        access, refresh = load_tokens()
        if access and not itlg.token_expired(access):
            return access
        if refresh:
            new = itlg.do_refresh(cfg, refresh)
            if new:
                return new
        if cfg.get("facePhoto") and os.path.exists(cfg["facePhoto"]):
            access, _ = itlg.do_face_login(cfg)
            if access:
                return access
        return None
    return _cached("token", _do, ttl=25)


# === STATUS CACHE (makes /status fast) ===
_STATUS_CACHE = {"ts": 0, "payload": None}
STATUS_CACHE_TTL = 60  # seconds

def get_status_payload(tk, device_id):
    """Return cached or fresh status data for /status. Very important for speed."""
    global _STATUS_CACHE
    now = time.time()
    if now - _STATUS_CACHE["ts"] < STATUS_CACHE_TTL and _STATUS_CACHE["payload"]:
        return _STATUS_CACHE["payload"]

    # Fresh fetch (this is the expensive part)
    data = itlg.get_user_info(tk, device_id) or {}
    ic = itlg.check_claimable(tk, device_id) or {}
    g = itlg.get_group_mining_list(tk, device_id) or {}
    can_rec, tot_rec = itlg.check_recovery(tk, device_id)

    _STATUS_CACHE = {
        "ts": now,
        "payload": (data, ic, g, can_rec, tot_rec)
    }
    return _STATUS_CACHE["payload"]


# ─── Telegram ─────────────────────────────────────────────────────────────────

def tg(token, method, **params):
    """Use requests for more reliable SSL handling."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(4):
        try:
            resp = requests.post(url, json=params, timeout=25, headers={"Content-Type": "application/json"})
            if resp.ok:
                return resp.json()
            time.sleep(1 + attempt)
        except Exception as e:
            if attempt == 3:
                return None
            time.sleep(1 + attempt)
    return None

def send(cid, text, token, reply_to=None):
    if len(text) > 4000:
        text = text[:3997] + "..."
    try:
        return tg(token, "sendMessage", chat_id=cid, text=text,
                  parse_mode="HTML", reply_to_message_id=reply_to)
    except Exception as e:
        print(f"[send error] {e}")
        return None

def poll(token, offset=None, backoff=0):
    """Long polling with auto backoff on failure."""
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    for attempt in range(5):
        try:
            resp = requests.get(url, params=params, timeout=35)
            if resp.ok:
                return resp.json(), 0  # reset backoff
            time.sleep(1 + attempt + backoff)
        except Exception as e:
            if attempt == 4:
                return None, min(backoff + 5, 60)
            time.sleep(1 + attempt + backoff)
    return None, min(backoff + 5, 60)

# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_start(cid, token):
    send(cid,
        "🤖 <b>Bot Klaim ITLG</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Otomatis klaim ITLG setiap 4 jam.\n"
        "Group mining every 24h.\n"
        "Auto-recovery of burned cycles.\n\n"
        "Ketik /help untuk daftar perintah.",
        token)

def cmd_help(cid, token):
    send(cid,
        "📖 <b>Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "/status       Dashboard lengkap\n"
        "/balance      Quick balance\n"
        "/claim        Paksa klaim mining\n"
        "/groupclaim   Paksa klaim group\n"
        "/recovery     Cek & klaim pemulihan burn\n"
        "/stop         Hentikan bot\n"
        "/restart      Restart ulang bot\n"
        "/help         This message",
        token)

def cmd_status(cid, token):
    cfg = load_config()
    tk = get_valid_token(cfg)
    device_id = cfg.get("deviceId", "")

    if not tk:
        send(cid,
            "❌ <b>Token tidak valid</b>\n"
            "Jalankan: <code>python3 bot.py --login-face</code>",
            token)
        return

    # ── Mining status (from check-claimable) - using cache for speed
    data, ic, gdata, can_recover, total_recover = get_status_payload(tk, device_id)
    claimable = ic.get("isClaimable", False)
    nf = ic.get("nextFrame")

    if claimable:
        mining_str = "✅ <b>Bisa diklaim sekarang!</b>"
    elif nf:
        remain = max(0, int((nf - time.time() * 1000) / 1000))
        mining_str = f"⏳ {countdown(remain)}"
    else:
        mining_str = "Unknown"

    # ── User info from cache
    # data already fetched above
    bal = 0
    refs_str = "N/A"
    streak_str = "N/A"
    recover_str = "N/A"
    per_claim_str = "N/A"
    per_day_str = "N/A"
    last_claim_str = "N/A"

    if data:
        ti = data.get("token", {})
        bal = ti.get("interlinkGoldTokenAmount", 0)
        total_ref = ti.get("totalReferral", 0)
        ref_dir = ti.get("directReferralHashRate", 0) or 0
        ref_ind = ti.get("indirectReferralHashRate", 0) or 0
        refs_str = f"{round(ref_dir + ref_ind, 2)} ({total_ref} refs)"
        streak = ti.get("burningStreak", 0)
        burned = ti.get("burnedCycles", 0)
        streak_str = f"{streak} / {burned}"
        recover_str = f"{ti.get('itlgRecoverable', ti.get('itlgBisa dipulihkan', 0))} ITLG"

        # Klaim terakhir time from API
        lct = ti.get("lastClaimTime")
        if lct:
            lct_sec = int(lct / 1000)
            ago = int(time.time() - lct_sec)
            h, m = ago // 3600, (ago % 3600) // 60
            lct_wib = datetime.fromtimestamp(lct_sec, tz=WIB).strftime("%H:%M WIB")
            last_claim_str = f"{h}h {m}m ago ({lct_wib})"

    # ── Claim history (from claim_state.json) ──
    state = itlg.load_claim_state()
    history = state.get("history", [])
    if history:
        avg = round(sum(history) / len(history), 1)
        per_claim_str = f"{avg} ITLG"
        per_day_str = f"{round(avg * 6, 1)} ITLG"

    # ── Group mining from cache
    group_str = "N/A"
    group_next_str = "N/A"
    if gdata:
        groups = gdata.get("groups", [])
        gnext = gdata.get("nextTimeClaim")
        already = gdata.get("requesterHasClaimedToday", False)
        total_pool = sum(g.get("totalReward", 0) for g in groups)
        if already:
            group_str = f"✅ Claimed today ({len(groups)} groups, pool: {total_pool})"
        elif gdata.get("isClaimable"):
            group_str = f"✅ Claimable! ({len(groups)} groups, pool: {total_pool})"
        else:
            group_str = f"⏳ Pending ({len(groups)} groups, pool: {total_pool})"
        if gnext:
            g_remain = max(0, int((gnext - time.time() * 1000) / 1000))
            group_next_str = countdown(g_remain)

    # ── Recovery from cache
    recovery_status = f"{total_recover} ITLG" if can_recover else "Tidak ada yang bisa dipulihkan saat ini"

    # ── Bot status ──
    pid = bot_pid()
    bot_status = f"✅ Berjalan (PID {pid})" if pid else "❌ Berhenti"

    send(cid,
        f"📊 <b>Dashboard ITLG</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Saldo      <b>{bal}</b> ITLG\n"
        f"⛏️ Mining       {mining_str}\n"
        f"📈 Per klaim    {per_claim_str}\n"
        f"📈 Per hari      {per_day_str}\n"
        f"🎯 Klaim terakhir   {last_claim_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Referral    {refs_str}\n"
        f"🔥 Streak/Burn  {streak_str}\n"
        f"💎 Bisa dipulihkan  {recover_str}\n"
        f"♻️ Pemulihan     {recovery_status}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Group        {group_str}\n"
        f"⏳ Group berikutnya   {group_next_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Bot          {bot_status}\n"
        f"🕐 {fmt_wib()} WIB",
        token)

def cmd_balance(cid, token):
    cfg = load_config()
    tk = get_valid_token(cfg)
    if not tk:
        send(cid, "❌ Token tidak valid. Jalankan: <code>python3 bot.py --login-face</code>", token)
        return
    device_id = cfg.get("deviceId", "")
    bal = itlg.get_balance(tk, device_id)
    if bal is None:
        send(cid, "❌ Failed to fetch balance.", token)
        return
    ic = itlg.check_claimable(tk, device_id)
    claimable = ic.get("isClaimable", False)
    status = "✅ Claimable" if claimable else "⏳ Mining"
    state = itlg.load_claim_state()
    history = state.get("history", [])
    avg = f" (~{round(sum(history)/len(history), 1)}/claim)" if history else ""
    send(cid,
        f"💰 <b>{bal}</b> ITLG\n"
        f"{status}{avg}\n"
        f"🕐 {fmt_wib()} WIB",
        token)

def cmd_claim(cid, token):
    cfg = load_config()
    tk = get_valid_token(cfg)
    if not tk:
        send(cid, "❌ Token tidak valid. Jalankan: <code>python3 bot.py --login-face</code>", token)
        return
    device_id = cfg.get("deviceId", "")

    # Check if claimable
    ic = itlg.check_claimable(tk, device_id)
    if not ic.get("isClaimable"):
        nf = ic.get("nextFrame")
        if nf:
            r = max(0, int((nf - time.time() * 1000) / 1000))
            send(cid, f"⏳ Not ready yet.\nNext claim: {countdown(r)}", token)
        else:
            send(cid, "⏳ Not claimable yet.", token)
        return

    send(cid, "⛏️ Claiming...", token)

    # Full claim flow (same as bot.py's attempt_claim)
    balance_before = itlg.get_balance(tk, device_id)
    user = itlg.get_user_info(tk, device_id)
    if not user:
        send(cid, "❌ Failed to get user info.", token)
        return

    ti = user.get("token", {})
    last_claim = ti.get("lastClaimTime") or int(time.time() * 1000)
    group_rate = ti.get("groupMiningRate", 0) or 0

    # Trigger ads first (required by ITLG)
    wait = itlg.trigger_ads(tk, device_id, last_claim)
    time.sleep(wait + 5)

    # Claim
    result = itlg.claim_airdrop(tk, device_id)
    status = result.get("statusCode")
    msg = result.get("message", "")

    if status == 200:
        time.sleep(2)
        balance_after = itlg.get_balance(tk, device_id)
        claimed = (balance_after - balance_before) if balance_before is not None and balance_after is not None else 0
        rates = itlg.get_rates(ti, itlg.load_claim_state())
        itlg.save_claim_state(claimed=claimed, balance=balance_after)

        # Telegram notification
        try:
            itlg.send_telegram_notif(cfg, {
                "claimed": claimed,
                "before": balance_before,
                "after": balance_after,
                "rate_per_claim": rates["actual_per_claim"] if rates["has_history"] else claimed,
                "rate_per_day": rates["actual_per_day"] if rates["has_history"] else None,
                "group_rate": group_rate,
                "claim_type": "mine",
            })
        except Exception:
            pass

        send(cid,
            f"✅ <b>Claimed +{claimed} ITLG</b>\n"
            f"📊 {balance_before} → {balance_after}\n"
            f"🕐 {fmt_wib()} WIB",
            token)
        return

    # Retry on 500
    if status == 500:
        time.sleep(10)
        result2 = itlg.claim_airdrop(tk, device_id)
        if result2.get("statusCode") == 200:
            time.sleep(2)
            balance_after = itlg.get_balance(tk, device_id)
            claimed = (balance_after - balance_before) if balance_before is not None and balance_after is not None else 0
            rates = itlg.get_rates(ti, itlg.load_claim_state())
            itlg.save_claim_state(claimed=claimed, balance=balance_after)
            try:
                itlg.send_telegram_notif(cfg, {
                    "claimed": claimed,
                    "before": balance_before,
                    "after": balance_after,
                    "rate_per_claim": rates["actual_per_claim"] if rates["has_history"] else claimed,
                    "rate_per_day": rates["actual_per_day"] if rates["has_history"] else None,
                    "group_rate": group_rate,
                    "claim_type": "mine",
                })
            except Exception:
                pass
            send(cid,
                f"✅ <b>Claimed on retry! +{claimed} ITLG</b>\n"
                f"📊 {balance_before} → {balance_after}\n"
                f"🕐 {fmt_wib()} WIB",
                token)
            return
        send(cid, f"❌ Retry failed: {result2.get('message', 'Unknown')}", token)
        return

    if status == 400 and "TOO_EARLY" in str(msg).upper():
        send(cid, "ℹ️ Already claimed (maybe manual?).", token)
        return

    send(cid, f"❌ Failed ({status}): {msg}", token)

def cmd_stop(cid, token):
    pid = bot_pid()
    if not pid:
        send(cid, "ℹ️ Bot not running.", token)
        return
    # Use bot.py's STOP_FILE (.stop), NOT .bot.stop
    with open(itlg.STOP_FILE, "w") as f:
        f.write(str(int(time.time())))
    try:
        os.kill(pid, signal.SIGTERM)
        send(cid, f"🛑 Stopping bot (PID {pid})...", token)
    except (ProcessLookupError, PermissionError) as e:
        send(cid, f"⚠️ Signal failed: {e}\nStopfile created, bot will exit within 10s.", token)
    # Clean up after delay
    time.sleep(3)
    for f in (itlg.STOP_FILE, itlg.PID_FILE):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

def cmd_restart(cid, token):
    pid = bot_pid()
    if pid:
        # Use bot.py's STOP_FILE
        with open(itlg.STOP_FILE, "w") as f:
            f.write(str(int(time.time())))
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        # Wait for process to actually die
        for _ in range(10):
            time.sleep(1)
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, OSError):
                break
        # Cleanup
        for f in (itlg.STOP_FILE, itlg.PID_FILE):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass

    # Start new instance
    try:
        subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "bot.py")],
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True)
        send(cid, "🔄 Bot restarting...", token)
        # Verify it started
        time.sleep(3)
        new_pid = bot_pid()
        if new_pid:
            send(cid, f"✅ Bot running (PID {new_pid})", token)
        else:
            send(cid, "⚠️ Bot started but PID not found yet. Check with /status", token)
    except Exception as e:
        send(cid, f"❌ Failed to start: {e}", token)

def cmd_groupclaim(cid, token):
    """Force claim group mining."""
    cfg = load_config()
    tk = get_valid_token(cfg)
    if not tk:
        send(cid, "❌ Token tidak valid. Jalankan: <code>python3 bot.py --login-face</code>", token)
        return

    send(cid, "👥 Checking group mining...", token)

    # Use bot.py's attempt_group_claim
    tk2, claimed, group_next = itlg.attempt_group_claim(cfg, tk)

    if claimed:
        send(cid, "✅ <b>Group mining claimed!</b>\n🕐 " + fmt_wib() + " WIB", token)
    elif group_next:
        r = max(0, int((group_next - time.time() * 1000) / 1000))
        send(cid, f"⏳ Group mining not ready.\nNext: {countdown(r)}", token)
    else:
        send(cid, "❌ Group mining claim failed. Check logs.", token)


def cmd_recovery(cid, token):
    """Force check and attempt recovery burn claim (full Indonesian)."""
    cfg = load_config()
    tk = get_valid_token(cfg)
    if not tk:
        send(cid, "❌ Token tidak valid.", token)
        return
    device_id = cfg.get("deviceId", "")
    send(cid, "♻️ Cek pemulihan burn...", token)
    can, total = itlg.check_recovery(tk, device_id)
    if not can or total <= 0:
        send(cid, f"ℹ️ Tidak ada yang bisa dipulihkan saat ini. Total: {total} ITLG", token)
        return
    burns = itlg.get_recoverable_burns(tk, device_id)
    send(cid, f"✅ Ditemukan {len(burns)} burn yang bisa dipulihkan. Total ~{total} ITLG. Mencoba pemulihan...", token)
    # Use bot.py logic
    tk2, recovered = itlg.attempt_recovery(cfg, tk)
    if recovered > 0:
        send(cid, f"✅ Pemulihan berhasil +{recovered} ITLG!", token)
    else:
        send(cid, "⚠️ Cek pemulihan lolos tapi klaim gagal (mungkin belum unlock cycle). Cek log.", token)


COMMANDS = {
    "/start": cmd_start, "/help": cmd_help, "/status": cmd_status,
    "/balance": cmd_balance, "/claim": cmd_claim,
    "/groupclaim": cmd_groupclaim,
    "/recovery": cmd_recovery,
    "/stop": cmd_stop, "/restart": cmd_restart,
}

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("🤖 ITLG Telegram Gateway v2.2")
    print("  ☕ https://saweria.co/febfrmn\n")

    cfg = load_config()
    token = cfg.get("tgBotToken")
    owner = cfg.get("tgChatId")

    if not token:
        print("❌ tgBotToken not set. Jalankan: python3 setup.py")
        sys.exit(1)

    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
        if resp.ok:
            name = resp.json()["result"]["username"]
            print(f"✅ Bot: @{name}")
        else:
            print(f"❌ Invalid token: HTTP {resp.status_code}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Invalid token: {e}")
        sys.exit(1)

    print(f"👤 Owner: {owner}")
    print(f"🤖 Bot: {'Berjalan' if bot_pid() else 'Berhenti'}")
    print(f"Listening...\n")

    offset = None
    backoff = 0
    consecutive_errors = 0
    print("✅ Gateway listening (long-poll + auto-reconnect enabled)\n")

    while True:
        try:
            result = poll(token, offset, backoff)
            if result is None:
                updates, new_backoff = None, backoff
            else:
                updates, new_backoff = result

            if not updates or not updates.get("ok"):
                consecutive_errors += 1
                backoff = new_backoff if new_backoff else min(5 * consecutive_errors, 60)
                print(f"[{fmt_wib()}] Poll failed (backoff {backoff}s, err#{consecutive_errors})")
                time.sleep(backoff)
                continue

            consecutive_errors = 0
            backoff = 0

            for u in updates.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message", {})
                text = msg.get("text", "")
                cid = msg.get("chat", {}).get("id")
                if not text or not cid:
                    continue
                if str(cid) != str(owner):
                    send(cid, "🔒 <b>Private Bot</b>\n\nBot ini cuma buat admin.", token)
                    continue
                cmd = text.strip().lower().split()[0]
                handler = COMMANDS.get(cmd)
                if handler:
                    print(f"[{fmt_wib()}] {cmd}")
                    try:
                        handler(cid, token)
                    except Exception as e:
                        print(f"[ERROR] {cmd}: {e}")
                        send(cid, f"❌ Error: {e}", token)
                else:
                    send(cid, "Unknown command. Tap /help", token)

        except Exception as e:
            consecutive_errors += 1
            backoff = min(5 * consecutive_errors, 60)
            print(f"[GATEWAY ERROR] {e} — reconnecting in {backoff}s")
            time.sleep(backoff)

if __name__ == "__main__":
    main()
