"""
control_bot.py — Telegram Bot for remote management.

Commands (owner-only, registered as slash menu):
  /arm HH:MM [am|pm]  — Schedule the reply window.
  /stop               — Cancel everything.
  /status             — Show current state.

Features:
  - Inline keyboard for group selection after /arm
  - 15-second auto-default to first group
  - Rich status display with group info
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ConversationHandler,
    ContextTypes, MessageHandler, filters,
)

import config
from scheduler import arm_scheduler
from state import state

log = logging.getLogger(__name__)

# ── Anti-spam tracking ────────────────────────────────────────────────────────
_last_command_ts: dict[int, float] = {}

# ── Duplicate handler guard ───────────────────────────────────────────────────
_handlers_registered: bool = False

# ── Pending group selection (auto-select timer) ──────────────────────────────
_pending_auto_select: dict[int, asyncio.Task] = {}  # msg_id → timer task

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


def _owner_only_callback(handler):
    """Decorator for callback queries: silently ignore non-owner callbacks."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query is None:
            return
        user = query.from_user
        if user is None or user.id != config.OWNER_ID:
            await query.answer("⛔ غير مصرح", show_alert=True)
            return
        return await handler(update, ctx)
    return wrapper


# ── Time parser ───────────────────────────────────────────────────────────────

def _format_ampm(dt: datetime) -> str:
    """Format a datetime with Arabic-friendly AM/PM label."""
    hour = dt.hour
    if hour < 12:
        return dt.strftime("%Y-%m-%d %I:%M:%S") + " AM (صباحاً)"
    else:
        return dt.strftime("%Y-%m-%d %I:%M:%S") + " PM (مساءً)"


def _parse_time(raw: str) -> datetime | None:
    """
    Smart time parser — finds the nearest upcoming occurrence.

    Rules:
      - Accepts 12h format: "10:30", "1:15", "12:00"
      - Accepts explicit AM/PM: "10:30am", "10:30pm", "10:30 PM"
      - Without AM/PM: picks the NEAREST future time (tries both AM & PM)
      - If the time already passed today, schedules for tomorrow
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
    if minute > 59 or hour > 23:
        return None

    now = datetime.now(tz=config.CAIRO_TZ)

    # ── Explicit AM/PM specified ──────────────────────────────────────────
    if ampm == "am":
        if hour == 12:
            h24 = 0
        elif hour > 12:
            return None
        else:
            h24 = hour
        try:
            cand = now.replace(hour=h24, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None
        if cand <= now:
            cand += timedelta(days=1)
        return cand

    if ampm == "pm":
        if hour == 12:
            h24 = 12
        elif hour > 12:
            return None
        else:
            h24 = hour + 12
        try:
            cand = now.replace(hour=h24, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None
        if cand <= now:
            cand += timedelta(days=1)
        return cand

    # ── No AM/PM: find nearest future occurrence ─────────────────────────
    # For hours > 12 (24h input like 13:00, 22:30), use directly
    if hour > 12:
        try:
            cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            return None
        if cand <= now:
            cand += timedelta(days=1)
        return cand

    # For hours 1–12: try both AM and PM, pick the nearest future one
    candidates = []

    # AM candidate (hour 12 → 0, others stay)
    am_hour = 0 if hour == 12 else hour
    try:
        am_cand = now.replace(hour=am_hour, minute=minute, second=0, microsecond=0)
        if am_cand <= now:
            am_cand += timedelta(days=1)
        candidates.append(am_cand)
    except ValueError:
        pass

    # PM candidate (hour 12 → 12, others += 12)
    pm_hour = 12 if hour == 12 else hour + 12
    if pm_hour <= 23:
        try:
            pm_cand = now.replace(hour=pm_hour, minute=minute, second=0, microsecond=0)
            if pm_cand <= now:
                pm_cand += timedelta(days=1)
            candidates.append(pm_cand)
        except ValueError:
            pass

    if not candidates:
        return None

    # Return the nearest future time
    return min(candidates)


# ── Conversation state ────────────────────────────────────────────────────────
WAITING_TIME = 1


# ── Inline Keyboard builder ──────────────────────────────────────────────────

def _build_group_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard with one button per configured group."""
    buttons = []
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for idx, group in enumerate(config.GROUPS):
        emoji = emojis[idx] if idx < len(emojis) else f"#{idx+1}"
        buttons.append([
            InlineKeyboardButton(
                text=f"{emoji} {group['name']}",
                callback_data=f"group_{idx}",
            )
        ])
    return InlineKeyboardMarkup(buttons)


