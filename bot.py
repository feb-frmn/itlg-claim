#!/usr/bin/env python3
"""
Interlink Labs Auto Claim — single account, login once, claim forever.

Usage:
  python bot.py              # loop mode (live countdown, auto-claim every 4h)
  python bot.py --once        # single run, check + claim if available, exit
  python bot.py --login       # force re-login (trigger OTP)
  python bot.py --login-face --photo selfie.jpg  # face login with photo file

The bot auto-claims every 4h and sends a Telegram notification on success
(if tgBotToken + tgChatId are set in config.json).

Config: config.json (run `python setup.py` for interactive setup)
"""

import sys, os, json, time, imaplib, email, re, hashlib, base64, argparse, random
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
import urllib3
urllib3.disable_warnings()

# ─── WIB timezone (UTC+7) ─────────────────────────────────────────────────────
WIB = timezone(timedelta(hours=7))
def now_wib():
    """Current time in WIB (Asia/Jakarta)."""
    return datetime.now(WIB)
def fmt_wib(fmt="%Y-%m-%d %H:%M:%S"):
    """Formatted WIB timestamp string."""
    return now_wib().strftime(fmt)

# ─── Config ───────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_BASE   = "https://prod.interlinklabs.ai/api/v1"
APP_VER    = "5.0.5"
CLAIM_INTERVAL = 4 * 60 * 60
OTP_TIMEOUT    = 180  # 3 minutes — Interlink can be slow to send OTP
OTP_POLL_DELAY = 5

CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
TOKEN_FILE  = os.path.join(SCRIPT_DIR, "token.json")
STATE_FILE  = os.path.join(SCRIPT_DIR, "claim_state.json")

# ─── Colors ───────────────────────────────────────────────────────────────────
class C:
    R = "\033[0m";  B = "\033[1m"
    RED = "\033[31m"; GR = "\033[32m"
    YLW = "\033[33m"; CY = "\033[36m"
    DIM = "\033[2m"

def log(ok, msg):
    icon = {"ok":"✅","err":"❌","warn":"⚠️","info":"ℹ️","step":"➡️"}[ok]
    line = f"{icon} {msg}"
    if ok == "err":   line = f"{C.RED}{line}{C.R}"
    elif ok == "ok":  line = f"{C.GR}{line}{C.R}"
    elif ok == "warn": line = f"{C.YLW}{line}{C.R}"
    elif ok == "info": line = f"{C.DIM}{line}{C.R}"
    elif ok == "step": line = f"{C.CY}{line}{C.R}"
    print(line)

# ─── Config loader ─────────────────────────────────────────────────────────────
def load_config():
    if not os.path.exists(CONFIG_FILE):
        log("err", "config.json not found. Run: python setup.py")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        cfg = json.load(f)
    if not cfg.get("deviceId"):
        import secrets
        cfg["deviceId"] = secrets.token_hex(8)  # random Android ANDROID_ID format
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    # Pick a random device fingerprint if not already set (sticks for this account)
    if not cfg.get("deviceModel"):
        devices = [
            ("Redmi Note 8 Pro", "XiaoMi"), ("Redmi Note 11", "XiaoMi"),
            ("SM-G991B", "samsung"), ("SM-A525F", "samsung"),
            ("Pixel 6", "Google"), ("Pixel 7", "Google"),
            ("CPH2247", "OPPO"), ("V2057A", "vivo"),
            ("RMX3081", "Realme"), ("M2101K6G", "POCO"),
        ]
        dev = random.choice(devices)
        cfg["deviceModel"] = dev[0]
        cfg["deviceBrand"] = dev[1]
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    return cfg

# ─── Token store ────────────────────────────────────────────────────────────────
def save_tokens(access, refresh):
    data = {"access": access, "refresh": refresh or "", "saved_at": int(time.time())}
    for path in (TOKEN_FILE, os.path.join(SCRIPT_DIR, "token-backup.json")):
        with open(path, "w") as f:
            json.dump(data, f)
        os.chmod(path, 0o600)

def load_tokens():
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        return data.get("access"), data.get("refresh")
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None

# ─── Claim state (actual claim amounts) ───────────────────────────────────────
def save_claim_state(claimed=None, balance=None):
    state = load_claim_state()
    if claimed is not None:
        state["last_claim"] = claimed
        state["history"] = (state.get("history", []) + [claimed])[-10:]
    if balance is not None:
        state["balance"] = balance
    state["updated_at"] = int(time.time())
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        os.chmod(STATE_FILE, 0o600)
    except Exception:
        pass

def load_claim_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"history": [], "last_claim": 0, "balance": 0}

def get_actual_rate(state):
    """Compute actual per-claim and per-day from claim history."""
    history = state.get("history", [])
    if not history:
        return 0, 0
    avg = sum(history) / len(history)
    return round(avg, 1), round(avg * 6, 1)  # 6 cycles per day (4h each)

# ─── JWT helpers ────────────────────────────────────────────────────────────────
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

# ─── HTTP ─────────────────────────────────────────────────────────────────────
def headers(token=None, device_id=None, cfg=None):
    model = "Redmi Note 8 Pro"
    brand = "XiaoMi"
    if cfg:
        model = cfg.get("deviceModel", model)
        brand = cfg.get("deviceBrand", brand)
    h = {
        "User-Agent": "okhttp/4.12.0",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "version": APP_VER,
        "x-platform": "android",
        "x-model": model,
        "x-brand": brand,
        "x-system-name": "Android",
        "x-bundle-id": "org.ai.interlinklabs.interlinkId",
    }
    if device_id:
        h["x-unique-id"] = device_id
        h["x-device-id"] = device_id
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def safe_json(r):
    """Parse JSON response safely, return {} on failure."""
    try:
        return r.json()
    except Exception:
        return {}

def api_get(path, token, device_id, params=None, cfg=None):
    h = headers(token, device_id, cfg)
    h["x-date"] = str(int(time.time() * 1000))
    return requests.get(f"{API_BASE}{path}", params=params, headers=h, verify=False, timeout=30)

def api_post(path, data, token=None, device_id=None, cfg=None):
    h = headers(token, device_id, cfg)
    h["x-date"] = str(int(time.time() * 1000))
    body = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
    h["x-content-hash"] = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    return requests.post(f"{API_BASE}{path}", data=body, headers=h, verify=False, timeout=30)

