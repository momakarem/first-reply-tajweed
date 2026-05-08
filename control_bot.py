"""
control_bot.py — Telegram Bot for remote management.

Commands (owner-only, registered as slash menu):
  /arm HH:MM [am|pm]  — Schedule the reply window.
  /stop               — Cancel everything.
  /status             — Show current state.
"""

import logging
import re
import time
from datetime import datetime, timedelta

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from scheduler import arm_scheduler
from state import state

log = logging.getLogger(__name__)

# ── Anti-spam tracking ────────────────────────────────────────────────────────
_last_command_ts: dict[int, float] = {}

# ── Duplicate handler guard ───────────────────────────────────────────────────
_handlers_registered: bool = False

# ── Slash command menu ────────────────────────────────────────────────────────
_BOT_COMMANDS = [
    BotCommand("arm", "Arm monitoring for a specific time"),
    BotCommand("stop", "Stop current monitoring"),
    BotCommand("status", "Show current status"),
]


async def _register_commands(app: Application) -> None:
    """Register slash commands with Telegram (called once at startup)."""
    try:
        await app.bot.set_my_commands(_BOT_COMMANDS)
        log.info("Slash command menu registered: /arm /stop /status")
    except Exception as exc:
        log.warning("Failed to register slash commands: %s", exc)


# ── Security decorator ────────────────────────────────────────────────────────

def _owner_only(handler):
    """Decorator: silently ignore non-owner messages, enforce anti-spam."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.message is None:
            return
        user = update.effective_user
        if user is None or user.id != config.OWNER_ID:
            uid = user.id if user else "unknown"
            log.warning("Unauthorized command attempt from user_id=%s", uid)
            return
        # Anti-spam
        now = time.monotonic()
        last = _last_command_ts.get(user.id, 0)
        if now - last < config.ANTI_SPAM_COOLDOWN_SEC:
            return
        _last_command_ts[user.id] = now
        return await handler(update, ctx)
    return wrapper


# ── Time parser ───────────────────────────────────────────────────────────────

def _parse_time(raw: str) -> datetime | None:
    """
    Parse time string into Cairo-aware datetime.
    Supports: "11:15", "11:15pm", "11:15am", "11:15 PM"
    """
    raw = raw.strip().lower().replace(" ", "")

    ampm = None
    if raw.endswith("am"):
        ampm = "am"
        raw = raw[:-2]
    elif raw.endswith("pm"):
        ampm = "pm"
        raw = raw[:-2]

    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not m:
        return None

    hour, minute = int(m.group(1)), int(m.group(2))
    if minute > 59:
        return None

    now = datetime.now(tz=config.CAIRO_TZ)

    if ampm == "am":
        if hour == 12:
            hour = 0
        elif hour > 12:
            return None
    elif ampm == "pm":
        if hour == 12:
            pass
        elif hour > 12:
            return None
        else:
            hour += 12
    else:
        if hour > 23:
            return None
        if hour <= 12:
            if now.hour < 12:
                cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if cand <= now:
                    cand = now.replace(
                        hour=hour + 12 if hour < 12 else hour,
                        minute=minute, second=0, microsecond=0)
            else:
                pm_hour = hour + 12 if hour < 12 else hour
                cand = now.replace(
                    hour=min(pm_hour, 23), minute=minute,
                    second=0, microsecond=0)
                if cand <= now:
                    cand = (now + timedelta(days=1)).replace(
                        hour=hour if hour != 12 else 0,
                        minute=minute, second=0, microsecond=0)
            return cand

    try:
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return None
    if cand <= now:
        cand += timedelta(days=1)
    return cand


# ── Command handlers ──────────────────────────────────────────────────────────

@_owner_only
async def cmd_arm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "📋 Usage: /arm HH:MM\n\n"
            "Examples:\n"
            "  /arm 11:15\n"
            "  /arm 11:15pm")
        return

    target_dt = _parse_time(args[0])
    if target_dt is None:
        await update.message.reply_text(
            f"❌ Invalid time format: `{args[0]}`\n\n"
            "Use HH:MM format, e.g.:\n"
            "  /arm 11:15\n"
            "  /arm 11:15pm")
        return

    old_note = ""
    if state.scheduled_dt:
        old_note = (
            f"\n⚠️ Replaced previous schedule "
            f"(was {state.scheduled_dt.strftime('%H:%M')} Cairo)")

    open_dt = target_dt - timedelta(minutes=config.PRE_WINDOW_MINUTES)
    close_dt = target_dt + timedelta(minutes=config.POST_WINDOW_MINUTES)

    bot = ctx.application.bot

    async def notify(text: str):
        try:
            await bot.send_message(chat_id=config.OWNER_ID, text=text)
        except Exception as e:
            log.warning("notify failed: %s", e)

    arm_scheduler(target_dt, notify_cb=notify)

    await update.message.reply_text(
        f"✅ Armed!{old_note}\n"
        f"🕐 Scheduled: {target_dt.strftime('%Y-%m-%d %H:%M')} Cairo\n"
        f"📡 Window: {open_dt.strftime('%H:%M')} – {close_dt.strftime('%H:%M')}\n"
        f"💬 Reply text: {state.reply_text}")


@_owner_only
async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state.reset()
    await update.message.reply_text(
        "🛑 Stopped. All schedules cancelled.\nUse /arm to re-arm.")


@_owner_only
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    now_cairo = datetime.now(tz=config.CAIRO_TZ)
    await update.message.reply_text(
        f"{state.status_text()}\n\n"
        f"🕰 Now: {now_cairo.strftime('%Y-%m-%d %H:%M:%S')} Cairo")


# ── Application builder ──────────────────────────────────────────────────────

def build_control_bot() -> Application:
    global _handlers_registered
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(_register_commands)
        .build()
    )
    if not _handlers_registered:
        app.add_handler(CommandHandler("arm", cmd_arm))
        app.add_handler(CommandHandler("stop", cmd_stop))
        app.add_handler(CommandHandler("status", cmd_status))
        _handlers_registered = True
        log.info("Control bot configured with /arm /stop /status")
    return app
