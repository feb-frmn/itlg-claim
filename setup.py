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

    loginId = ask("Interlink Login ID (number, e.g. 123456)",
                  str(existing.get("loginId", "")))

    # For secrets: show hint if existing, but don't reveal the value
    passcode_default = str(existing.get("passcode", ""))
    if passcode_default:
        print(f"  {BOLD}Passcode{RESET} {DIM}(current: {'*' * len(passcode_default)} — press Enter to keep){RESET}")
        passcode = getpass.getpass(f"  > ") or passcode_default
    else:
        passcode = getpass.getpass(f"  {BOLD}Passcode{RESET} (6-digit code from registration)\n  > ")

    email = ask("Your Gmail address (registered to Interlink)",
                existing.get("email", ""))

    imap_default = existing.get("imapPassword", "")
    if imap_default:
        print(f"  {BOLD}Gmail App Password{RESET} {DIM}(current: {'*' * len(imap_default)} — press Enter to keep){RESET}")
        print(f"  {DIM}  Get one at: https://myaccount.google.com/apppasswords{RESET}")
        imap_password = getpass.getpass(f"  > ") or imap_default
    else:
        print(f"  {BOLD}Gmail App Password{RESET} (NOT your Gmail password!)")
        print(f"  {DIM}  Get one at: https://myaccount.google.com/apppasswords{RESET}")
        imap_password = getpass.getpass(f"  > ")

    print(f"\n  {BOLD}OPTIONAL{RESET} — press Enter to skip:\n")

    tg_bot_token = ask("Telegram Bot Token (for push notifications)",
                       existing.get("tgBotToken", ""))
    tg_chat_id = ask("Telegram Chat ID (your user ID, e.g. 123456789)",
                     str(existing.get("tgChatId", "")))

    # Build config
    cfg = {
        "loginId": loginId,
        "passcode": passcode,
        "email": email,
        "imapPassword": imap_password,
        "deviceId": existing.get("deviceId", ""),
        "tgBotToken": tg_bot_token,
        "tgChatId": tg_chat_id,
    }

    # Auto-generate deviceId if empty
    if not cfg["deviceId"]:
        cfg["deviceId"] = hashlib.md5(loginId.encode()).hexdigest()[:16]
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
        print(f"  1. Run: {CYAN}python bot.py --login{RESET}  (one-time OTP login)")
        print(f"  2. Run: {CYAN}python bot.py{RESET}           (start the bot)")
        print(f"  3. Leave it running — it auto-claims every 4h and sends Telegram notifs.")
        print()
    return 0

if __name__ == "__main__":
    exit(main())
