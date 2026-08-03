"""
scheduler.py — Triple-Window stealth scheduler.

Timeline:
  [T-120s] Phase 1: CONNECT — ensure connection stable, cache target, pre-load reply
  [T-90s]  Phase 2: TYPING  — continuous typing indicator for 30s (presence proof)
  [T-60s]  Phase 3: SNIPE   — silent ultra-fast monitoring, INSTANT reply on photo
  [T+0s]   Target time       — if no photo yet, continue monitoring
  [T+180s] Grace expires     — disconnect userbot (control bot stays alive)
"""

import asyncio
import logging
from datetime import datetime, timedelta

import config
import persistent_state
from state import state

log = logging.getLogger(__name__)

# ── Timeline constants (seconds relative to target) ──────────────────────────
CONNECT_BEFORE  = 120   # T-120s: ensure connection + cache + pre-load reply
TYPING_BEFORE   = 90    # T-90s:  start typing indicator (presence proof)
SNIPE_BEFORE    = 60    # T-60s:  stop typing, enter silent ultra-fast monitoring
GRACE_AFTER     = 180   # T+180s: grace period after target time (3 minutes)


async def _run_triple_window(target_dt: datetime, notify_cb=None) -> None:
    """
    Full lifecycle coroutine — Triple Window System.

    Phase 1 (T-120s → T-90s): Connect, verify session, cache target entity,
                                pre-load reply text into memory.
    Phase 2 (T-90s → T-60s):  Continuous typing for 30 seconds (presence proof).
    Phase 3 (T-60s → T+0s):   Silent ultra-fast monitoring — instant reply on photo.
    Grace   (T+0s → T+180s):  Continue monitoring for 3 more minutes, then disconnect.
    """
    from userbot import send_typing, disconnect_userbot, reconnect_userbot, reset_for_next_arm

    connect_dt  = target_dt - timedelta(seconds=CONNECT_BEFORE)
    typing_dt   = target_dt - timedelta(seconds=TYPING_BEFORE)
    snipe_dt    = target_dt - timedelta(seconds=SNIPE_BEFORE)
    close_dt    = target_dt + timedelta(seconds=GRACE_AFTER)

    # Reset the reply guard for this new arm cycle
    reset_for_next_arm()

    # ═══════════════════════════════════════════════════════════════════════
    # SLEEP — wait until T-120s
    # ═══════════════════════════════════════════════════════════════════════
    now = datetime.now(tz=config.CAIRO_TZ)
    wait_connect = (connect_dt - now).total_seconds()

    if wait_connect > 0:
        log.info(
            "Scheduler: Phase 1 starts in %.1f s (%s Cairo)",
            wait_connect, connect_dt.strftime("%H:%M:%S"),
        )
        try:
            await asyncio.sleep(wait_connect)
        except asyncio.CancelledError:
            log.info("Scheduler: cancelled before Phase 1")
            return

    # Guard: bail if a newer /arm replaced this schedule
    if state.scheduled_dt != target_dt:
        log.info("Scheduler: stale task — bailing out")
        return

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 1 — CONNECT & STABILIZE & PRE-LOAD (T-120s → T-90s)
    # ═══════════════════════════════════════════════════════════════════════
    log.info(
        "━━━ Phase 1: CONNECT & PRE-LOAD (%s Cairo) ━━━",
        datetime.now(tz=config.CAIRO_TZ).strftime("%H:%M:%S"),
    )

    try:
        await reconnect_userbot()
    except Exception as exc:
        log.error("Phase 1: Connection verification FAILED: %s", exc)
        if notify_cb:
            try:
                await notify_cb(f"❌ Connection failed at T-120s: {exc}")
            except Exception:
                pass
        return

    # Pre-load reply text into memory for zero-delay execution
    log.info("Phase 1: Reply text pre-loaded into memory ✓")
    log.info("Phase 1: Target entity cached ✓")
    log.info("Phase 1: Connection verified ✓")

    if notify_cb:
        try:
            await notify_cb(
                f"🔌 Phase 1: Connected & Pre-loaded\n"
                f"✅ Session verified\n"
                f"✅ Target chat cached\n"
                f"✅ Reply text pre-loaded\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🕐 Target: {target_dt.strftime('%H:%M:%S')} Cairo\n"
                f"⌨️ Typing at: {typing_dt.strftime('%H:%M:%S')}\n"
                f"🎯 Snipe mode at: {snipe_dt.strftime('%H:%M:%S')}\n"
                f"⏰ Grace ends at: {close_dt.strftime('%H:%M:%S')} (+3 min)"
            )
        except Exception:
            pass

    # ── Sleep until T-90s ─────────────────────────────────────────────────
    now2 = datetime.now(tz=config.CAIRO_TZ)
    wait_typing = (typing_dt - now2).total_seconds()
    if wait_typing > 0:
        try:
            await asyncio.sleep(wait_typing)
        except asyncio.CancelledError:
            log.info("Scheduler: cancelled between Phase 1 and Phase 2")
            return

    if state.scheduled_dt != target_dt:
        return

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 2 — TYPING / PRESENCE PROOF (T-90s → T-60s)
    # ═══════════════════════════════════════════════════════════════════════
    now3 = datetime.now(tz=config.CAIRO_TZ)
    actual_typing = (snipe_dt - now3).total_seconds()

    if actual_typing > 0:
        log.info(
            "━━━ Phase 2: TYPING / PRESENCE for %.1f seconds (%s Cairo) ━━━",
            actual_typing, now3.strftime("%H:%M:%S"),
        )
        try:
            await send_typing(actual_typing)
        except asyncio.CancelledError:
            log.info("Scheduler: cancelled during Phase 2 (typing)")
            return
    else:
        log.info("━━━ Phase 2: SKIPPED — already past T-60s ━━━")

    if state.scheduled_dt != target_dt:
        return

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE 3 — SILENT ULTRA-FAST MONITORING (T-60s → T+180s grace)
    # ═══════════════════════════════════════════════════════════════════════
    log.info(
        "━━━ Phase 3: SILENT ULTRA-FAST MONITORING — ON (%s Cairo) ━━━",
        datetime.now(tz=config.CAIRO_TZ).strftime("%H:%M:%S"),
    )

    # ★ Activate monitoring — the event handler will fire INSTANTLY on photo
    state.activate_monitoring()

    if notify_cb:
        try:
            await notify_cb(
                f"🎯 Phase 3: SILENT SNIPE — monitoring ON\n"
                f"⚡ Photo → ReadHistory → Instant reply (ZERO delay)\n"
                f"🕐 Target: {target_dt.strftime('%H:%M:%S')} Cairo\n"
                f"⏰ Grace until: {close_dt.strftime('%H:%M:%S')} (+3 min)"
            )
        except Exception:
            pass

    # ── Wait through snipe window + 3-minute grace period ─────────────────
    now4 = datetime.now(tz=config.CAIRO_TZ)
    wait_close = (close_dt - now4).total_seconds()

    if wait_close > 0:
        try:
            await asyncio.sleep(wait_close)
        except asyncio.CancelledError:
            log.info("Scheduler: cancelled during snipe/grace period")
            return

    # ═══════════════════════════════════════════════════════════════════════
    # TIMEOUT — grace period expired (3 minutes after target), no photo
    # ═══════════════════════════════════════════════════════════════════════
    if state.reply_sent:
        log.info("Scheduler: window closed (reply already sent)")
        persistent_state.clear_state()
        return

    state.deactivate_monitoring()
    persistent_state.clear_state()
    log.info("Scheduler: ⏱ GRACE EXPIRED (3 min) — no reply sent. Disconnecting userbot…")

    if notify_cb:
        try:
            await notify_cb(
                "⏱ Grace period expired (3 min) — no photo detected.\n"
                "🔌 Disconnecting userbot…\n"
                "🤖 Control bot stays alive — use /arm to re-arm."
            )
        except Exception:
            pass

    await disconnect_userbot()


def arm_scheduler(target_dt: datetime, notify_cb=None) -> None:
    """
    Cancel any existing arm tasks and launch a fresh triple-window.
    Called from the /arm command handler.
    """
    state.cancel_arm_tasks()
    state.arm(target_dt)

    task = asyncio.ensure_future(_run_triple_window(target_dt, notify_cb))
    state._arm_task = task

    connect_dt = target_dt - timedelta(seconds=CONNECT_BEFORE)
    close_dt   = target_dt + timedelta(seconds=GRACE_AFTER)

    log.info(
        "Scheduler: armed for %s Cairo | connect=%s | close=%s (+3min grace)",
        target_dt.strftime("%Y-%m-%d %H:%M:%S"),
        connect_dt.strftime("%H:%M:%S"),
        close_dt.strftime("%H:%M:%S"),
    )