# ─── Login flow (ONE-TIME ONLY) ────────────────────────────────────────────────
def check_login_id(cfg):
    r = api_get(f"/auth/loginId-exist-check/{cfg['loginId']}", token=None,
                device_id=cfg["deviceId"], params={"deviceId": cfg["deviceId"]})
    return safe_json(r).get("statusCode") == 200

def check_passcode(cfg):
    r = api_post("/auth/check-passcode?v=2",
                 {"loginId": str(cfg["loginId"]), "passcode": str(cfg["passcode"]), "deviceId": cfg["deviceId"]},
                 device_id=cfg["deviceId"])
    d = safe_json(r)
    if d.get("statusCode") == 200:
        data = d.get("data", {})
        return data.get("email") or (data.get("verificationInfo") or [{}])[0].get("gmail")
    return None

def send_otp(cfg, email_addr):
    r = api_post("/auth/send-otp-email-verify-login",
                 {"loginId": str(cfg["loginId"]), "passcode": str(cfg["passcode"]),
                  "email": email_addr, "deviceId": cfg["deviceId"]},
                 device_id=cfg["deviceId"])
    d = safe_json(r)
    return r.status_code == 200 and d.get("statusCode") == 200

def grab_otp(cfg, email_addr, after_ts):
    """Poll IMAP for a fresh login OTP. Only accept emails sent after after_ts."""
    time.sleep(5)
    deadline = time.time() + OTP_TIMEOUT
    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(email_addr, cfg["imapPassword"])
            mail.select("inbox")
            _, msgs = mail.search(None, "ALL")
            for eid in reversed(msgs[0].split()[-10:]):
                _, msg_data = mail.fetch(eid, "(RFC822)")
                for part in msg_data:
                    if not isinstance(part, tuple):
                        continue
                    msg = email.message_from_bytes(part[1])
                    # Reject old emails
                    try:
                        if parsedate_to_datetime(msg.get("Date", "")).timestamp() < after_ts - 30:
                            continue
                    except Exception:
                        pass
                    # Must be "Login Verification" (not "Email Change")
                    subj = str(msg.get("Subject", ""))
                    if "login" not in subj.lower() and "verification code" not in subj.lower():
                        continue
                    body = ""
                    if msg.is_multipart():
                        for p in msg.walk():
                            ct = p.get_content_type()
                            if ct == "text/plain":
                                try: body = p.get_payload(decode=True).decode(errors="ignore")
                                except: pass
                            elif ct == "text/html" and not body:
                                try: body = p.get_payload(decode=True).decode(errors="ignore")
                                except: pass
                    else:
                        try: body = msg.get_payload(decode=True).decode(errors="ignore")
                        except: pass
                    matches = re.findall(r"\b(\d{6})\b", body or "")
                    if matches:
                        mail.logout()
                        return matches[0]
            mail.logout()
        except Exception as e:
            log("warn", f"IMAP error: {e}")
        time.sleep(OTP_POLL_DELAY)
    return None

def verify_otp(cfg, otp):
    r = api_post("/auth/check-otp-email-verify-login?v=2",
                 {"loginId": str(cfg["loginId"]), "otp": otp, "deviceId": cfg["deviceId"]},
                 device_id=cfg["deviceId"])
    d = safe_json(r)
    if d.get("statusCode") == 200:
        data = d.get("data", {})
        return data.get("accessToken"), data.get("refreshToken")
    return None, None

def do_login(cfg):
    """Full OTP login. Returns (access, refresh) or (None, None)."""
    log("step", "Checking login ID...")
    if not check_login_id(cfg):
        log("err", f"Login ID {cfg['loginId']} not found.")
        return None, None

    log("step", "Checking passcode...")
    found_email = check_passcode(cfg)
    if not found_email and not cfg.get("email"):
        log("err", "Passcode wrong and no email in config.")
        return None, None
    email_addr = found_email or cfg["email"]
    log("ok", f"Account email: {email_addr}")

    if not cfg.get("imapPassword"):
        log("err", "imapPassword not set in config.json")
        return None, None

    for attempt in range(3):
        send_ts = time.time()
        log("step", f"Sending OTP (attempt {attempt+1}/3)...")
        if not send_otp(cfg, email_addr):
            time.sleep(5)
            continue
        log("info", "Waiting for OTP email...")
        otp = grab_otp(cfg, email_addr, send_ts)
        if not otp:
            continue
        log("step", f"Verifying OTP {otp}...")
        access, refresh = verify_otp(cfg, otp)
        if access:
            log("ok", "Login successful!")
            save_tokens(access, refresh)
            log("info", "Token saved to token.json + token-backup.json")
            return access, refresh
        log("warn", "OTP expired, resending...")

    log("err", "Login failed after 3 attempts.")
    return None, None

# ─── Face Login (selfie photo, alternative to OTP) ───────────────────────────
def get_presigned_login(cfg):
    """Get presigned URL for face photo upload."""
    r = api_post("/s3/face/presigned-login",
                 {"loginId": str(cfg["loginId"]), "passcode": str(cfg["passcode"])},
                 device_id=cfg["deviceId"])
    return safe_json(r)

def upload_face(upload_url, face_data):
    """Upload face photo to presigned URL."""
    try:
        import urllib3
        urllib3.disable_warnings()
        r = requests.put(upload_url, data=face_data,
                        headers={"Content-Type": "image/png"}, timeout=30, verify=False)
        return r.status_code == 200
    except Exception:
        return False

def login_with_face(cfg, image_key):
    """Login using face image key."""
    r = api_post("/auth/login",
                 {"loginId": str(cfg["loginId"]),
                  "passcode": str(cfg["passcode"]),
                  "image": image_key,
                  "presignedUrlImage": image_key},
                 device_id=cfg["deviceId"])
    return safe_json(r)

