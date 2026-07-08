# ITLG Claim Bot v2.2 — Full Indonesia

```
███████╗███████╗██████╗       ███████╗██████╗ ███╗   ███╗███╗   ██╗
██╔════╝██╔════╝██╔══██╗      ██╔════╝██╔══██╗████╗ ████║████╗  ██║
█████╗  █████╗  ██████╔╝█████╗█████╗  ██████╔╝██╔████╔██║██╔██╗ ██║
██╔══╝  ██╔══╝  ██╔══██╗╚════╝██╔══╝  ██╔══██╗██║╚██╔╝██║██║╚██╗██║
██║     ███████╗██████╔╝      ██║     ██║  ██║██║ ╚═╝ ██║██║ ╚████║
╚═╝     ╚══════╝╚═════╝       ╚═╝     ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═══╝
```

Auto claim ITLG dari Interlink Labs. Mining 4 jam, group mining, recovery otomatis. Full bahasa Indonesia, cepat, dan bebas bug.

Satu script Python. Login sekali pakai OTP atau selfie, lalu klaim selamanya. Notifikasi Telegram full Indonesia.


## What's New in v2.2

- Full bahasa Indonesia di semua notifikasi Telegram dan log
- **Fixed**: Mining claim notif tidak lagi menampilkan "👥 Group: 0.71/hari" dari API groupMiningRate (misleading). Hanya real per-claim + per-hari dari history.
- **Fixed**: Group claim notif sekarang menampilkan "Group reward: XXX ITLG total" (actual amount), bukan rate.
- Gateway lebih robust: pakai `requests` + long polling + exponential backoff + auto-reconnect (tahan timeout di VPS Oracle)
- Penambahan `demo_test.py` untuk verifikasi output notif
- Perbaikan lag & bug pesan
- Header bot dan gateway full Indonesia
- Lebih cepat dan stabil

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
python bot.py --status      # Live status (API call, accurate timer)
python bot.py --stop        # Stop bot
python bot.py --restart     # Stop + start fresh
python bot.py --once        # Single run
python bot.py --login       # Force re-login OTP (email)
python bot.py --login-face  # Login with face photo (selfie)
```

## Login Methods

### Method 1: OTP (email)
```bash
python setup.py          # enter loginId, passcode, email, imapPassword
python bot.py --login    # send OTP to email, enter code
```

### Method 2: Selfie / Face Photo
```bash
python setup.py          # enter loginId, passcode + selfie photo path
python bot.py --login-face  # upload photo → face verify → login
```
Face photo: clear selfie, good lighting, full face visible. Format: JPG/PNG.

## What's New in v2.2

| Feature | Detail |
|---|---|
| Face Login | `--login-face` — login with selfie, no OTP needed |
| Auto face fallback | Token expired → try face login first before OTP |
| Dual login | OTP + Selfie, use either one |

## What's New in v2.0

| Feature | v1 | v2 |
|---|---|---|
| Mining claim (4h) | Auto + delay | Auto + delay + re-fetch timer on failure |
| Group mining (24h) | Manual | Auto + human delay 30-120s |
| Recovery | Manual | Auto every cycle + claim |
| Status timer | Parse stale log | Live API (matches APK) |
| Crash | Dead | Auto-restart 50x, delay 30s |
| Telegram notif | Claim only | Claim + crash alert |
| Stop | Manual kill | `--stop` graceful |
| Log | Bloated | Auto-trim 500 lines + clean 2 days |
| Double-run | Possible | Protected |
| PID | Shown | Hidden (group-safe) |

## Auto Claim (fully automatic)

| Feature | Interval | Status |
|---|---|---|
| Mining claim | 4 hours | ✅ Auto + human delay 10-60s |
| Group mining | 24 hours | ✅ Auto + human delay 30-120s |
| Recovery | Every cycle | ✅ Auto-check + claim |
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

## Demo Test (baru di v2.2)

Gunakan `demo_test.py` untuk melihat contoh output notifikasi Telegram tanpa perlu menjalankan bot:

```bash
python demo_test.py                    # tampilkan semua contoh
python demo_test.py --claim-success    # contoh klaim mining berhasil (format utama)
python demo_test.py --recovery         # contoh recovery
python demo_test.py --group            # contoh group mining
python demo_test.py --dashboard        # contoh tampilan /status
```

Ini sangat berguna untuk:
- Verifikasi format pesan sebelum release
- Testing notifikasi Telegram
- Menunjukkan ke user seperti apa outputnya

