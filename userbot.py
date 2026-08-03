"""
userbot.py — Telethon personal-account userbot (Persistent Service Edition).

Anti-detection features:
  - Device identity spoofing (Telegram Desktop)
  - ReadHistoryRequest before every reply
  - Content rotation (4 linguistic variants)
  - Typing simulation phases (managed by scheduler)
  - incoming+photo event filter only
  - Boolean double-response guard
  - Userbot disconnect after reply (control bot stays alive)

Zero-delay reply mode:
  - NO artificial delay (no sleep, no hard_delay)
  - ReadHistoryRequest → Instant reply
  - Measures actual network latency only

Persistent service mode:
  - Control bot runs forever in main loop
  - Userbot connects/disconnects per arm cycle
  - No os._exit() — ready for next /arm after each task

Supports two session modes:
  1. TELETHON_SESSION env var (StringSession) — Docker/EasyPanel
  2. File-based session at sessions/userbot.session — local dev
"""

import asyncio
import logging
import os
import random
import time
from datetime import datetime

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.functions.messages import ReadHistoryRequest
from telethon.tl.types import MessageMediaPhoto

import config
from state import state

log = logging.getLogger(__name__)

# ── Module-level references ───────────────────────────────────────────────────
_client: TelegramClient | None = None
_target_entity = None
_notify_cb = None

# ── Double-response guard (atomic boolean) ────────────────────────────────────
_reply_fired: bool = False

# ── Content rotation: 4 linguistic variants ───────────────────────────────────
REPLY_VARIANTS = [
    "مروه محروس 17",
    "مروه محروس ١٧",
    "مروة محروس 17",
    "مروة محروس ١٧",
]

# ── Device identity: Telegram Desktop ─────────────────────────────────────────
_DEVICE_MODEL = "Desktop"
_SYSTEM_VERSION = "Windows 11"
_APP_VERSION = "Telegram Desktop 7.0.4"
_LANG_CODE = "ar"
_SYSTEM_LANG_CODE = "ar-eg"


def get_client() -> TelegramClient:
    return _client


def _create_client(session) -> TelegramClient:
    """Create TelegramClient with realistic device fingerprint."""
    return TelegramClient(
        session,
        config.API_ID,
        config.API_HASH,
        device_model=_DEVICE_MODEL,
        system_version=_SYSTEM_VERSION,
        app_version=_APP_VERSION,
        lang_code=_LANG_CODE,
        system_lang_code=_SYSTEM_LANG_CODE,
        connection_retries=-1,
        auto_reconnect=True,
        flood_sleep_threshold=300,
    )


async def build_userbot(
    notify_cb=None,
    code_callback=None,
    password_callback=None,
) -> TelegramClient:
    """
    Initialize userbot with spoofed device identity.

    Args:
        notify_cb: async callable to send status notifications to the owner.
        code_callback: async callable that returns the verification code string.
                       If None, Telethon falls back to input() (terminal).
        password_callback: async callable that returns the 2FA password string.
                           If None, Telethon falls back to input() (terminal).
    """
    global _client, _target_entity, _notify_cb
    _notify_cb = notify_cb

    session_string = os.environ.get("TELETHON_SESSION", "").strip()

    if session_string:
        log.info("Using StringSession from TELETHON_SESSION env var")
        _client = _create_client(StringSession(session_string))
        await _client.connect()
        if not await _client.is_user_authorized():
            log.error("StringSession is NOT authorized. Re-run create_session.py")
            raise RuntimeError("StringSession expired — re-run create_session.py")
    else:
        log.info("Using file-based session: %s", config.USERBOT_SESSION)
        _client = _create_client(config.USERBOT_SESSION)

        # Build start() kwargs — only pass callbacks if provided
        start_kwargs = {"phone": config.PHONE}
        if code_callback is not None:
            start_kwargs["code_callback"] = code_callback
        if password_callback is not None:
            start_kwargs["password"] = password_callback

        try:
            await _client.start(**start_kwargs)
        except FloodWaitError as e:
            log.warning("FloodWait %ds — sleeping…", e.seconds)
            await asyncio.sleep(e.seconds + 5)
            await _client.start(**start_kwargs)

    me = await _client.get_me()
    log.info(
        "Userbot connected as %s (id=%s) | device=%s",
        me.first_name, me.id, _DEVICE_MODEL,
    )

    # Resolve target chat entity once
    try:
        raw = config.TARGET_CHAT
        try:
            _target_entity = await _client.get_entity(int(raw))
        except ValueError:
            _target_entity = await _client.get_entity(raw)
        title = getattr(_target_entity, "title", str(_target_entity.id))
        log.info("Target chat: '%s' (id=%s)", title, _target_entity.id)
    except Exception as exc:
        log.error("Cannot resolve TARGET_CHAT '%s': %s", config.TARGET_CHAT, exc)
        raise

    # ── Event handler: incoming photos ONLY ───────────────────────────────
    _client.add_event_handler(
        _on_photo_message,
        events.NewMessage(
            chats=_target_entity,
            incoming=True,
            func=lambda e: e.photo,  # photo=True filter
        ),
    )
    log.info("Stealth event handler registered (incoming photos only).")
    return _client