def do_face_login(cfg, photo_override=None):
    """Full face login flow: verify passcode → get presigned URL → upload photo → login.
    Args:
        cfg: config dict
        photo_override: if set, use this photo path instead of cfg['facePhoto']
    Returns (access_token, refresh_token) or (None, None).
    """
    lid = cfg.get("loginId", "")
    pwd = cfg.get("passcode", "")
    photo_path = photo_override or cfg.get("facePhoto", "")

    if not all([lid, pwd]):
        log("err", "Missing loginId or passcode in config.")
        return None, None

    if not photo_path or not os.path.exists(photo_path):
        log("err", f"Face photo not found: {photo_path}")
        log("info", "Run: python setup.py (isi facePhoto path)")
        return None, None

    # Step 1: Verify passcode
    log("step", "Verifying passcode...")
    check = check_passcode(cfg)
    if not check:
        log("err", "Invalid passcode.")
        return None, None
    log("ok", f"User verified: {check}")

    # Step 2: Read face photo
    try:
        with open(photo_path, "rb") as f:
            face_data = f.read()
        log("step", f"Loaded face photo: {photo_path} ({len(face_data)} bytes)")
    except Exception as e:
        log("err", f"Cannot read photo: {e}")
        return None, None

    # Step 3: Get presigned URL
    log("step", "Getting presigned upload URL...")
    presign = get_presigned_login(cfg)
    if presign.get("statusCode") != 200:
        log("err", f"Presign failed: {presign.get('message', '')}")
        return None, None

    try:
        image_data = presign["data"]["image"]
        image_key = image_data["key"]
        upload_url = image_data["uploadUrl"]
        log("ok", f"Got presigned URL (key: {image_key[:30]}...)")
    except (KeyError, TypeError) as e:
        log("err", f"Unexpected presign response: {e}")
        return None, None

    # Step 4: Upload face photo
    log("step", "Uploading face photo...")
    if not upload_face(upload_url, face_data):
        log("err", "Face photo upload failed.")
        return None, None
    log("ok", "Face photo uploaded.")

    # Step 5: Login with face
    log("step", "Verifying face + logging in...")
    result = login_with_face(cfg, image_key)

    # Extract tokens from response
    data = result.get("data", {})
    token = None
    refresh_tok = None

    if isinstance(data, dict):
        token = data.get("accessToken") or data.get("token") or data.get("access_token")
        refresh_tok = data.get("refreshToken") or data.get("refresh_token")

    if not token:
        for k in ["token", "accessToken", "access_token"]:
            if k in result:
                token = result[k]
    if not refresh_tok:
        for k in ["refreshToken", "refresh_token"]:
            if k in result:
                refresh_tok = result[k]

    if token:
        log("ok", "Face login successful!")
        save_tokens(token, refresh_tok)
        log("info", f"Token saved. Refresh: {'YES' if refresh_tok else 'NO'}")
        return token, refresh_tok

    # Check for specific errors
    msg = result.get("message", "")
    if "E304" in str(msg):
        log("err", "FACE MISMATCH! Selfie doesn't match registration photo.")
    else:
        log("err", f"Face login failed: {msg}")
    return None, None

# ─── Refresh ──────────────────────────────────────────────────────────────────
def do_refresh(cfg, refresh_token):
    if not refresh_token:
        return None
    log("step", "Refreshing token...")
    try:
        r = api_post("/auth/token", {"refreshToken": refresh_token}, device_id=cfg["deviceId"])
        d = safe_json(r)
        if d.get("statusCode") == 200:
            data = d.get("data", {})
            new_access = data.get("accessToken") or data.get("jwtToken")
            new_refresh = data.get("refreshToken")
            if new_access:
                log("ok", "Token refreshed.")
                save_tokens(new_access, new_refresh or refresh_token)
                return new_access
    except Exception as e:
        log("warn", f"Refresh error: {e}")
    return None

# ─── Get session (login once, never logout) ────────────────────────────────────
def get_session(cfg, allow_login=True):
    """Get a valid access token. Order: stored → refresh → face login → OTP login."""
    access, refresh = load_tokens()
    if access and not token_expired(access):
        return access
    if refresh:
        new_access = do_refresh(cfg, refresh)
        if new_access:
            return new_access
    if not allow_login:
        log("warn", "No valid token. Run: python bot.py --login or --login-face")
        return None
    # Try face login first (if facePhoto configured)
    if cfg.get("facePhoto") and os.path.exists(cfg["facePhoto"]):
        log("warn", "No valid token. Trying face login...")
        access, refresh = do_face_login(cfg)
        if access:
            return access
        log("warn", "Face login failed. Trying OTP...")
    else:
        log("warn", "No valid token. Triggering OTP login...")
    access, refresh = do_login(cfg)
    return access

# ─── API helpers ──────────────────────────────────────────────────────────────
def get_user_info(token, device_id):
    r = api_get("/auth/current-user-full?include=userInfo,token,isClaimable", token, device_id)
    d = safe_json(r)
    return d.get("data") if d.get("statusCode") == 200 else None

def check_claimable(token, device_id):
    r = api_get("/token/check-is-claimable", token, device_id)
    return safe_json(r).get("data", {})

def get_balance(token, device_id):
    data = get_user_info(token, device_id)
    return data.get("token", {}).get("interlinkGoldTokenAmount", 0) if data else None

def trigger_ads(token, device_id, last_claim):
    try:
        r = api_get(f"/token/get-random-ads-mining-new?totalHhp=1&lastTimeClaim={last_claim}", token, device_id)
        d = safe_json(r)
        if d.get("statusCode") == 200:
            return d.get("data", {}).get("timeRetry", 10) or 10
    except Exception:
        pass
    return 10

def claim_airdrop(token, device_id):
    r = api_post("/token/claim-airdrop", {}, token=token, device_id=device_id)
    return safe_json(r)

# ─── Recovery (burn cycle recovery, check every claim cycle) ──────────────────
def check_recovery(token, device_id):
    """Check if any burned ITLG is recoverable right now."""
    r = api_get("/recovery/total-recoverable", token, device_id)
    d = safe_json(r)
    if d.get("statusCode") == 200:
        data = d.get("data", {})
        return data.get("canRecover", False), data.get("totalRecoverable", 0)
    return False, 0

def get_recoverable_burns(token, device_id):
    """Get list of burn transactions that can be recovered."""
    r = api_get("/recovery/my", token, device_id)
    d = safe_json(r)
    if d.get("statusCode") == 200:
        burns = d.get("data", {}).get("data", [])
        return [b for b in burns if b.get("isRecoverable")]
    return []