# ── Arm helpers ───────────────────────────────────────────────────────────────

async def _do_arm(update: Update, ctx: ContextTypes.DEFAULT_TYPE, time_str: str):
    """Shared arming logic — parses time, shows group selection keyboard."""
    target_dt = _parse_time(time_str)
    if target_dt is None:
        await update.message.reply_text(
            f"❌ Invalid time: `{time_str}`\n\n"
            "Use HH:MM format, e.g.:\n"
            "  11:15\n"
            "  11:15pm")
        return ConversationHandler.END

    old_note = ""
    if state.scheduled_dt:
        old_note = (
            f"\n⚠️ Replaced previous schedule "
            f"(was {state.scheduled_dt.strftime('%H:%M')} Cairo)")

    connect_dt = target_dt - timedelta(seconds=120)

    # Store target_dt in user_data for the callback handler
    ctx.user_data["pending_target_dt"] = target_dt
    ctx.user_data["pending_old_note"] = old_note

    # ── Single group → skip selection, arm immediately ────────────────────
    if len(config.GROUPS) == 1:
        group = config.GROUPS[0]
        await _finalize_arm(
            update=update, ctx=ctx,
            target_dt=target_dt, old_note=old_note,
            group_idx=0, group=group,
            message=update.message,
            is_callback=False,
        )
        return ConversationHandler.END

    # ── Multiple groups → show inline keyboard ────────────────────────────
    ampm_label = "PM (مساءً)" if target_dt.hour >= 12 else "AM (صباحاً)"
    keyboard = _build_group_keyboard()

    selection_msg = await update.message.reply_text(
        f"🎯 اختر الجروب المستهدف:{old_note}\n\n"
        f"⏰ الموعد: {target_dt.strftime('%I:%M')} {ampm_label}\n"
        f"🚀 بدء التحضير: {connect_dt.strftime('%I:%M:%S %p')}\n\n"
        f"⏳ سيتم اختيار الجروب الأول تلقائيًا خلال 15 ثانية...",
        reply_markup=keyboard,
    )

    # Store the selection message ID for the callback handler
    ctx.user_data["selection_msg_id"] = selection_msg.message_id
    ctx.user_data["selection_chat_id"] = selection_msg.chat_id

    # ── Auto-select timer (15 seconds) ────────────────────────────────────
    # Cancel any existing auto-select timer
    msg_id = selection_msg.message_id
    if msg_id in _pending_auto_select:
        _pending_auto_select[msg_id].cancel()

    async def _auto_select():
        try:
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            return

        # Auto-select first group
        group = config.GROUPS[0]
        log.info("Auto-selecting default group: %s (timeout)", group["name"])

        try:
            await _finalize_arm(
                update=update, ctx=ctx,
                target_dt=target_dt, old_note=old_note,
                group_idx=0, group=group,
                message=selection_msg,
                is_callback=True,
            )
        except Exception as exc:
            log.error("Auto-select failed: %s", exc)

        _pending_auto_select.pop(msg_id, None)

    task = asyncio.create_task(_auto_select())
    _pending_auto_select[msg_id] = task

    return ConversationHandler.END


