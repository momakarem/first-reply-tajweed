"""
main.py — Process entry point.
Runs the Telethon userbot AND python-telegram-bot control bot
in a single asyncio event loop.

Includes: startup checks, crash recovery, log redaction, graceful reconnect.
"""

import asyncio
import logging
import os
import re
import signal
import sys
import warnings
from datetime import datetime, timedelta

# Suppress python-telegram-bot internal warnings
warnings.filterwarnings("ignore", category=UserWarning, module=r"telegram\.")

os.makedirs("sessions", exist_ok=True)

from userbot import build_userbot
from control_bot import build_control_bot
from startup_checks import run_all_checks
from scheduler import arm_scheduler
from state import state
import config
import persistent_state


# ── Log redaction filter ──────────────────────────────────────────────────────

class _RedactFilter(logging.Filter):
    """Prevent sensitive values (API_HASH, BOT_TOKEN) from appearing in logs."""

    def __init__(self):
        super().__init__()
        # Build regex from actual sensitive values
        patterns = []
        for val in config._SENSITIVE_VALUES:
            if val and len(val) > 6:
                patterns.append(re.escape(val))
        self._re = re.compile("|".join(patterns)) if patterns else None

    def filter(self, record: logging.LogRecord) -> bool:
        if self._re and isinstance(record.msg, str):
            record.msg = self._re.sub("***REDACTED***", record.msg)
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("first_reply.log", encoding="utf-8"),
    ],
)

# Apply redaction filter to root logger
logging.getLogger().addFilter(_RedactFilter())

for name in ("telethon", "httpx", "httpcore", "telegram", "apscheduler"):
    logging.getLogger(name).setLevel(logging.WARNING)

log = logging.getLogger("main")


# ── Crash recovery ────────────────────────────────────────────────────────────

async def _try_recover_state(notify_cb) -> None:
    """
    Attempt to restore armed schedule from persistent storage.

    Handles 4 scenarios:
      1. Future schedule → re-arm
      2. Mid-window, reply not sent → resume monitoring
      3. Mid-window, reply already sent → clear
      4. Expired window → clear
    """
    saved = persistent_state.load_state()
    if saved is None:
        log.info("No previous state to recover")
        return

    try:
        scheduled_dt = datetime.fromisoformat(saved["scheduled_dt"])
        reply_sent = bool(saved.get("reply_sent", False))
        reply_text = saved.get("reply_text", config.DEFAULT_REPLY_TEXT)
        group_id = saved.get("group_id", "")
        group_name = saved.get("group_name", "")
    except (ValueError, KeyError) as exc:
        log.warning("Invalid saved state, clearing: %s", exc)
        persistent_state.clear_state()
        return

    now = datetime.now(tz=config.CAIRO_TZ)
    open_dt = scheduled_dt - timedelta(minutes=config.PRE_WINDOW_MINUTES)
    close_dt = scheduled_dt + timedelta(minutes=config.POST_WINDOW_MINUTES)

    recovery_msg = ""

    if now < open_dt:
        # Future schedule — re-arm
        state.reply_text = reply_text
        if group_id:
            state.selected_group_id = group_id
            state.selected_group_name = group_name
        arm_scheduler(scheduled_dt, notify_cb=notify_cb)
        state.recovered_from_disk = True
        recovery_msg = (
            f"🔄 Recovered future schedule: "
            f"{scheduled_dt.strftime('%H:%M')} Cairo"
        )
        log.info(recovery_msg)

    elif now <= close_dt and not reply_sent:
        # Mid-window, reply not sent — resume monitoring
        state.scheduled_dt = scheduled_dt
        state.reply_text = reply_text
        state.reply_sent = False
        if group_id:
            state.selected_group_id = group_id
            state.selected_group_name = group_name
        state.activate_monitoring()
        state.recovered_from_disk = True

        # Launch a timer for remaining window
        remaining = (close_dt - now).total_seconds()

        async def _close_window():
            try:
                await asyncio.sleep(remaining)
            except asyncio.CancelledError:
                return
            if not state.reply_sent:
                state.deactivate_monitoring()
                persistent_state.clear_state()
                log.info("Recovered window closed (timeout)")
                if notify_cb:
                    try:
                        await notify_cb(
                            "⏱ Monitoring window closed — no reply sent."
                        )
                    except Exception:
                        pass

        state._arm_task = asyncio.create_task(_close_window())
        recovery_msg = (
            f"🔄 Resumed active monitoring "
            f"(window closes at {close_dt.strftime('%H:%M')} Cairo)"
        )
        log.info(recovery_msg)

    elif now <= close_dt and reply_sent:
        # Reply was already sent — clear
        persistent_state.clear_state()
        state.recovered_from_disk = True
        recovery_msg = "✅ Reply was already sent before restart"
        log.info(recovery_msg)

    else:
        # Expired
        persistent_state.clear_state()
        recovery_msg = (
            f"⏱ Recovered schedule expired "
            f"(was {scheduled_dt.strftime('%H:%M')} Cairo), clearing"
        )
        log.info(recovery_msg)

    # Notify owner about recovery
    if notify_cb and recovery_msg:
        try:
            await notify_cb(f"🔄 System restarted.\n{recovery_msg}")
        except Exception:
            pass


# ── Control bot runner ────────────────────────────────────────────────────────

