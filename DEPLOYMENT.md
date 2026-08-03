# EasyPanel Deployment Guide


امر التشغيل: >>>  python main.py


Step-by-step guide to deploy First Reply Tajweed on EasyPanel.

## 1. Create the Service

1. Log into your EasyPanel dashboard
2. Click **"+ Create Service"** → **"App"**
3. Name it `first-reply-tajweed`

## 2. Connect Repository

- **Source**: GitHub / Git URL
- **Branch**: `main`
- **Build**: Dockerfile (auto-detected)

## 3. Environment Variables

Go to **Environment** tab and add all required variables:

```
API_ID=your_api_id
API_HASH=your_api_hash
PHONE=+201234567890
BOT_TOKEN=your_bot_token
OWNER_ID=your_telegram_user_id
TARGET_CHAT=-1001234567890
DEFAULT_REPLY_TEXT=مروة محروس 17
```

> ⚠️ Never put real credentials in the repo. Always use EasyPanel's environment settings.

## 4. Volume Mount

Go to **Volumes** tab and add:

| Mount Path | Volume Name |
|------------|-------------|
| `/app/sessions` | `sessions-data` |

This persists the Telethon session and armed state across container restarts.

## 5. Port Configuration

**No ports needed.** This bot uses outbound Telegram API polling only — no inbound HTTP traffic.

- Remove any port mappings EasyPanel auto-creates
- No domain/SSL required

## 6. Restart Policy

In **Advanced** settings:

- **Restart Policy**: `unless-stopped`
- This ensures the bot survives VPS reboots and OOM kills

## 7. First-Time Session Setup

Telethon requires an interactive login on first run:

1. **Deploy** the service in EasyPanel
2. Open the **Console/Shell** tab
3. Run: `python main.py`
4. Enter your phone number when prompted
5. Enter the verification code from Telegram
6. The session file is saved to `/app/sessions/`
7. **Restart** the service — it will now run non-interactively

## 8. Verify Deployment

After the service starts, check **Logs** in EasyPanel for:

```
✅ Control bot authorized: @YourBotName
✅ Owner reachable: YourName
✅ Userbot session valid: YourName
✅ Target chat accessible: 'ChatTitle'
─── All startup checks passed ───
>>> First-Reply system running.
```

Then in Telegram:
1. Open your bot chat
2. Type `/` — you should see the command menu
3. Send `/status` — verify response

## 9. Health Monitoring

The container includes a healthcheck that runs every 60s. EasyPanel will show the health status in the dashboard. If unhealthy for 3 consecutive checks, the container auto-restarts.

## 10. Crash Recovery

If the container restarts while armed:
- **Future schedule**: Automatically re-armed
- **Mid-monitoring**: Monitoring resumes if window still open
- **Reply sent**: Cleared, no duplicate
- **Expired**: Cleaned up

The owner receives a Telegram notification about any recovery action.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Bot doesn't respond | Check `OWNER_ID` matches your Telegram user ID |
| Session expired | Re-authenticate via EasyPanel console |
| Can't access target chat | Verify `TARGET_CHAT` ID and that userbot is a member |
| Container keeps restarting | Check logs for missing env vars |
| No slash command menu | Send any message to the bot first, then try `/` |

## Updating

1. Push code changes to your repo
2. In EasyPanel, click **"Rebuild"**
3. The volume preserves sessions — no re-authentication needed
