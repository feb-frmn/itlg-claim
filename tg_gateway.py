#!/usr/bin/env python3
"""
ITLG Telegram Gateway v2.0 — Command interface for ITLG Claim Bot.

Fixed v2.0:
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

# Import bot.py — gives us all API functions + constants
sys.path.insert(0, str(SCRIPT_DIR))
import bot as itlg
import requests
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
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return None

def get_valid_token(cfg):
    """Get a valid token, refreshing if needed. Returns token or None."""
    access, refresh = load_tokens()
    if access and not itlg.token_expired(access):
        return access
    if refresh:
        new = itlg.do_refresh(cfg, refresh)
        if new:
            return new
    # Try face login fallback
    if cfg.get("facePhoto") and os.path.exists(cfg["facePhoto"]):
        access, _ = itlg.do_face_login(cfg)
        if access:
            return access
    return None

# ─── Telegram ─────────────────────────────────────────────────────────────────

def tg(token, method, **params):
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(params).encode()
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception:
        return None

def send(cid, text, token, reply_to=None):
    # Telegram max message length = 4096
    if len(text) > 4000:
        text = text[:3997] + "..."
    return tg(token, "sendMessage", chat_id=cid, text=text,
              parse_mode="HTML", reply_to_message_id=reply_to)

def poll(token, offset=None):
    params = {"timeout": 30, "allowed_updates": json.dumps(["message"])}
    if offset:
        params["offset"] = offset
    qs = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{token}/getUpdates?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=35) as r:
            return json.loads(r.read())
    except Exception:
        return None

# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_start(cid, token):
    send(cid,
        "🤖 <b>ITLG Claim Bot</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Auto-claims ITLG every 4h.\n"
        "Group mining every 24h.\n"
        "Auto-recovery of burned cycles.\n\n"
        "Tap /help for commands.",
        token)

def cmd_help(cid, token):
    send(cid,
        "📖 <b>Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n"
        "/status       Full dashboard\n"
        "/balance      Quick balance\n"
        "/claim        Force mine claim\n"
        "/groupclaim   Force group claim\n"
        "/stop         Stop bot\n"
        "/restart      Restart bot\n"
        "/help         This message",
        token)

def cmd_status(cid, token):
    cfg = load_config()
    tk = get_valid_token(cfg)
    device_id = cfg.get("deviceId", "")

    if not tk:
        send(cid,
            "❌ <b>No valid token</b>\n"
            "Run: <code>python3 bot.py --login-face</code>",
            token)
        return

    # ── Mining status (from check-claimable) ──
    ic = itlg.check_claimable(tk, device_id)
    claimable = ic.get("isClaimable", False)
    nf = ic.get("nextFrame")

    if claimable:
        mining_str = "✅ <b>Claimable now!</b>"
    elif nf:
        remain = max(0, int((nf - time.time() * 1000) / 1000))
        mining_str = f"⏳ {countdown(remain)}"
    else:
        mining_str = "Unknown"

    # ── User info (balance, refs, streak, recovery) ──
    data = itlg.get_user_info(tk, device_id)
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
        ref_dir = ti.get("directReferralsHashRate", 0) or 0
        ref_ind = ti.get("indirectReferralsHashRate", 0) or 0
        refs_str = f"{round(ref_dir + ref_ind, 2)} ({total_ref} refs)"
        streak = ti.get("burningStreak", 0)
        burned = ti.get("burnedCycles", 0)
        streak_str = f"{streak} / {burned}"
        recover_str = f"{ti.get('itlgRecoverable', 0)} ITLG"

        # Last claim time from API
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

    # ── Group mining ──
    gdata = itlg.get_group_mining_list(tk, device_id)
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

    # ── Recovery ──
    can_recover, total_recover = itlg.check_recovery(tk, device_id)
    recovery_status = f"{total_recover} ITLG" if can_recover else "Nothing to recover"

    # ── Bot status ──
    pid = bot_pid()
    bot_status = f"✅ Running (PID {pid})" if pid else "❌ Stopped"

    send(cid,
        f"📊 <b>ITLG Dashboard</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance      <b>{bal}</b> ITLG\n"
        f"⛏️ Mining       {mining_str}\n"
        f"📈 Per claim    {per_claim_str}\n"
        f"📈 Per day      {per_day_str}\n"
        f"🎯 Last claim   {last_claim_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Referrals    {refs_str}\n"
        f"🔥 Streak/Burn  {streak_str}\n"
        f"💎 Recoverable  {recover_str}\n"
        f"♻️ Recovery      {recovery_status}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Group        {group_str}\n"
        f"⏳ Group next   {group_next_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Bot          {bot_status}\n"
        f"🕐 {fmt_wib()} WIB",
        token)

def cmd_balance(cid, token):
    cfg = load_config()
    tk = get_valid_token(cfg)
    if not tk:
        send(cid, "❌ No valid token. Run: <code>python3 bot.py --login-face</code>", token)
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
        send(cid, "❌ No valid token. Run: <code>python3 bot.py --login-face</code>", token)
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
        send(cid, "❌ No valid token. Run: <code>python3 bot.py --login-face</code>", token)
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

COMMANDS = {
    "/start": cmd_start, "/help": cmd_help, "/status": cmd_status,
    "/balance": cmd_balance, "/claim": cmd_claim,
    "/groupclaim": cmd_groupclaim,
    "/stop": cmd_stop, "/restart": cmd_restart,
}

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("🤖 ITLG Telegram Gateway v2.1")
    print("  ☕ https://saweria.co/febfrmn\n")

    cfg = load_config()
    token = cfg.get("tgBotToken")
    owner = cfg.get("tgChatId")

    if not token:
        print("❌ tgBotToken not set. Run: python3 setup.py")
        sys.exit(1)

    try:
        r = urllib.request.urlopen(
            f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        name = json.loads(r.read())["result"]["username"]
        print(f"✅ Bot: @{name}")
    except Exception as e:
        print(f"❌ Invalid token: {e}")
        sys.exit(1)

    print(f"👤 Owner: {owner}")
    print(f"🤖 Bot: {'Running' if bot_pid() else 'Stopped'}")
    print(f"Listening...\n")

    offset = None
    while True:
        updates = poll(token, offset)
        if not updates or not updates.get("ok"):
            time.sleep(2)
            continue
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
                send(cid, f"Unknown command. Tap /help", token)

if __name__ == "__main__":
    main()