async def _run_control_bot(app) -> None:
    """Keep the control bot alive. Bot is already initialized and polling."""
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        log.info("Control bot shut down.")


# ── Main ──────────────────────────────────────────────────────────────────────

async def _async_main() -> None:
    loop = asyncio.get_running_loop()
    control_app = build_control_bot()

    # ── Step 1: Start Control Bot FIRST (so it can send/receive messages) ──
    await control_app.initialize()
    await control_app.start()
    await control_app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )
    log.info("Control bot started — polling for updates.")

    async def _notify(text: str):
        try:
            await control_app.bot.send_message(
                chat_id=config.OWNER_ID, text=text)
        except Exception as exc:
            log.warning("Notify failed: %s", exc)

    # ── Step 2: Build Telegram-based verification callbacks ───────────────
    # Future that will hold the owner's reply (code or password)
    _pending_future: asyncio.Future | None = None

    async def _verification_reply_handler(update, context):
        """Temporary handler: captures owner's text reply during login."""
        nonlocal _pending_future
        if update.message is None or update.effective_user is None:
            return
        if update.effective_user.id != config.OWNER_ID:
            return
        if _pending_future is not None and not _pending_future.done():
            _pending_future.set_result(update.message.text.strip())
            # Stop propagation — don't let other handlers process this message
            from telegram.ext import ApplicationHandlerStop
            raise ApplicationHandlerStop

    # Register temporary handler (group=-1 so it runs before other handlers)
    from telegram.ext import MessageHandler, filters
    temp_handler = MessageHandler(
        filters.TEXT & ~filters.COMMAND, _verification_reply_handler
    )
    control_app.add_handler(temp_handler, group=-1)

    async def code_callback():
        """Ask owner for verification code via Telegram, wait for reply."""
        nonlocal _pending_future
        _pending_future = loop.create_future()
        await _notify(
            "🔐 كود التحقق مطلوب!\n\n"
            "تليجرام بعتلك كود تحقق.\n"
            "⚠️ مهم: ابعت الكود *بمسافات* بين الأرقام عشان تليجرام ما يلغيهوش!\n\n"
            "مثال: 1 2 3 4 5\n\n"
            "ابعت الكود هنا 👇"
        )
        log.info("Verification code requested via Telegram — waiting for owner reply…")
        raw = await asyncio.wait_for(_pending_future, timeout=300)
        # Strip non-digit characters (user sends code with spaces to bypass
        # Telegram's anti-phishing detection that blocks shared login codes)
        code = re.sub(r'\D', '', raw)
        log.info("Verification code received from owner (cleaned: %s chars).", len(code))
        return code

    async def password_callback():
        """Ask owner for 2FA password via Telegram, wait for reply."""
        nonlocal _pending_future
        _pending_future = loop.create_future()
        await _notify(
            "🔑 كلمة سر التحقق بخطوتين (2FA) مطلوبة!\n\n"
            "ابعت الباسورد هنا 👇"
        )
        log.info("2FA password requested via Telegram — waiting for owner reply…")
        password = await asyncio.wait_for(_pending_future, timeout=300)
        log.info("2FA password received from owner.")
        return password

    # ── Step 3: Build userbot (may trigger code/password callbacks) ────────
    try:
        userbot_client = await build_userbot(
            notify_cb=_notify,
            code_callback=code_callback,
            password_callback=password_callback,
        )
        log.info("Userbot ready.")
    except asyncio.TimeoutError:
        log.error("Login timed out — owner did not reply within 5 minutes.")
        await _notify("❌ انتهت المهلة! ما ردتش بالكود خلال 5 دقايق.\nشغّل البوت تاني.")
        await control_app.updater.stop()
        await control_app.stop()
        await control_app.shutdown()
        return
    except Exception as exc:
        log.error("Userbot login FAILED: %s", exc)
        await _notify(f"❌ فشل تسجيل الدخول:\n{exc}")
        await control_app.updater.stop()
        await control_app.stop()
        await control_app.shutdown()
        return
    finally:
        # Remove temporary verification handler — no longer needed
        control_app.remove_handler(temp_handler, group=-1)
        log.info("Temporary verification handler removed.")

    # ── Step 4: Startup checks ────────────────────────────────────────────
    try:
        target_title = await run_all_checks(
            control_app.bot, userbot_client
        )
        state.target_chat_name = target_title
    except Exception as exc:
        log.error("Startup check FAILED: %s", exc)
        await userbot_client.disconnect()
        await control_app.updater.stop()
        await control_app.stop()
        await control_app.shutdown()
        return

    # ── Step 5: Crash recovery ────────────────────────────────────────────
    await _try_recover_state(notify_cb=_notify)

    # ── Step 6: Main loop — Control Bot already running ───────────────────
    control_task = asyncio.create_task(
        _run_control_bot(control_app), name="control_bot")

    shutdown_event = asyncio.Event()

    def _handle_signal(sig):
        log.info("Received %s — shutting down…", sig.name)
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except NotImplementedError:
            pass

    log.info(">>> First-Reply system running (persistent service mode).")
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        control_task.cancel()
        state.cancel_arm_tasks()
        await asyncio.gather(control_task, return_exceptions=True)
        await userbot_client.disconnect()
        log.info("Bye!")


def main() -> None:
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
