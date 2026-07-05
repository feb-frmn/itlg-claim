#!/usr/bin/env python3
"""
Interlink Labs cron checker — auto-claim + Telegram notification.

Designed to run via cronjob every 5 minutes.
Checks if claim is available, claims it, sends Telegram notification with
claimed amount and current rate per 4h cycle.

Usage:
  python check_claim.py

Requires: config.json with tgBotToken + tgChatId (optional, skips notif if absent)
         token.json with valid access/refresh token (run bot.py --login first)
"""

import os, sys, json, time, hashlib, base64
from datetime import datetime

import requests
import urllib3
urllib3.disable_warnings()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_BASE   = "https://prod.interlinklabs.ai/api/v1"
APP_VER    = "5.0.0"

CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
TOKEN_FILE  = os.path.join(SCRIPT_DIR, "token.json")


def headers(token=None, device_id=None):
    h = {
        "User-Agent": "okhttp/4.12.0",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "version": APP_VER,
        "x-platform": "android",
        "x-model": "Redmi Note 8 Pro",
        "x-brand": "XiaoMi",
        "x-system-name": "Android",
        "x-bundle-id": "org.ai.interlinklabs.interlinkId",
    }
    if device_id:
        h["x-unique-id"] = device_id
        h["x-device-id"] = device_id
    if token:
        h["Authorization"] = f"Bearer {token}"
    h["x-date"] = str(int(time.time() * 1000))
    return h


def api_get(path, token, device_id, params=None):
    return requests.get(f"{API_BASE}{path}", params=params,
                        headers=headers(token, device_id), verify=False, timeout=30)


def api_post(path, data, token=None, device_id=None):
    h = headers(token, device_id)
    body = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
    h["x-content-hash"] = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    return requests.post(f"{API_BASE}{path}", data=body, headers=h, verify=False, timeout=30)


def jwt_exp(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except Exception:
        return None


def token_expired(token, buffer=300):
    exp = jwt_exp(token)
    if not exp:
        return True
    return time.time() >= (exp - buffer)


def load_config():
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    if not cfg.get("deviceId"):
        cfg["deviceId"] = hashlib.md5(str(cfg["loginId"]).encode()).hexdigest()[:16]
    return cfg


def load_tokens():
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        return data.get("access"), data.get("refresh")
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None


def save_tokens(access, refresh):
    backup = os.path.join(SCRIPT_DIR, "token-backup.json")
    for path in (TOKEN_FILE, backup):
        with open(path, "w") as f:
            json.dump({"access": access, "refresh": refresh or "",
                       "saved_at": int(time.time())}, f)
        os.chmod(path, 0o600)


def refresh_token(cfg, refresh):
    if not refresh:
        return None
    try:
        r = api_post("/auth/token", {"refreshToken": refresh}, device_id=cfg["deviceId"])
        d = r.json()
        if d.get("statusCode") == 200:
            data = d.get("data", {})
            new_access = data.get("accessToken") or data.get("jwtToken")
            new_refresh = data.get("refreshToken")
            if new_access:
                save_tokens(new_access, new_refresh or refresh)
                return new_access
    except Exception:
        pass
    return None


def get_session(cfg):
    access, refresh = load_tokens()
    if access and not token_expired(access):
        return access
    if refresh:
        return refresh_token(cfg, refresh)
    return None


def get_user_info(token, device_id):
    r = api_get("/auth/current-user-full?include=userInfo,token,isClaimable",
                token, device_id)
    d = r.json()
    return d.get("data") if d.get("statusCode") == 200 else None


def check_claimable(token, device_id):
    r = api_get("/token/check-is-claimable", token, device_id)
    return r.json().get("data", {})


def claim_airdrop(token, device_id):
    return api_post("/token/claim-airdrop", {}, token=token, device_id=device_id).json()


def trigger_ads(token, device_id, last_claim):
    try:
        r = api_get(f"/token/get-random-ads-mining-new?totalHhp=1&lastTimeClaim={last_claim}",
                    token, device_id)
        d = r.json()
        if d.get("statusCode") == 200:
            return d.get("data", {}).get("timeRetry", 10) or 10
    except Exception:
        pass
    return 10


def get_rates(ti):
    mining   = ti.get("dailyMiningRate", 0) or 0
    grp      = ti.get("groupMiningRate", 0) or 0
    ref_dir  = ti.get("directReferralsHashRate", 0) or 0
    ref_ind  = ti.get("indirectReferralsHashRate", 0) or 0
    total    = mining + grp + ref_dir + ref_ind
    return {
        "total": total,
        "rate_4h": round(total / 6, 2) if total else 0,
    }


def send_telegram(cfg, text):
    bot_token = cfg.get("tgBotToken")
    chat_id = cfg.get("tgChatId")
    if not bot_token or not chat_id:
        return
    import urllib.parse
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = f"chat_id={urllib.parse.quote(chat_id)}&text={urllib.parse.quote(text)}"
    try:
        requests.post(url, data=payload,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      timeout=10, verify=False)
    except Exception:
        pass


def main():
    cfg = load_config()
    token = get_session(cfg)
    if not token:
        print(f"[{datetime.now():%H:%M:%S}] No valid token. Run bot.py --login")
        return

    device_id = cfg["deviceId"]
    ic = check_claimable(token, device_id)

    if not ic.get("isClaimable"):
        # Silent — cron stays quiet when nothing to claim
        return

    # Claimable — capture balance before
    user = get_user_info(token, device_id)
    if not user:
        return
    ti = user.get("token", {})
    balance_before = ti.get("interlinkGoldTokenAmount", 0)
    last_claim = ti.get("lastClaimTime") or int(time.time() * 1000)

    # Trigger ads + claim
    wait = trigger_ads(token, device_id, last_claim)
    time.sleep(wait + 5)
    result = claim_airdrop(token, device_id)
    status = result.get("statusCode")

    if status == 200:
        time.sleep(2)
        user2 = get_user_info(token, device_id)
        balance_after = user2.get("token", {}).get("interlinkGoldTokenAmount", 0) if user2 else 0
        claimed = balance_after - balance_before
        rates = get_rates(ti)
        now = datetime.now().strftime("%H:%M:%S")
        # This goes to stdout → cron delivers to Telegram
        print(
            f"✅ ITLG Claim Success\n\n"
            f"💰 Claimed: +{claimed} ITLG\n"
            f"📊 Balance: {balance_before} → {balance_after} ITLG\n"
            f"⏱️ Rate: {rates['rate_4h']}/4h ({rates['total']}/day)\n"
            f"🕐 {now}\n\n"
            f"Next claim in 4h."
        )
        # Also try direct Telegram if configured
        send_telegram(cfg, (
            f"✅ ITLG Claim Success\n\n"
            f"💰 Claimed: +{claimed} ITLG\n"
            f"📊 Balance: {balance_before} → {balance_after} ITLG\n"
            f"⏱️ Rate: {rates['rate_4h']}/4h ({rates['total']}/day)\n"
            f"🕐 {now}\n\n"
            f"Next claim in 4h."
        ))
    elif status == 400 and "TOO_EARLY" in str(result.get("message", "")).upper():
        # Silent — already claimed
        pass
    else:
        msg = result.get("message", "unknown")
        print(f"❌ ITLG Claim failed ({status}): {msg}")


if __name__ == "__main__":
    main()
