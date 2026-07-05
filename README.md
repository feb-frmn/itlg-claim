# Interlink Auto Claim

Auto-claim $ITLG from Interlink Labs. Every 4 hours, no manual clicking.

Single Python script. Login once with IMAP OTP, then it claims forever. The bot knows when your next claim is available and counts down automatically — just leave it running. Optional Telegram notifications when a claim succeeds.

## Setup

```bash
pip install requests
cp config.json.example config.json
```

Edit `config.json`:

```json
{
  "loginId": "123456",
  "passcode": "000000",
  "email": "your-email@gmail.com",
  "imapPassword": "your gmail app password",
  "deviceId": "",
  "tgBotToken": "",
  "tgChatId": ""
}
```

- `loginId` — your Interlink ID (number, not email)
- `passcode` — 6-digit passcode you set during registration
- `email` — the email registered to your Interlink account
- `imapPassword` — Gmail App Password ([get one here](https://myaccount.google.com/apppasswords), not your Gmail password)
- `deviceId` — leave empty, it auto-generates
- `tgBotToken` — optional, Telegram bot token for push notifications
- `tgChatId` — optional, your Telegram chat ID for notifications

If you skip the Telegram fields, the bot still works fine — it just won't send push notifications. You'll still see everything in the console.

## Run

```bash
python bot.py
```

That's it. The bot logs in via OTP once, saves the token, and stays running. It reads the next claim time from the API and shows a live countdown. When the timer hits zero, it claims automatically.

```
  ╔══════════════════════════════════════╗
  ║  username                              ║
  ╠══════════════════════════════════════╣
  ║  ITLG Balance                         609  ║
  ║  Last claim                          17 ITLG  ║
  ║  Per claim                         17.0 ITLG  ║
  ║  Per day                          102.0 ITLG  ║
  ║  Group                           inactive  ║
  ║  Referral                    1.9 (8 refs)  ║
  ║  Streak/Burned                    0 / 511  ║
  ║  Recoverable                   10502 ITLG  ║
  ╚══════════════════════════════════════╝
⏰ Next claim in 03h 52m 10s
```

The dashboard tracks your **actual claim history** — what you really get per claim and per day, not theoretical rates:

- **ITLG Balance** — your current mined balance
- **Last claim** — how much you got from the most recent claim
- **Per claim** — average ITLG per claim (from your actual claim history)
- **Per day** — estimated daily earnings (per claim × 6 cycles per day)
- **Group** — group mining rate (shows "inactive" until you create a group in the app)
- **Referral** — combined direct + indirect referral rate and your referrer count
- **Streak/Burned** — your current burning streak and total burned cycles
- **Recoverable** — ITLG locked in burned cycles that can be recovered later

On a successful claim, you'll see:

```
✅ Claimed! +17 ITLG
ℹ️ Balance: 592 → 609 ITLG
ℹ️ Avg per claim: 17.0 | Per day: 102.0 ITLG
```

And if Telegram is configured, you get a push notification with the same info.

## Options

```
python bot.py          # run with live countdown timer (default)
python bot.py --once   # single run, check + claim if available, then exit
python bot.py --login  # force re-login (get new OTP)
```

## Cron Mode (No-Agent Watchdog)

For set-and-forget auto-claiming without keeping the bot running, use `check_claim.py` with cron:

```bash
*/5 * * * * cd /path/to/interlink-bot && python3 check_claim.py
```

The checker is **silent when there's nothing to claim** — it produces no output, so your cron inbox stays clean. When a claim succeeds, it prints the notification to stdout (ideal for cron delivery or piping to a notifier). It also sends directly to Telegram if `tgBotToken` + `tgChatId` are set in config.

Manual test:
```bash
python check_claim.py   # prints claim result if claimable, silent otherwise
```

## Saving Your Token

After your first login, the bot saves your token to `token.json` (and `token-backup.json` as a backup). This file lets you claim without logging in again. Keep a copy somewhere safe — if you lose both, you'll need to re-login via OTP.

**Backup:**
```bash
# already done automatically as token-backup.json, but you can copy it elsewhere:
cp token.json ~/token-backup.json
```

**Restore:**
```bash
cp ~/token-backup.json token.json
chmod 600 token.json
```

You can also manually paste a token from packet capture (e.g. HTTP Catcher on your phone):
```bash
echo '{"access":"eyJ...","refresh":"eyJ...","saved_at":0}' > token.json
chmod 600 token.json
```

Only `access` is required. `refresh` is optional but helps auto-renew.

## How It Works

1. First run: sends OTP to your Gmail, IMAP grabs it, verifies, saves token
2. Bot reads `nextFrame` from the API — knows exactly when you can claim next
3. Counts down in real-time. When timer hits zero: checks claimable, triggers ads session, claims
4. Token never logs out. If expired, refreshes automatically. Only re-logins if refresh token also dies.

## Token Types

| App Display | Token | What it is |
|---|---|---|
| Gold | **ITLG** | What you mine. This is the airdrop token. |
| Interlink | ITL | Utility token, separate supply |
| Silver / Diamond | — | Boosters, not separate tokens |

You're mining **ITLG**.

## Files

```
bot.py                # the bot (loop mode + --once + --login)
check_claim.py        # cron checker (silent if nothing to claim, prints on success)
config.json           # your config (gitignored)
config.json.example   # template
token.json            # saved token (gitignored, auto-created)
token-backup.json     # backup copy (gitignored, auto-created)
claim_state.json      # actual claim history for rate display (gitignored, auto-created)
```

## Notes

- Your token is saved locally with `chmod 600`. Don't share `config.json` or `token.json`.
- If OTP doesn't arrive, the bot resends automatically (up to 3 times).
- No multi-account, no proxy rotation, no Node.js. One script, one account, one dependency.
- Group mining rate is 0 until you create a group in the Interlink app. Once active, it shows automatically.
- `burnedCycles` and `itlgRecoverable` are display-only — the API has no recovery endpoint yet. Recover through the app when available.

## License

MIT
