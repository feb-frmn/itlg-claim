# Interlink Auto Claim

Auto-claim $ITLG from Interlink Labs. Every 4 hours, no manual clicking.

Single Python script. Login once with OTP, then it claims forever. The bot knows when your next claim is available and counts down automatically — just leave it running. Optional Telegram notifications when a claim succeeds.

## Quick Start

```bash
git clone https://github.com/feb-frmn/itlg-claim.git
cd itlg-claim
pip install requests
python setup.py
```

`setup.py` will ask you for everything it needs and save it to `config.json`. You just fill in the blanks and press Enter.

### What you need before running setup

| Field | What it is | How to get it |
|---|---|---|
| **loginId** | Your Interlink ID (a number, not email) | Open the Interlink app → Profile |
| **passcode** | 6-digit passcode you set during registration | You chose this when signing up |
| **email** | The Gmail registered to your Interlink account | Whatever email you signed up with |
| **imapPassword** | Gmail App Password (NOT your Gmail password!) | [Get one here](https://myaccount.google.com/apppasswords) |
| **tgBotToken** | Telegram bot token (optional) | Create a bot via [@BotFather](https://t.me/BotFather) |
| **tgChatId** | Your Telegram user ID (optional) | Message [@userinfobot](https://t.me/userinfobot) |

Watch the video tutorial: [Gmail App Password](https://myaccount.google.com/apppasswords) — this is a 16-character code that lets the bot read your OTP emails. It's **not** your Gmail login password.

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
  ║  Group                   pending activation  ║
  ║  Referral                    1.9 (8 refs)  ║
  ║  Streak/Burned                    0 / 511  ║
  ║  Recoverable                   10502 ITLG  ║
  ╚══════════════════════════════════════╝
⏰ Next claim in 03h 52m 10s
```

What each line means:

- **ITLG Balance** — your current mined balance
- **Last claim** — how much you got from the most recent claim
- **Per claim** — average ITLG per claim (from your actual claim history)
- **Per day** — estimated daily earnings (per claim × 6 cycles per day)
- **Group** — group mining rate. Shows "pending activation" if your group rate is still 0. Once the group is active, the rate shows here and claims increase automatically.
- **Referral** — combined direct + indirect referral rate and your referrer count
- **Streak/Burned** — your current burning streak and total burned cycles
- **Recoverable** — ITLG locked in burned cycles that can be recovered later

On a successful claim, you'll see:

```
✅ Claimed! +17 ITLG
ℹ️ Balance: 592 → 609 ITLG
ℹ️ Avg per claim: 17.0 | Per day: 102.0 ITLG
```

And if Telegram is configured, you get a push notification:

```
✅ ITLG Claim Success

💰 Claimed: +17 ITLG
📊 Balance: 592 → 609 ITLG
⏱️ Per claim: 17.0 ITLG
📈 Per day: ~102.0 ITLG (6 claims)
👥 Group: pending activation
🕐 12:00:23

Next claim in 4h.
```

## Options

```
python setup.py        # interactive setup (fills config.json for you)
python bot.py          # run with live countdown timer (default)
python bot.py --once   # single run, check + claim if available, then exit
python bot.py --login  # force re-login (get new OTP)
```

## Cron Mode (Set and Forget)

For auto-claiming without keeping the bot running, set up `check_claim.py` with cron:

```bash
*/5 * * * * cd /path/to/itlg-claim && python3 check_claim.py
```

The checker is **silent when there's nothing to claim** — it produces no output, so your logs stay clean. When a claim succeeds, it prints the notification to stdout (making it ideal for cron delivery — any output is the notification itself). It also sends directly to Telegram if `tgBotToken` + `tgChatId` are set in config.

Manual test:
```bash
python check_claim.py   # prints claim result if claimable, silent otherwise
```

## Group Mining

The bot **automatically claims group mining every cycle** — it uses the same endpoint as solo mining (`/token/claim-airdrop`), so every claim includes solo + group + referral earnings all at once.

If the dashboard shows **"pending activation"**, it means your group mining rate is still `0` on the server. This happens when:

- You haven't created a group in the Interlink app yet
- Your group doesn't have enough active members (they need to be KYC-verified and have claimed at least once)
- The group mining cycle hasn't started yet (it may need one full cycle to activate)

Once the server sets your `groupMiningRate` above 0, the bot picks it up automatically — no code changes needed. Your per-claim amount increases and the dashboard shows the group rate.

## Saving Your Token

After your first login, the bot saves your token to `token.json` (and `token-backup.json` as a backup). This file lets you claim without logging in again. Keep a copy somewhere safe — if you lose both, you'll need to re-login via OTP.

**Backup** (also done automatically):
```bash
cp token.json ~/token-backup.json
```

**Restore**:
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
setup.py              # interactive setup — fills config.json with prompts
bot.py                # the bot (loop mode + --once + --login)
check_claim.py        # cron checker (silent if nothing to claim, prints on success)
config.json           # your config (gitignored)
config.json.example   # template with empty fields
token.json            # saved token (gitignored, auto-created)
token-backup.json     # backup copy (gitignored, auto-created)
claim_state.json      # actual claim history for rate display (gitignored, auto-created)
```

## Notes

- Your token is saved locally with `chmod 600`. Don't share `config.json` or `token.json`.
- If OTP doesn't arrive, the bot resends automatically (up to 3 times).
- No multi-account, no proxy rotation, no Node.js. One script, one account, one dependency.
- Group mining is claimed automatically every cycle. The dashboard shows "pending activation" until the server enables your group's rate.
- `burnedCycles` and `itlgRecoverable` are display-only — the API has no recovery endpoint yet. Recover through the app when available.

## License

MIT