async def _finalize_arm(
    *, update, ctx, target_dt, old_note, group_idx, group, message, is_callback
):
    """
    Complete the arming process after a group is selected.

    Steps:
      1. Switch target chat in userbot
      2. Update state with selected group
      3. Start the scheduler
      4. Edit the selection message with confirmation
    """
    from userbot import switch_target_chat

    group_id = group["id"]
    group_name = group["name"]

    connect_dt = target_dt - timedelta(seconds=120)
    close_dt   = target_dt + timedelta(seconds=180)

    # ── Switch userbot target ─────────────────────────────────────────────
    try:
        await switch_target_chat(group_id)
    except Exception as exc:
        error_text = f"❌ فشل الاتصال بالجروب: {group_name}\n\n{exc}"
        if is_callback:
            try:
                await message.edit_text(error_text)
            except Exception:
                pass
        else:
            await message.reply_text(error_text)
        return

    # ── Update state ──────────────────────────────────────────────────────
    state.selected_group_id = group_id
    state.selected_group_name = group_name

    # ── Arm scheduler ─────────────────────────────────────────────────────
    bot = ctx.application.bot

    async def notify(text: str):
        try:
            await bot.send_message(chat_id=config.OWNER_ID, text=text)
        except Exception as e:
            log.warning("notify failed: %s", e)

    arm_scheduler(target_dt, notify_cb=notify)

    # ── Build confirmation text ───────────────────────────────────────────
    ampm_label = "PM (مساءً)" if target_dt.hour >= 12 else "AM (صباحاً)"
    confirm_text = (
        f"✅ تم اختيار:\n"
        f"{group_name}\n\n"
        f"⏰ الموعد: {target_dt.strftime('%I:%M')} {ampm_label}\n"
        f"🚀 بدء التحضير: {connect_dt.strftime('%I:%M:%S %p')}\n"
        f"🎯 وضع القنص جاهز"
    )

    if old_note:
        confirm_text += f"\n{old_note}"

    # ── Edit message in place ─────────────────────────────────────────────
    if is_callback:
        try:
            await message.edit_text(confirm_text)
        except Exception as exc:
            log.warning("Failed to edit selection message: %s", exc)
    else:
        await message.reply_text(confirm_text)

    log.info(
        "Armed for %s | Group: %s | Target: %s Cairo",
        target_dt.strftime("%H:%M:%S"),
        group_name,
        target_dt.strftime("%Y-%m-%d %H:%M:%S"),
    )


# ── Callback handler for group selection ──────────────────────────────────────

@_owner_only_callback
async def _on_group_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button press for group selection."""
    query = update.callback_query
    await query.answer()

    data = query.data  # e.g. "group_0", "group_1", ...
    if not data or not data.startswith("group_"):
        return

    try:
        group_idx = int(data.split("_")[1])
    except (IndexError, ValueError):
        return

    if group_idx < 0 or group_idx >= len(config.GROUPS):
        return

    group = config.GROUPS[group_idx]

    # Cancel auto-select timer
    msg_id = query.message.message_id
    timer = _pending_auto_select.pop(msg_id, None)
    if timer:
        timer.cancel()

    # Retrieve pending arm data from user_data
    target_dt = ctx.user_data.get("pending_target_dt")
    old_note = ctx.user_data.get("pending_old_note", "")

    if target_dt is None:
        await query.message.edit_text("❌ انتهت صلاحية الأمر. أعد /arm")
        return

    await _finalize_arm(
        update=update, ctx=ctx,
        target_dt=target_dt, old_note=old_note,
        group_idx=group_idx, group=group,
        message=query.message,
        is_callback=True,
    )

    # Clean up user_data
    ctx.user_data.pop("pending_target_dt", None)
    ctx.user_data.pop("pending_old_note", None)
    ctx.user_data.pop("selection_msg_id", None)
    ctx.user_data.pop("selection_chat_id", None)


# ── Command handlers ──────────────────────────────────────────────────────────

@_owner_only
async def cmd_arm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        # No time provided → ask for it
        await update.message.reply_text(
            "🕐 Write the time\n\n"
            "Example: 11:15 or 11:15pm")
        return WAITING_TIME

    # Time provided directly → show group selection
    return await _do_arm(update, ctx, args[0])


@_owner_only
async def _arm_receive_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handles the time message after /arm was sent without args."""
    time_str = update.message.text.strip()
    return await _do_arm(update, ctx, time_str)


async def _arm_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


@_owner_only
async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Cancel any pending auto-select timers
    for msg_id, timer in list(_pending_auto_select.items()):
        timer.cancel()
    _pending_auto_select.clear()

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
        arm_conv = ConversationHandler(
            entry_points=[CommandHandler("arm", cmd_arm)],
            states={
                WAITING_TIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, _arm_receive_time),
                ],
            },
            fallbacks=[
                CommandHandler("stop", _arm_cancel),
                CommandHandler("arm", cmd_arm),
            ],
            conversation_timeout=60,
        )
        app.add_handler(arm_conv)
        app.add_handler(CallbackQueryHandler(_on_group_selected, pattern=r"^group_\d+$"))
        app.add_handler(CommandHandler("stop", cmd_stop))
        app.add_handler(CommandHandler("status", cmd_status))
        _handlers_registered = True
        log.info("Control bot configured with /arm /stop /status + inline group selection")
    return app