def attempt_recovery(cfg, token):
    """Check + claim recovery if available. Returns (token, recovered_amount)."""
    device_id = cfg["deviceId"]
    can_recover, total = check_recovery(token, device_id)
    if not can_recover or total <= 0:
        return token, 0

    log("ok", f"Recovery available! {total} ITLG recoverable. Fetching burn transactions...")
    burns = get_recoverable_burns(token, device_id)
    if not burns:
        log("info", "Recovery: canRecover=true but no recoverable burns found. Trying next cycle.")
        return token, 0

    balance_before = get_balance(token, device_id)
    recovered_total = 0
    for burn in burns:
        tid = burn.get("transactionId")
        if not tid:
            continue
        log("step", f"Recovering burn: {tid} ({burn.get('amount', 0)} ITLG)...")
        r = api_post("/recovery/claim", {"transactionId": tid}, token=token, device_id=device_id)
        result = safe_json(r)
        status = result.get("statusCode")
        msg = result.get("message", "")
        if status == 200 or status == 201:
            amt = burn.get("amount", 0)
            recovered_total += amt
            log("ok", f"Recovered! +{amt} ITLG from {tid}")
            time.sleep(2)
        else:
            log("warn", f"Recovery failed for {tid}: {msg}")

    if recovered_total > 0:
        time.sleep(2)
        balance_after = get_balance(token, device_id)
        log("ok", f"Recovery complete! +{recovered_total} ITLG recovered")
        if balance_before is not None and balance_after is not None:
            log("info", f"Balance: {balance_before} → {balance_after} ITLG")
        try:
            send_telegram_notif(cfg, {
                "claimed": recovered_total,
                "before": balance_before,
                "after": balance_after,
                "rate_per_claim": recovered_total,
                "rate_per_day": None,
                "group_rate": 0,
            })
        except Exception:
            pass
    return token, recovered_total

# ─── Group mining (24h cycle, 1 claim = all groups) ───────────────────────────
GROUP_INTERVAL = 24 * 60 * 60  # 24 hours

def get_group_mining_list(token, device_id):
    """Get list of all groups + next claim time."""
    r = api_post("/group-mining/get-list-group-mining", {}, token=token, device_id=device_id)
    d = safe_json(r)
    return d.get("data") if d.get("statusCode") == 200 else None

def claim_group_mining(token, device_id, group_id):
    """Claim group mining for one group (claims ALL groups at once)."""
    r = api_post("/group-mining/claim-group-mining", {"groupId": group_id}, token=token, device_id=device_id)
    return safe_json(r)

def attempt_group_claim(cfg, token):
    """Check + claim group mining (24h cycle). Returns (token, claimed, next_time_ms)."""
    device_id = cfg["deviceId"]
    data = get_group_mining_list(token, device_id)
    if not data:
        log("err", "Failed to fetch group mining list.")
        return token, False, None

    groups = data.get("groups", [])
    is_claimable = data.get("isClaimable", False)
    next_time = data.get("nextTimeClaim")
    already_claimed = data.get("requesterHasClaimedToday", False)

    # Find a claimable group
    claimable_group = None
    total_reward = 0
    for g in groups:
        total_reward += g.get("totalReward", 0)
        if g.get("canClaim"):
            claimable_group = g
            break

    if not claimable_group:
        if already_claimed:
            log("info", f"Group mining: already claimed today. {len(groups)} groups, total reward pool: {total_reward} ITLG")
        else:
            log("info", f"Group mining: not ready yet. {len(groups)} groups, total reward pool: {total_reward} ITLG")
        return token, False, next_time

    gid = claimable_group["groupId"]
    log("ok", f"Group mining claimable! Group: {gid} ({len(groups)} groups, pool: {total_reward} ITLG)")

    # Human-like delay
    jitter = random.randint(30, 120)
    log("info", f"Waiting {jitter}s before group claim (human-like)...")
    time.sleep(jitter)

    balance_before = get_balance(token, device_id)
    result = claim_group_mining(token, device_id, gid)
    status = result.get("statusCode")
    msg = result.get("message", "")

    if status == 200:
        time.sleep(2)
        balance_after = get_balance(token, device_id)
        claimed = (balance_after - balance_before) if balance_before is not None and balance_after is not None else None
        log("ok", f"Group mining claimed! +{claimed if claimed is not None else '?'} ITLG")
        if balance_before is not None and balance_after is not None:
            log("info", f"Balance: {balance_before} → {balance_after} ITLG")
        # Telegram notification
        try:
            send_telegram_notif(cfg, {
                "claimed": claimed,
                "before": balance_before,
                "after": balance_after,
                "rate_per_claim": claimed or 0,
                "rate_per_day": None,
                "group_rate": total_reward,
            })
        except Exception as e:
            log("warn", f"Telegram notif failed: {e}")
        return token, True, next_time

    if status == 400 and "ALREADY_CLAIMED" in str(msg).upper():
        log("info", "Group mining: already claimed today.")
        return token, False, next_time

    log("err", f"Group mining claim failed ({status}): {msg}")
    return token, False, next_time

# ─── Rates ────────────────────────────────────────────────────────────────────
def get_rates(ti, state=None):
    """Extract rate info for dashboard + notifications."""
    mining   = ti.get("dailyMiningRate", 0) or 0
    group    = ti.get("groupMiningRate", 0) or 0
    ref_dir  = ti.get("directReferralsHashRate", 0) or 0
    ref_ind  = ti.get("indirectReferralsHashRate", 0) or 0
    actual_per_claim, actual_per_day = (0, 0)
    if state:
        actual_per_claim, actual_per_day = get_actual_rate(state)
    return {
        "mining": mining, "group": group,
        "ref_dir": ref_dir, "ref_ind": ref_ind,
        "actual_per_claim": actual_per_claim,
        "actual_per_day": actual_per_day,
        "has_history": actual_per_claim > 0,
    }