async def send_typing(duration_seconds: float) -> None:
    """
    Send continuous typing action for the specified duration.
    Used by the scheduler during the preparation phase.
    """
    if not _client or not _target_entity:
        return

    end_time = asyncio.get_event_loop().time() + duration_seconds
    log.info("Typing simulation started for %.0f seconds", duration_seconds)

    while asyncio.get_event_loop().time() < end_time:
        try:
            async with _client.action(_target_entity, "typing"):
                # Each action lasts ~5 seconds; sleep slightly less to maintain overlap
                remaining = end_time - asyncio.get_event_loop().time()
                await asyncio.sleep(min(4.5, max(0.1, remaining)))
        except asyncio.CancelledError:
            log.info("Typing simulation cancelled")
            return
        except Exception as exc:
            log.warning("Typing action error: %s", exc)
            await asyncio.sleep(1)

    log.info("Typing simulation finished")


async def mark_as_read(msg_id: int) -> None:
    """Send ReadHistoryRequest to mark messages as read (human behavior)."""
    if not _client or not _target_entity:
        return
    try:
        await _client(ReadHistoryRequest(
            peer=_target_entity,
            max_id=msg_id,
        ))
        log.info("ReadHistory sent (max_id=%d)", msg_id)
    except Exception as exc:
        log.warning("ReadHistoryRequest failed: %s", exc)


async def disconnect_userbot() -> None:
    """
    Disconnect the userbot client only. Does NOT terminate the process.
    The control bot stays alive and ready for a new /arm command.
    """
    log.info("Disconnecting userbot client...")
    if _client:
        try:
            if _client.is_connected():
                await _client.disconnect()
                log.info("Userbot client disconnected cleanly")
            else:
                log.info("Userbot was already disconnected")
        except Exception as exc:
            log.warning("Disconnect error (non-fatal): %s", exc)


async def reconnect_userbot() -> None:
    """
    Reconnect the userbot client if disconnected.
    Called by the scheduler at Phase 1 (T-120s) of each arm cycle.
    Event handlers persist across disconnects — no re-registration needed.
    """
    if not _client:
        raise RuntimeError("Client not initialized — run build_userbot() first")

    if _client.is_connected():
        log.info("Userbot already connected")
    else:
        log.info("Reconnecting userbot client...")
        await _client.connect()

    if not await _client.is_user_authorized():
        raise RuntimeError("Session lost authorization — re-run create_session.py")

    me = await _client.get_me()
    log.info("Userbot connection verified: %s (id=%s)", me.first_name, me.id)


def reset_for_next_arm() -> None:
    """
    Reset the double-response guard so a new arm cycle can fire.
    Called by the scheduler when starting a new arm task.
    """
    global _reply_fired
    _reply_fired = False
    log.info("Reply guard reset — ready for next arm cycle")


async def switch_target_chat(chat_id: str) -> str:
    """
    Switch the target chat to a new group at runtime.

    Resolves the new entity, re-registers the event handler on the new chat,
    and returns the chat title.

    Called from the control bot after group selection via inline keyboard.
    """
    global _target_entity

    if not _client:
        raise RuntimeError("Client not initialized — run build_userbot() first")

    # Ensure client is connected
    if not _client.is_connected():
        await _client.connect()

    # Resolve new entity
    try:
        try:
            new_entity = await _client.get_entity(int(chat_id))
        except ValueError:
            new_entity = await _client.get_entity(chat_id)
    except Exception as exc:
        log.error("Cannot resolve chat_id '%s': %s", chat_id, exc)
        raise

    title = getattr(new_entity, "title", str(new_entity.id))
    log.info("Switching target chat to: '%s' (id=%s)", title, new_entity.id)

    # Remove ALL existing NewMessage handlers, then re-register on new entity
    _client.remove_event_handler(_on_photo_message)

    _target_entity = new_entity

    _client.add_event_handler(
        _on_photo_message,
        events.NewMessage(
            chats=_target_entity,
            incoming=True,
            func=lambda e: e.photo,
        ),
    )
    log.info("Event handler re-registered on '%s'", title)

    # Update state
    state.target_chat_name = title
    return title


