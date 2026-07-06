# Interlink Auto Claim

```
███████╗███████╗██████╗       ███████╗██████╗ ███╗   ███╗███╗   ██╗
██╔════╝██╔════╝██╔══██╗      ██╔════╝██╔══██╗████╗ ████║████╗  ██║
█████╗  █████╗  ██████╔╝█████╗█████╗  ██████╔╝██╔████╔██║██╔██╗ ██║
██╔══╝  ██╔══╝  ██╔══██╗╚════╝██╔══╝  ██╔══██╗██║╚██╔╝██║██║╚██╗██║
██║     ███████╗██████╔╝      ██║     ██║  ██║██║ ╚═╝ ██║██║ ╚████║
╚═╝     ╚══════╝╚═════╝       ╚═╝     ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═══╝
```

Auto-claim $ITLG from Interlink Labs. Mining, group mining & recovery — full otomatis, crash-proof.

Single Python script. Login once with OTP, then it claims forever. Sends Telegram notification on every successful claim and crash.

## Quick Start

```bash
git clone https://github.com/feb-frmn/itlg-claim.git
cd itlg-claim
pip install requests
python setup.py
```

`setup.py` will ask you for everything it needs and save it to `config.json`.

### What you need before running setup

| Field | What it is | Example | How to get it |
|---|---|---|---|
| **loginId** | Your Interlink ID — a **number**, not email | `8002` | Open the Interlink app → Profile |
| **passcode** | 6-digit passcode (numbers only) | `204008` | You chose this when signing up |
| **email** | The Gmail address registered to your account | `you@gmail.com` | Whatever email you signed up with |
| **imapPassword** | Gmail App Password — 16 letters | `abcd efgh ijkl mnop` | [Get one here](https://myaccount.google.com/apppasswords) |
| **tgBotToken** | Telegram bot token (optional) | `123456:ABC-DEF...` | Create via [@BotFather](https://t.me/BotFather) |
| **tgChatId** | Your Telegram user ID (optional) | `123456789` | Message [@userinfobot](https://t.me/userinfobot) |

## Commands

```
python bot.py               # Start (auto-restart on crash)
python bot.py --status      # Live status (API call, timer akurat)
python bot.py --stop        # Stop bot
python bot.py --restart     # Stop + start fresh
python bot.py --once        # Single run
python bot.py --login       # Force re-login OTP (email)
python bot.py --login-face  # Login with face photo (selfie)
```

## Login Methods

### Method 1: OTP (email)
```bash
python setup.py          # isi loginId, passcode, email, imapPassword
python bot.py --login    # kirim OTP ke email, masukin kode
```

### Method 2: Selfie / Face Photo
```bash
python setup.py          # isi loginId, passcode + path foto selfie
python bot.py --login-face  # upload foto → verifikasi wajah → login
```
Face photo: selfie jelas, pencahayaan bagus, wajah terlihat full. Format: JPG/PNG.

## What's New in v2.1

| Fitur | Detail |
|---|---|
| Face Login | `--login-face` — login pake selfie, gak perlu OTP |
| Auto face fallback | Token expired → coba face login dulu sebelum OTP |
| Dual login | OTP + Selfie, bisa pilih mana aja |

## What's New in v2.0

| Fitur | v1 | v2 |
|---|---|---|
| Mining claim (4h) | Auto + delay | Auto + delay + re-fetch timer saat gagal |
| Group mining (24h) | Manual | Auto + human delay 30-120s |
| Recovery | Manual | Auto setiap cycle + claim |
| Status timer | Parse log basi | Live API (match APK) |
| Crash | Mati total | Auto-restart 50x, delay 30s |
| Telegram notif | Claim only | Claim + crash alert |
| Stop | Kill manual | `--stop` graceful |
| Log | Bengkak | Auto-trim 500 lines + clean 2 hari |
| Double-run | Bisa | Protected |
| PID | Tampil | Hidden (group-safe) |

## Auto Claim (semua otomatis)

| Fitur | Interval | Status |
|---|---|---|
| Mining claim | 4 jam | ✅ Auto + human delay 10-60s |
| Group mining | 24 jam | ✅ Auto + human delay 30-120s |
| Recovery | Setiap cycle | ✅ Auto-check + claim |
| Token refresh | Auto | ✅ JWT auto-refresh |

## Status Output

```
  ╔══════════════════════════════════════╗
  ║   Interlink ITLG — Status             ║
  ╚══════════════════════════════════════╝

  🤖 Bot: ✅ Running
  💰 Balance: 8087 ITLG
  🎯 Last claim: +41 ITLG (0h 2m ago, 15:02 WIB)
  📊 History: 17 → 17 → 17 → 41 → 41
  📈 Per claim: 25.0 ITLG | Per day: 150.0 ITLG
  👥 Refs: 4.5 (21 refs)
  🔥 Streak/Burned: 0 / 511
  💎 Recoverable: 10241 ITLG
  ─────────────────────────────
  👥 Group: claimed today (5 groups, pool: 432)
  ⏳ Group next: 16h 55m 44s
  ⏳ Mining next: 03h 55m 44s
```

All values are **live from API** — timer matches your APK exactly.

## How It Works

1. First run: sends OTP to Gmail, IMAP grabs it, verifies, saves token
2. Bot reads `nextFrame` from API — knows exactly when you can claim next
3. Mining claim every 4h, group mining every 24h, recovery every cycle — all automatic
4. Telegram notification on every claim + crash alert
5. Token never logs out. Auto-refresh if expired. Auto-restart if crash.
6. Log auto-cleanup: trims to last 500 lines, deletes files older than 2 days

## Anti-Detection

- **Random device fingerprint** — each account gets a random phone model (Samsung, Xiaomi, Pixel, OPPO, etc.)
- **Human-like timing** — waits 10-120s after claim window opens before claiming
- **No constant polling** — checks every 10 seconds, not every 1 second
- **Same endpoint as the app** — uses the exact same API endpoints and headers as the official Interlink Android app

## Token Backup

After first login, token saved to `token.json` + `token-backup.json` (chmod 600).

```bash
# Manual backup
cp token.json ~/token-backup.json

# Restore
cp ~/token-backup.json token.json
chmod 600 token.json
```

## Files

```
setup.py              # interactive setup
bot.py                # the bot (v2.0)
config.json           # your config (gitignored)
token.json            # saved token (gitignored)
claim_state.json      # claim history (gitignored)
```

## OTP Not Arriving?

1. **Check Spam/Junk** — Gmail sometimes routes Interlink emails to Spam
2. **Wait 1-2 minutes** — Interlink can be slow
3. **Verify Gmail App Password** — must be 16-letter App Password, not Gmail password
4. **Login from the app first** — open InterLink app, login once, then run `bot.py --login`
5. **Check IMAP access** — Gmail Settings → Forwarding and POP/IMAP → Enable IMAP

## License

MIT

---

## ☕ Support

[![Saweria](https://img.shields.io/badge/Saweria-ffb13b?style=for-the-badge&logo=ko-fi&logoColor=white)](https://saweria.co/febfrmn)