# ─── Dashboard ─────────────────────────────────────────────────────────────────
def show_dashboard(token, device_id):
    data = get_user_info(token, device_id)
    if not data:
        log("err", "Failed to fetch user info.")
        return None, None
    ui = data.get("userInfo", {})
    ti = data.get("token", {})
    ic = data.get("isClaimable", {})
    state = load_claim_state()
    rates = get_rates(ti, state)
    gold        = ti.get("interlinkGoldTokenAmount", 0)
    total_ref   = ti.get("totalReferral", 0)
    streak      = ti.get("burningStreak", 0)
    burned      = ti.get("burnedCycles", 0)
    recoverable = ti.get("itlgRecoverable", 0)
    has_group   = rates["group"] > 0
    W = 38
    print()
    print(f"  {C.B}╔{'═'*W}╗{C.R}")
    print(f"  {C.B}║{C.R}  {ui.get('username', 'N/A')[:30]:<34}  {C.B}║{C.R}")
    print(f"  {C.B}╠{'═'*W}╣{C.R}")
    print(f"  {C.B}║{C.R}  ITLG Balance   {str(gold):>28}  {C.B}║{C.R}")
    print(f"  {C.B}║{C.R}  Last claim     {str(state.get('last_claim', 0)) + ' ITLG':>28}  {C.B}║{C.R}")
    if rates["has_history"]:
        print(f"  {C.B}║{C.R}  Per claim      {str(rates['actual_per_claim']) + ' ITLG':>28}  {C.B}║{C.R}")
        print(f"  {C.B}║{C.R}  Per day        {str(rates['actual_per_day']) + ' ITLG':>28}  {C.B}║{C.R}")
    else:
        print(f"  {C.B}║{C.R}  Per claim      {'waiting first claim':>28}  {C.B}║{C.R}")
        print(f"  {C.B}║{C.R}  Per day        {'waiting first claim':>28}  {C.B}║{C.R}")
    if has_group:
        print(f"  {C.B}║{C.R}  Group          {str(rates['group']) + '/day':>28}  {C.B}║{C.R}")
    else:
        print(f"  {C.B}║{C.R}  Group          {'pending activation':>28}  {C.B}║{C.R}")
    print(f"  {C.B}║{C.R}  Referral       {str(round(rates['ref_dir'] + rates['ref_ind'], 2)) + f' ({total_ref} refs)':>28}  {C.B}║{C.R}")
    print(f"  {C.B}║{C.R}  Streak/Burned  {f'{streak} / {burned}':>28}  {C.B}║{C.R}")
    if recoverable and recoverable > 0:
        print(f"  {C.B}║{C.R}  Recoverable    {str(recoverable) + ' ITLG':>28}  {C.B}║{C.R}")
    print(f"  {C.B}╚{'═'*W}╝{C.R}")
    return ic, ti

def format_countdown(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}h {m:02d}m {s:02d}s"

# ─── Telegram notification ────────────────────────────────────────────────────
def send_telegram_notif(cfg, info):
    """Send a Telegram message after successful claim."""
    bot_token = cfg.get("tgBotToken")
    chat_id = cfg.get("tgChatId")
    if not bot_token or not chat_id:
        return
    import urllib.parse
    claimed = info.get("claimed")
    before = info.get("before")
    after = info.get("after")
    per_claim = info.get("rate_per_claim", 0)
    per_day = info.get("rate_per_day")
    group_rate = info.get("group_rate", 0)
    now = fmt_wib("%H:%M:%S WIB")
    day_line = f"\n📈 Per day: ~{per_day} ITLG (6 claims)" if per_day else ""
    group_line = f"\n👥 Group: {group_rate}/day (active!)" if group_rate > 0 else "\n👥 Group: pending activation"
    text = (
        f"✅ ITLG Claim Success\n\n"
        f"💰 Claimed: +{claimed} ITLG\n"
        f"📊 Balance: {before} → {after} ITLG\n"
        f"⏱️ Per claim: {per_claim} ITLG{day_line}{group_line}\n"
        f"🕐 {now}\n\n"
        f"Next claim in 4h."
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10, verify=False)
        if r.status_code == 200:
            log("ok", "Telegram notification sent.")
        else:
            log("warn", f"Telegram error: {r.status_code}")
    except Exception as e:
        log("warn", f"Telegram notif error: {e}")

# ─── Claim ─────────────────────────────────────────────────────────────────────
def attempt_claim(cfg, token):
    device_id = cfg["deviceId"]
    ic = check_claimable(token, device_id)
    if not ic.get("isClaimable"):
        nf = ic.get("nextFrame")
        if nf:
            remain = int((nf - time.time() * 1000) / 1000)
            log("info", f"Not claimable. Next in {format_countdown(max(0, remain))}")
        return token, False

    # Human-like delay: wait 30-120s before claiming (humans don't claim at 00:00:00)
    jitter = random.randint(30, 120)
    log("info", f"Claimable! Waiting {jitter}s before claiming (human-like)...")
    time.sleep(jitter)

    # Capture balance BEFORE claim
    balance_before = get_balance(token, device_id)
    user = get_user_info(token, device_id)
    if not user:
        return token, False
    ti = user.get("token", {})
    last_claim = ti.get("lastClaimTime") or int(time.time() * 1000)
    group_rate = ti.get("groupMiningRate", 0) or 0

    log("ok", "Claimable! Triggering ads...")
    wait = trigger_ads(token, device_id, last_claim)
    time.sleep(wait + 5)

    log("step", "Claiming...")
    result = claim_airdrop(token, device_id)
    status = result.get("statusCode")
    msg = result.get("message", "")

    if status == 200:
        time.sleep(2)
        balance_after = get_balance(token, device_id)
        claimed = (balance_after - balance_before) if balance_before is not None and balance_after is not None else None
        rates = get_rates(ti, load_claim_state())
        save_claim_state(claimed=claimed, balance=balance_after)
        log("ok", f"Claimed! +{claimed if claimed is not None else '?'} ITLG")
        log("info", f"Balance: {balance_before} → {balance_after} ITLG")
        if rates["has_history"]:
            log("info", f"Avg per claim: {rates['actual_per_claim']} | Per day: {rates['actual_per_day']} ITLG")
        else:
            log("info", f"First claim recorded: {claimed} ITLG")
        try:
            send_telegram_notif(cfg, {
                "claimed": claimed,
                "before": balance_before,
                "after": balance_after,
                "rate_per_claim": rates["actual_per_claim"] if rates["has_history"] else claimed,
                "rate_per_day": rates["actual_per_day"] if rates["has_history"] else None,
                "group_rate": group_rate,
            })
        except Exception as e:
            log("warn", f"Telegram notif failed: {e}")
        show_dashboard(token, device_id)
        return token, True

    if status == 400 and "TOO_EARLY" in str(msg).upper():
        log("info", "Already claimed (maybe manual?). Syncing next timer from API...")
        ic_new = check_claimable(token, device_id)
        nf = ic_new.get("nextFrame")
        if nf:
            remain = int((nf - time.time() * 1000) / 1000)
            log("info", f"Next claim in {format_countdown(max(0, remain))}")
        return token, False

    if status == 500:
        log("err", "Server error. Retrying in 10s...")
        time.sleep(10)
        result2 = claim_airdrop(token, device_id)
        if result2.get("statusCode") == 200:
            balance_after = get_balance(token, device_id)
            claimed = (balance_after - balance_before) if balance_before is not None and balance_after is not None else None
            rates = get_rates(ti, load_claim_state())
            save_claim_state(claimed=claimed, balance=balance_after)
            log("ok", f"Claimed on retry! +{claimed if claimed is not None else '?'} ITLG")
            try:
                send_telegram_notif(cfg, {
                    "claimed": claimed,
                    "before": balance_before,
                    "after": balance_after,
                    "rate_per_claim": rates["actual_per_claim"] if rates["has_history"] else claimed,
                    "rate_per_day": rates["actual_per_day"] if rates["has_history"] else None,
                    "group_rate": group_rate,
                })
            except Exception:
                pass
            show_dashboard(token, device_id)
            return token, True
        log("err", f"Retry failed: {result2.get('message', '')}")
        return token, False

    log("err", f"Claim failed ({status}): {msg}")
    return token, False

