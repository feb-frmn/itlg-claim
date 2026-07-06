#!/usr/bin/env python3
"""
Interlink bot setup — fills in config.json for you with prompts.

Usage: python setup.py
"""

import json, os, hashlib, getpass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")
EXAMPLE     = os.path.join(SCRIPT_DIR, "config.json.example")

BOLD  = "\033[1m"
DIM   = "\033[2m"
CYAN  = "\033[36m"
GREEN = "\033[32m"
RESET = "\033[0m"

def ask(prompt, default=""):
    suffix = f" {DIM}(default: {default}){RESET}" if default else ""
    full = f"  {BOLD}{prompt}{RESET}{suffix}\n  > "
    val = input(full).strip()
    return val or default

def main():
    print(f"\n  {CYAN}{BOLD}╔══════════════════════════════════════╗{RESET}")
    print(f"  {CYAN}{BOLD}║   Interlink Bot Setup               ║{RESET}")
    print(f"  {CYAN}{BOLD}║   Fill in your details below        ║{RESET}")
    print(f"  {CYAN}{BOLD}╚══════════════════════════════════════╝{RESET}\n")

    # Load existing config if present
    existing = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            existing = json.load(f)
        print(f"  {GREEN}Found existing config.json — loading current values.{RESET}\n")
    elif os.path.exists(EXAMPLE):
        with open(EXAMPLE) as f:
            existing = json.load(f)

    # Set random device fingerprint if not present
    if not existing.get("deviceModel"):
        import random as _r
        devices = [
            ("Redmi Note 8 Pro", "XiaoMi"), ("Redmi Note 11", "XiaoMi"),
            ("SM-G991B", "samsung"), ("SM-A525F", "samsung"),
            ("Pixel 6", "Google"), ("Pixel 7", "Google"),
            ("CPH2247", "OPPO"), ("V2057A", "vivo"),
            ("RMX3081", "Realme"), ("M2101K6G", "POCO"),
        ]
        dev = _r.choice(devices)
        existing["deviceModel"] = dev[0]
        existing["deviceBrand"] = dev[1]

    print(f"  {BOLD}REQUIRED{RESET} — without these the bot won't work:\n")

    loginId = ask("Interlink Login ID (angka murni, contoh: 123456 — BUKAN @username)",
                  str(existing.get("loginId", "")))

    # For secrets: show hint if existing, but don't reveal the value
    passcode_default = str(existing.get("passcode", ""))
    if passcode_default:
        print(f"  {BOLD}Passcode{RESET} {DIM}(current: {'*' * len(passcode_default)} — press Enter to keep){RESET}")
        passcode = getpass.getpass(f"  > ") or passcode_default
    else:
        passcode = getpass.getpass(f"  {BOLD}Passcode{RESET} (6-digit angka dari registrasi)\n  > ")

    email = ask("Email Gmail yang terdaftar di Interlink (contoh: kamu@gmail.com)",
                existing.get("email", ""))

    imap_default = existing.get("imapPassword", "")
    if imap_default:
        print(f"  {BOLD}Gmail App Password{RESET} {DIM}(current: {'*' * len(imap_default)} — press Enter to keep){RESET}")
        print(f"  {DIM}  Bukan password Gmail! Bikin di: https://myaccount.google.com/apppasswords{RESET}")
        print(f"  {DIM}  Bisa pake spasi (abcd efgh ijkl mnop) atau gabung (abcdefghijklmnop){RESET}")
        imap_password = getpass.getpass(f"  > ") or imap_default
    else:
        print(f"  {BOLD}Gmail App Password{RESET} (16 huruf — BUKAN password Gmail lo!)")
        print(f"  {DIM}  Bikin di: https://myaccount.google.com/apppasswords{RESET}")
        print(f"  {DIM}  Bisa pake spasi atau gabung, dua-duanya jalan{RESET}")
        imap_password = getpass.getpass(f"  > ")


    print(f"\n  {BOLD}OPTIONAL{RESET} — press Enter to skip:\n")

    # Face photo for face login (alternative to OTP)
    face_photo_default = existing.get("facePhoto", "")
    face_photo = ask("Face photo path (selfie.jpg — alternative login tanpa OTP)",
                     face_photo_default)
    if face_photo:
        face_photo = face_photo.strip('"').strip("'")
        if not os.path.exists(face_photo):
            print(f"  {BOLD}⚠️  File not found: {face_photo}{RESET}")
            print(f"  {DIM}  Face login gak akan jalan tanpa file ini. Tapi lanjut aja, bisa OTP juga.{RESET}")

    tg_bot_token = ask("Telegram Bot Token (kosongin kalau gak mau notif)",
                       existing.get("tgBotToken", ""))
    tg_chat_id = ask("Telegram Chat ID (kosongin kalau gak mau notif)",
                     str(existing.get("tgChatId", "")))

    # Build config
    cfg = {
        "loginId": loginId,
        "passcode": passcode,
        "email": email,
        "imapPassword": imap_password,
        "facePhoto": face_photo,
        "deviceId": existing.get("deviceId", ""),
        "tgBotToken": tg_bot_token,
        "tgChatId": tg_chat_id,
    }

    # Auto-generate deviceId — random per install (NOT md5 of loginId)
    # Interlink may silent-drop OTP from deviceId patterns that look bot-like
    if not cfg["deviceId"]:
        import secrets
        cfg["deviceId"] = secrets.token_hex(8)  # 16-char random hex (Android ANDROID_ID format)
        print(f"\n  {GREEN}✅ Auto-generated device ID: {cfg['deviceId']}{RESET}")

    # Save
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)

    print(f"\n  {GREEN}{BOLD}✅ Config saved to {CONFIG_FILE}{RESET}")
    print(f"  {DIM}(chmod 600 — only you can read it){RESET}\n")

    # Validate
    missing = []
    if not loginId:    missing.append("loginId")
    if not passcode:   missing.append("passcode")
    if not email:      missing.append("email")
    if not imap_password: missing.append("imapPassword")

    if missing:
        print(f"  {BOLD}⚠️  Missing required fields: {', '.join(missing)}{RESET}")
        print(f"  Edit {CONFIG_FILE} manually or re-run this setup.\n")
        return 1
    else:
        print(f"  {GREEN}All required fields filled!{RESET}")
        print(f"\n  {BOLD}Next steps:{RESET}")
        print(f"  1. Run: {CYAN}python setup.py{RESET}         (interactive setup)")
        print(f"  2. Login method:")
        print(f"     • {CYAN}python bot.py --login{RESET}       (OTP via email)")
        if face_photo:
            print(f"     • {CYAN}python bot.py --login-face{RESET} (selfie photo)")
        print(f"  3. Run: {CYAN}python bot.py{RESET}           (start the bot)")
        print(f"  4. Leave it running — auto-claims mining + group + recovery.")
        print(f"\n  {BOLD}⚠️  OTP not arriving?{RESET}")
        print(f"  {DIM}  • Check Spam/Junk folder in Gmail{RESET}")
        print(f"  {DIM}  • Wait 1-2 minutes — Interlink can be slow{RESET}")
        print(f"  {DIM}  • Make sure Gmail App Password is correct (not your Gmail password){RESET}")
        print(f"  {DIM}  • If OTP still doesn't arrive, try logging in from the InterLink app first,{RESET}")
        print(f"  {DIM}    then run bot.py --login (the app registers your device with Interlink){RESET}")
        print()
    return 0

if __name__ == "__main__":
    exit(main())