async def _on_photo_message(event: events.NewMessage.Event) -> None:
    """
    Hot-path handler for incoming photos — ZERO DELAY mode.

    Flow:
      1. Guard: skip if not monitoring or already replied
      2. Apply sender/caption filters
      3. Set double-response guard (atomic)
      4. ReadHistoryRequest (mark as read) — FIRST action
      5. Reply INSTANTLY — NO delay, NO sleep
      6. Record latency (actual network time only)
      7. Notify owner
      8. Disconnect userbot (control bot stays alive)
    """
    global _reply_fired

    # ── Guard: monitoring must be active ──────────────────────────────────
    if not state.monitoring_active:
        return
    if state.reply_sent or _reply_fired:
        return

    msg = event.message

    # ── Photo type check (belt-and-suspenders) ────────────────────────────
    if not isinstance(msg.media, MessageMediaPhoto):
        return

    # ── Sender whitelist ──────────────────────────────────────────────────
    if config.ALLOWED_SENDER_IDS and msg.sender_id not in config.ALLOWED_SENDER_IDS:
        return

    # ── Caption keyword filter ────────────────────────────────────────────
    if config.CAPTION_KEYWORD:
        if config.CAPTION_KEYWORD not in (msg.message or "").lower():
            return

    # ══════════════════════════════════════════════════════════════════════
    # EXECUTION — t0 starts NOW (event arrival)
    # ══════════════════════════════════════════════════════════════════════
    t0 = time.perf_counter()

    # ── SET DOUBLE-RESPONSE GUARD (atomic) ────────────────────────────────
    _reply_fired = True
    state.reply_sent = True
    state.monitoring_active = False

    log.info("⚡ Photo detected (msg_id=%d) — INSTANT reply sequence", msg.id)

    # ── Step 1: ReadHistoryRequest (mark as read) — FIRST action ──────────
    await mark_as_read(msg.id)

    # ── Step 2: Pick random reply variant ─────────────────────────────────
    reply_text = random.choice(REPLY_VARIANTS)

    # ── Step 3: Send the reply INSTANTLY — NO delay, NO sleep ─────────────
    try:
        await _client.send_message(
            entity=_target_entity,
            message=reply_text,
            reply_to=msg.id,
        )
    except Exception as exc:
        # Rollback guard on failure
        _reply_fired = False
        state.reply_sent = False
        state.monitoring_active = True
        log.error("❌ Reply FAILED (msg_id=%d): %s", msg.id, exc)
        if _notify_cb:
            try:
                await _notify_cb(f"❌ Reply FAILED: {exc}")
            except Exception:
                pass
        return

    # ── Step 4: Record total latency (event arrival → send complete) ─────
    total_latency_ms = (time.perf_counter() - t0) * 1_000
    now = datetime.now(tz=config.CAIRO_TZ)
    state.mark_sent(total_latency_ms, now, msg.id)

    log.info(
        "✅ Reply sent | '%s' | msg_id=%d | latency=%.0f ms | at=%s",
        reply_text, msg.id, total_latency_ms,
        now.strftime("%H:%M:%S.%f"),
    )

    # ── Step 5: Notify owner ──────────────────────────────────────────────
    if _notify_cb:
        try:
            await _notify_cb(
                f"✅ Reply sent!\n"
                f"⚡ Latency: {total_latency_ms:.0f} ms\n"
                f"🕐 At: {now.strftime('%H:%M:%S')} Cairo\n"
                f"💬 Text: {reply_text}\n"
                f"🔌 Disconnecting userbot (bot stays alive)..."
            )
        except Exception:
            pass

    # ── Step 6: Disconnect userbot (control bot stays alive) ──────────────
    log.info("Reply done — disconnecting userbot (service continues)")
    await disconnect_userbot()
