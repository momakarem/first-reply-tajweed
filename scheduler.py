"""
scheduler.py — Async scheduler for the monitoring window.

Flow:
  arm(dt)
    └─ sleeps until (dt - PRE_WINDOW) → activates monitoring
         └─ sleeps until (dt + POST_WINDOW) → deactivates + resets
"""

import asyncio
import logging
from datetime import datetime, timedelta

import config
import persistent_state
from state import state

log = logging.getLogger(__name__)


async def _run_window(target_dt: datetime, notify_cb=None) -> None:
    """
    Single coroutine that handles the full lifecycle:
      1. Sleep until window-open time.
      2. Activate monitoring.
      3. Sleep until window-close time.
      4. Deactivate monitoring and reset.

    notify_cb: optional async callable(text) for owner notifications.
    """
    open_dt  = target_dt - timedelta(minutes=config.PRE_WINDOW_MINUTES)
    close_dt = target_dt + timedelta(minutes=config.POST_WINDOW_MINUTES)

    # ── Phase 1: wait for window to open ─────────────────────────────────────
    now = datetime.now(tz=config.CAIRO_TZ)
    wait_open = (open_dt - now).total_seconds()

    if wait_open > 0:
        log.info("Scheduler: window opens in %.1f s (%s Cairo)", wait_open, open_dt.strftime("%H:%M:%S"))
        try:
            await asyncio.sleep(wait_open)
        except asyncio.CancelledError:
            log.info("Scheduler: arm task cancelled before window open")
            return

    # Guard against stale tasks: if a newer /arm replaced this one, bail out
    if state.scheduled_dt != target_dt:
        return

    # ── Phase 2: activate monitoring ─────────────────────────────────────────
    state.activate_monitoring()
    log.info("Scheduler: monitoring ACTIVATED at %s", datetime.now(tz=config.CAIRO_TZ).strftime("%H:%M:%S"))

    if notify_cb:
        try:
            await notify_cb(
                f"📡 Monitoring ACTIVATED\n"
                f"Window: {open_dt.strftime('%H:%M')} – {close_dt.strftime('%H:%M')} Cairo\n"
                f"Target time: {target_dt.strftime('%H:%M')} Cairo"
            )
        except Exception:
            pass

    # ── Phase 3: wait for window to close ────────────────────────────────────
    now2 = datetime.now(tz=config.CAIRO_TZ)
    wait_close = (close_dt - now2).total_seconds()

    if wait_close > 0:
        try:
            await asyncio.sleep(wait_close)
        except asyncio.CancelledError:
            log.info("Scheduler: window task cancelled during active monitoring")
            return

    # ── Phase 4: auto-close ──────────────────────────────────────────────────
    if state.reply_sent:
        # Reply was already sent; just clean up quietly
        log.info("Scheduler: window closed (reply was already sent)")
        persistent_state.clear_state()
        return

    state.deactivate_monitoring()
    log.info("Scheduler: monitoring DEACTIVATED (timeout, no reply sent)")
    persistent_state.clear_state()

    if notify_cb:
        try:
            await notify_cb("⏱ Monitoring window closed — no reply was sent.")
        except Exception:
            pass


def arm_scheduler(target_dt: datetime, notify_cb=None) -> None:
    """
    Cancel any existing arm tasks and launch a fresh window coroutine.
    Call from the /arm command handler.
    """
    # Cancel previous schedule
    state.cancel_arm_tasks()

    # Record the new schedule
    state.arm(target_dt)

    # Launch the window lifecycle task
    task = asyncio.ensure_future(_run_window(target_dt, notify_cb))
    state._arm_task = task

    log.info(
        "Scheduler: armed for %s Cairo (window %s – %s)",
        target_dt.strftime("%Y-%m-%d %H:%M"),
        (target_dt - timedelta(minutes=config.PRE_WINDOW_MINUTES)).strftime("%H:%M"),
        (target_dt + timedelta(minutes=config.POST_WINDOW_MINUTES)).strftime("%H:%M"),
    )