# ─── Run modes ──────────────────────────────────────────────────────────────────
def run_once(cfg):
    log("info", f"Run: {fmt_wib()}")
    token = get_session(cfg, allow_login=False)
    if not token:
        return
    ic, _ = show_dashboard(token, cfg["deviceId"])
    if ic and ic.get("isClaimable"):
        attempt_claim(cfg, token)
    else:
        nf = ic.get("nextFrame") if ic else None
        if nf:
            remain = int((nf - time.time() * 1000) / 1000)
            log("info", f"Mining next in {format_countdown(max(0, remain))}")

    # Group mining check
    log("info", "Checking group mining...")
    token, group_claimed, group_next = attempt_group_claim(cfg, token)
    if group_next:
        remain = int((group_next - time.time() * 1000) / 1000)
        log("info", f"Group mining next in {format_countdown(max(0, remain))}")

    # Recovery check
    log("info", "Checking recovery...")
    token, recovered = attempt_recovery(cfg, token)
    if recovered > 0:
        log("ok", f"Recovered {recovered} ITLG from burned cycles!")
    else:
        log("info", "Recovery: nothing to recover yet.")

def run_loop(cfg):
    log("info", "Loop mode. Mining 4h + Group mining 24h.")
    token = get_session(cfg)
    if not token:
        log("err", "No valid token. Run: python bot.py --login")
        return

    # ─── Initial check: claim both if available ───
    ic, _ = show_dashboard(token, cfg["deviceId"])
    if ic and ic.get("isClaimable"):
        token, _ = attempt_claim(cfg, token)

    # Group mining initial check
    token, _, group_next = attempt_group_claim(cfg, token)

    # Recovery initial check
    token, recovered = attempt_recovery(cfg, token)
    if recovered > 0:
        show_dashboard(token, cfg["deviceId"])

    # Get timers
    ic = check_claimable(token, cfg["deviceId"])
    mining_next = ic.get("nextFrame") or (time.time() * 1000 + CLAIM_INTERVAL * 1000)
    if not group_next:
        group_next = time.time() * 1000 + GROUP_INTERVAL * 1000

    log("info", f"Mining next: {format_countdown((mining_next - time.time() * 1000) / 1000)}")
    log("info", f"Group next:  {format_countdown((group_next - time.time() * 1000) / 1000)}")

    while True:
        # Check stopfile
        if os.path.exists(STOP_FILE):
            log("info", "Stop signal received. Exiting run_loop.")
            return
        now_ms = time.time() * 1000
        mining_remain = max(0, (mining_next - now_ms) / 1000)
        group_remain = max(0, (group_next - now_ms) / 1000)
        next_label = "mining" if mining_remain < group_remain else "group"
        next_secs = min(mining_remain, group_remain)

        if mining_remain > 0 or group_remain > 0:
            print(f"\r  {C.CY}⏰ Mining: {format_countdown(mining_remain)} | Group: {format_countdown(group_remain)}{C.R}     ", end="", flush=True)

        if mining_remain <= 0:
            print()
            log("step", "Mining claim time!")
            human_delay = random.randint(10, 60)
            log("info", f"Waiting {human_delay}s (human-like)...")
            time.sleep(human_delay)
            token = get_session(cfg)
            if not token:
                time.sleep(60)
                token = get_session(cfg)
            if token:
                token, claimed = attempt_claim(cfg, token)
                if claimed:
                    # Check recovery after successful mining claim
                    token, _ = attempt_recovery(cfg, token)
                    ic = check_claimable(token, cfg["deviceId"])
                    mining_next = ic.get("nextFrame") or (time.time() * 1000 + CLAIM_INTERVAL * 1000)
                else:
                    # Claim failed — re-fetch timer from API instead of blind 1-min retry
                    ic = check_claimable(token, cfg["deviceId"])
                    nf = ic.get("nextFrame")
                    if nf:
                        mining_next = nf
                    else:
                        mining_next = time.time() * 1000 + 300 * 1000  # fallback: retry in 5 min

        if group_remain <= 0:
            print()
            log("step", "Group mining claim time!")
            human_delay = random.randint(10, 60)
            log("info", f"Waiting {human_delay}s (human-like)...")
            time.sleep(human_delay)
            token = get_session(cfg)
            if token:
                token, claimed, group_next = attempt_group_claim(cfg, token)
                if not group_next:
                    group_next = time.time() * 1000 + GROUP_INTERVAL * 1000
            else:
                group_next = time.time() * 1000 + 300 * 1000  # fallback: retry in 5 min (was 1 min)

        time.sleep(10)


