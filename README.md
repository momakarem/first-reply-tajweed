# First Reply Tajweed

Telegram auto-reply bot that monitors a target chat and instantly replies to the first photo message within a scheduled time window. Controlled remotely via a private Telegram bot.

## Features

- **Scheduled monitoring** — Arm a specific time, bot monitors ±3 min window
- **Sub-second reply** — Optimized for minimum latency
- **Remote control** — `/arm`, `/stop`, `/status` via Telegram slash commands
- **Crash recovery** — Persists armed state to disk, auto-recovers after restart
- **Security hardened** — Owner-only access, anti-spam, log redaction
- **Docker ready** — One-click deploy on EasyPanel

## Bot Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/arm HH:MM` | Arm monitoring for a time | `/arm 11:15` or `/arm 11:15pm` |
| `/stop` | Stop current monitoring | `/stop` |
| `/status` | Show current status | `/status` |

Commands appear automatically in Telegram's "/" menu.

## Prerequisites

1. **Telegram API credentials** — Get from [my.telegram.org](https://my.telegram.org) → API development tools
2. **Bot token** — Create via [@BotFather](https://t.me/BotFather)
3. **Your user ID** — Get from [@userinfobot](https://t.me/userinfobot)
4. **Target chat ID** — The group/channel to monitor

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_ID` | ✅ | Telegram API ID |
| `API_HASH` | ✅ | Telegram API Hash |
| `PHONE` | ✅ | Phone number (international format) |
| `BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `OWNER_ID` | ✅ | Your Telegram user ID |
| `TARGET_CHAT` | ✅ | Target chat username or ID |
| `DEFAULT_REPLY_TEXT` | ❌ | Reply message (default: `مروة محروس 17`) |
| `ALLOWED_SENDER_IDS` | ❌ | Comma-separated user IDs filter |
| `CAPTION_KEYWORD` | ❌ | Photo caption keyword filter |

## Quick Start (Docker)

```bash
# 1. Clone the repo
git clone <repo-url> && cd first-reply-tajweed

# 2. Create .env from template
cp .env.example .env
# Edit .env with your credentials

# 3. First run — authenticate Telethon session
docker compose run --rm first-reply

# 4. Production run
docker compose up -d
```

## Session Authentication

On **first run**, Telethon will ask for your phone number and verification code interactively. Run with `docker compose run --rm first-reply` to complete authentication. The session is stored in the `sessions_data` Docker volume and persists across restarts.

### Restoring a Session

If migrating to a new server:

```bash
# On old server — find the volume
docker volume inspect first-reply-tajweed_sessions_data

# Copy the session files, then on new server:
docker cp ./sessions/. first-reply-tajweed:/app/sessions/
```

Or use EasyPanel's volume management to back up and restore.

## EasyPanel Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for step-by-step EasyPanel instructions.

## Architecture

```
main.py              — Entry point, startup checks, crash recovery
control_bot.py       — Telegram bot commands (/arm /stop /status)
userbot.py           — Telethon personal account auto-reply
scheduler.py         — Async monitoring window lifecycle
state.py             — Shared runtime state with persistence hooks
persistent_state.py  — Crash-safe JSON state to disk
startup_checks.py    — Pre-flight connection verification
config.py            — Environment variable loader
```

## Security

- Only `OWNER_ID` can use bot commands — all others silently ignored
- `API_HASH` and `BOT_TOKEN` are redacted from all log output
- Anti-spam: 2-second cooldown between commands
- Atomic state file writes prevent corruption
- Session directory permission warnings on Linux

## License

Private project.