# ─── Cleanup old log/cache (auto, runs on bot start) ──────────────────────────
def cleanup_old_files(max_age_days=2):
    """Delete log entries older than max_age_days. Keeps file small, prevents bloat."""
    import glob
    now = time.time()
    cutoff = now - (max_age_days * 86400)
    
    # 1. Trim interlink.log — keep only last 500 lines
    log_file = os.path.join(SCRIPT_DIR, "interlink.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                lines = f.readlines()
            if len(lines) > 500:
                with open(log_file, "w") as f:
                    f.writelines(lines[-500:])
        except Exception:
            pass
    
    # 2. Delete old backup files older than max_age_days
    for pattern in ["token-backup-*.json", "claim_state-*.json"]:
        for f in glob.glob(os.path.join(SCRIPT_DIR, pattern)):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
            except Exception:
                pass
    
    # 3. Clean old __pycache__
    pycache = os.path.join(SCRIPT_DIR, "__pycache__")
    if os.path.isdir(pycache):
        for f in glob.glob(os.path.join(pycache, "*")):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
            except Exception:
                pass


# ─── Stop bot ──────────────────────────────────────────────────────────────────
STOP_FILE = os.path.join(SCRIPT_DIR, ".stop")

def stop_bot():
    """Stop the running bot gracefully using stopfile."""
    # Write stopfile — the running bot checks for this and exits cleanly
    with open(STOP_FILE, "w") as f:
        f.write(str(int(time.time())))
    log("info", "Stop signal sent. Bot will exit within 10 seconds.")
    # Also try SIGTERM as backup
    import subprocess, signal
    try:
        pids = subprocess.getoutput('pgrep -f "python3 bot\\.py$"').strip().split("\n")
        my_pid = str(os.getpid())
        pids = [p for p in pids if p and p != my_pid and p.strip()]
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
        if pids:
            log("ok", f"Sent stop signal to {len(pids)} process(es).")
        else:
            log("info", "No running bot process found (but stopfile created).")
    except Exception as e:
        log("warn", f"Could not signal process: {e}")
    # Clean up stopfile after 15s
    time.sleep(2)
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)


# ─── Status check (live API call for accurate timers) ─────────────────────────
def show_status():
    """Live status check — calls API for real timers, not stale log parsing."""
    state = load_claim_state()
    bal = state.get("balance", 0)
    lc = state.get("last_claim", 0)
    history = state.get("history", [])
    updated = state.get("updated_at", 0)
    ago = int(time.time() - updated)
    h, m = ago // 3600, (ago % 3600) // 60
    last_claim_wib = datetime.fromtimestamp(updated, tz=WIB).strftime("%H:%M WIB") if updated > 0 else "N/A"

    # Bot running?
    import subprocess
    try:
        pid = subprocess.getoutput('pgrep -f "python3 bot.py"').strip().split("\n")[0]
        bot_status = "✅ Running" if pid else "❌ NOT running"
    except Exception:
        bot_status = "❓ Unknown"

    # ─── LIVE API CALL for real timers ───
    cfg = load_config()
    # Auto-restore token from backup if missing
    if not os.path.exists(TOKEN_FILE) and os.path.exists(os.path.join(SCRIPT_DIR, "token-backup.json")):
        import shutil
        shutil.copy2(os.path.join(SCRIPT_DIR, "token-backup.json"), TOKEN_FILE)
        os.chmod(TOKEN_FILE, 0o600)
    token = get_session(cfg, allow_login=False)
    
    mining_next_str = "N/A"
    group_next_str = "N/A"
    refs = "N/A"
    streak_burned = "N/A"
    rec = "N/A"
    group_status = "N/A"
    per_claim = "N/A"
    per_day = "N/A"
    last_group_claim = "N/A"
    last_recovery = "N/A"

    if token:
        device_id = cfg["deviceId"]
        
        # Live mining timer
        try:
            ic = check_claimable(token, device_id)
            nf = ic.get("nextFrame")
            if nf:
                remain = max(0, int((nf - time.time() * 1000) / 1000))
                mining_next_str = format_countdown(remain)
            else:
                mining_next_str = "claimable now!"
        except Exception as e:
            mining_next_str = f"API error: {e}"
        
        # Live group timer
        try:
            gdata = get_group_mining_list(token, device_id)
            if gdata:
                groups = gdata.get("groups", [])
                gnext = gdata.get("nextTimeClaim")
                already = gdata.get("requesterHasClaimedToday", False)
                total_reward = sum(g.get("totalReward", 0) for g in groups)
                if gnext:
                    remain = max(0, int((gnext - time.time() * 1000) / 1000))
                    group_next_str = format_countdown(remain)
                else:
                    group_next_str = "N/A"
                if already:
                    group_status = f"claimed today ({len(groups)} groups, pool: {total_reward})"
                elif gdata.get("isClaimable"):
                    group_status = f"claimable! ({len(groups)} groups, pool: {total_reward})"
                else:
                    group_status = f"pending ({len(groups)} groups, pool: {total_reward})"
        except Exception:
            pass
        
        # Live user info for refs/streak/recoverable
        try:
            data = get_user_info(token, device_id)
            if data:
                ti = data.get("token", {})
                total_ref = ti.get("totalReferral", 0)
                ref_dir = ti.get("directReferralsHashRate", 0) or 0
                ref_ind = ti.get("indirectReferralsHashRate", 0) or 0
                refs = f"{round(ref_dir + ref_ind, 2)} ({total_ref} refs)"
                streak = ti.get("burningStreak", 0)
                burned = ti.get("burnedCycles", 0)
                streak_burned = f"{streak} / {burned}"
                rec = f"{ti.get('itlgRecoverable', 0)}"
                # Update balance from live data
                bal = ti.get("interlinkGoldTokenAmount", bal)
        except Exception:
            pass
    else:
        mining_next_str = "⚠️ No token (run: python bot.py --login)"

    # Per claim/day from history
    if history:
        avg = round(sum(history) / len(history), 1)
        per_claim = f"{avg} ITLG"
        per_day = f"{round(avg * 6, 1)} ITLG"

    # Parse log for last group claim + recovery (these are events, not timers — safe to parse)
    try:
        raw_log = open(os.path.join(SCRIPT_DIR, "interlink.log")).read()
        lgc = re.findall(r"Group mining claimed!\s+\+([\d?]+) ITLG", raw_log)
        lrc = re.findall(r"Recovery complete!\s+\+([\d]+) ITLG", raw_log)
        if lgc: last_group_claim = f"+{lgc[-1]} ITLG"
        if lrc: last_recovery = f"+{lrc[-1]} ITLG"
    except Exception:
        pass

    print(f"\n  {C.CY}{C.B}╔══════════════════════════════════════╗{C.R}")
    print(f"  {C.CY}{C.B}║   Interlink ITLG — Status             ║{C.R}")
    print(f"  {C.CY}{C.B}╚══════════════════════════════════════╝{C.R}\n")
    print(f"  🤖 Bot: {bot_status}")
    print(f"  💰 Balance: {bal} ITLG")
    print(f"  🎯 Last claim: +{lc} ITLG ({h}h {m}m ago, {last_claim_wib})")
    if history:
        print(f"  📊 History: {' → '.join(str(x) for x in history[-5:])}")
    print(f"  📈 Per claim: {per_claim} | Per day: {per_day}")
    print(f"  👥 Refs: {refs}")
    print(f"  🔥 Streak/Burned: {streak_burned}")
    print(f"  💎 Recoverable: {rec} ITLG")
    if last_recovery != "N/A":
        print(f"  ♻️ Last recovery: {last_recovery}")
    print(f"  ─────────────────────────────")
    print(f"  👥 Group: {group_status}")
    if last_group_claim != "N/A":
        print(f"  🎯 Last group claim: {last_group_claim}")
    print(f"  ⏳ Group next: {group_next_str}")
    print(f"  ⏳ Mining next: {mining_next_str}")
    print()
def main():
    parser = argparse.ArgumentParser(description="Interlink Labs Auto Claim")
    parser.add_argument("--once", action="store_true", help="Single run, then exit")
    parser.add_argument("--login", action="store_true", help="Force re-login via OTP")
    parser.add_argument("--login-face", action="store_true", help="Login with face photo (selfie)")
    parser.add_argument("--photo", type=str, default=None, help="Selfie photo path (use with --login-face)")
    parser.add_argument("--status", action="store_true", help="Live status check (API call)")
    parser.add_argument("--stop", action="store_true", help="Stop the running bot")
    parser.add_argument("--restart", action="store_true", help="Stop then start the bot")
    args = parser.parse_args()

    print(f"\n  {C.CY}{C.B}╔════════════════════════════════════╗{C.R}")
    print(f"  {C.CY}{C.B}║   Interlink Labs Auto Claim Bot     ║{C.R}")
    print(f"  {C.CY}{C.B}║   Login once · Claim every 4h       ║{C.R}")
    print(f"  {C.CY}{C.B}╚════════════════════════════════════╝{C.R}")
    print(f"  {C.DIM}  ☕ Support: https://saweria.co/febfrmn{C.R}\n")

    cfg = load_config()

    if args.login:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        access, _ = do_login(cfg)
        if access:
            log("ok", "Login complete. Run: python bot.py")
        return

    if args.login_face:
        # Backup existing token before face login
        if os.path.exists(TOKEN_FILE):
            import shutil
            shutil.copy2(TOKEN_FILE, TOKEN_FILE + ".pre-login")
        access, _ = do_face_login(cfg, photo_override=args.photo)
        if access:
            log("ok", "Face login complete. Run: python bot.py")
            # Clean up pre-login backup on success
            pre = TOKEN_FILE + ".pre-login"
            if os.path.exists(pre):
                os.remove(pre)
        else:
            # Restore previous token if face login failed
            pre = TOKEN_FILE + ".pre-login"
            if os.path.exists(pre):
                import shutil
                shutil.move(pre, TOKEN_FILE)
                log("info", "Restored previous token (face login failed).")
        return

    if args.status:
        show_status()
        return

    if args.stop:
        stop_bot()
        return

    if args.restart:
        stop_bot()
        time.sleep(3)
        log("info", "Starting fresh...")
        # Continue to run_loop below

    if args.once:
        run_once(cfg)
        return

    # ─── Main loop with crash-proof auto-restart ───
    cleanup_old_files(max_age_days=2)
    
    # Don't start if already running
    import subprocess
    existing = subprocess.getoutput('pgrep -f "python3 bot.py"').strip().split("\n")
    existing = [p for p in existing if p and p != str(os.getpid())]
    if existing and not args.restart:
        log("warn", "Bot already running. Use --stop first or --status to check.")
        return

    MAX_RESTARTS = 50
    restart_count = 0
    while restart_count < MAX_RESTARTS:
        # Check stopfile — exit cleanly if --stop was called
        if os.path.exists(STOP_FILE):
            log("info", "Stop signal received. Exiting.")
            try:
                os.remove(STOP_FILE)
            except Exception:
                pass
            break
        try:
            run_loop(cfg)
        except KeyboardInterrupt:
            print(f"\n\n  {C.DIM}Stopped.{C.R}\n")
            break
        except Exception as e:
            restart_count += 1
            log("err", f"Crash #{restart_count}: {e}")
            log("info", f"Auto-restart in 30s... (attempt {restart_count}/{MAX_RESTARTS})")
            try:
                send_telegram_notif(cfg, {
                    "claimed": 0, "before": 0, "after": 0,
                    "rate_per_claim": 0, "rate_per_day": None, "group_rate": 0,
                })
            except Exception:
                pass
            time.sleep(30)
            # Clean up before restart
            cleanup_old_files(max_age_days=2)
            log("step", f"Restarting... (attempt {restart_count}/{MAX_RESTARTS})")
            continue
    
    if restart_count >= MAX_RESTARTS:
        log("err", f"Max restarts ({MAX_RESTARTS}) reached. Bot stopped. Check logs.")

if __name__ == "__main__":
    main()
