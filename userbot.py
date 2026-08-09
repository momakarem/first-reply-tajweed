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
from telethon.utils import get_peer_id

import config
from state import state

log = logging.getLogger(__name__)

# ── Module-level references ───────────────────────────────────────────────────
_client: TelegramClient | None = None
_target_entity = None
_target_chat_id: int | None = None  # Normalized chat ID (with -100 prefix for channels)
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

    Registers a SINGLE persistent NewMessage handler (no chats filter).
    The handler filters internally by comparing event.chat_id against
    _target_chat_id, which is updated by switch_target_chat().

    Args:
        notify_cb: async callable to send status notifications to the owner.
        code_callback: async callable that returns the verification code string.
                       If None, Telethon falls back to input() (terminal).
        password_callback: async callable that returns the 2FA password string.
                           If None, Telethon falls back to input() (terminal).
    """
    global _client, _target_entity, _target_chat_id, _notify_cb
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

        # Connect first and check if session is still valid.
        # Only trigger the full login flow (start) if not authorized.
        # This avoids sending a new verification code every restart.
        await _client.connect()

        if await _client.is_user_authorized():
            log.info("Existing session is valid — skipping login.")
        else:
            log.info("Session not authorized — starting login flow…")
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

    # Resolve default target chat entity
    try:
        raw = config.TARGET_CHAT
        try:
            _target_entity = await _client.get_entity(int(raw))
        except ValueError:
            _target_entity = await _client.get_entity(raw)

        # Compute normalized chat ID (with -100 prefix for channels)
        _target_chat_id = get_peer_id(_target_entity)
        title = getattr(_target_entity, "title", str(_target_entity.id))
        log.info(
            "Target chat: '%s' (entity.id=%s, chat_id=%s)",
            title, _target_entity.id, _target_chat_id,
        )
    except Exception as exc:
        log.error("Cannot resolve TARGET_CHAT '%s': %s", config.TARGET_CHAT, exc)
        raise

    # ── Single persistent event handler (NO chats filter) ─────────────────
    # Filtering is done INSIDE _on_photo_message by comparing
    # event.chat_id against _target_chat_id. This avoids issues with
    # handler re-registration during group switching and disconnect/reconnect.
    _client.add_event_handler(
        _on_photo_message,
        events.NewMessage(incoming=True),
    )
    log.info(
        "Persistent event handler registered (incoming, internal filtering). "
        "target_chat_id=%s",
        _target_chat_id,
    )
    return _client


async def send_typing(duration_seconds: float) -> None:
    """
    Send continuous typing action for the specified duration.
    Used by the scheduler during the preparation phase.
    """
    if not _client or not _target_entity:
        return

    # Resolve InputPeer once before the loop (avoids repeated lookups
    # and handles the case where _target_entity changed via switch).
    try:
        target_peer = await _client.get_input_entity(_target_entity)
    except Exception as exc:
        log.warning("Cannot resolve InputPeer for typing, using entity directly: %s", exc)
        target_peer = _target_entity

    end_time = asyncio.get_event_loop().time() + duration_seconds
    log.info("Typing simulation started for %.0f seconds", duration_seconds)

    while asyncio.get_event_loop().time() < end_time:
        try:
            async with _client.action(target_peer, "typing"):
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
        # Use get_input_entity to get the correct InputPeer type.
        # This prevents the "Invalid Peer" error that occurs when
        # _target_entity is a full Channel object after a group switch.
        input_peer = await _client.get_input_entity(_target_entity)
        await _client(ReadHistoryRequest(
            peer=input_peer,
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

    Updates _target_entity and _target_chat_id. Does NOT re-register
    the event handler — the persistent handler filters internally by
    comparing event.chat_id against _target_chat_id.

    Called from the control bot after group selection via inline keyboard.
    """
    global _target_entity, _target_chat_id

    if not _client:
        raise RuntimeError("Client not initialized — run build_userbot() first")

    # Ensure client is connected
    if not _client.is_connected():
        log.info("Client disconnected — reconnecting for group switch...")
        await _client.connect()

    # Verify authorization after reconnect
    if not await _client.is_user_authorized():
        raise RuntimeError("Session lost authorization — re-run create_session.py")

    # Resolve new entity
    try:
        try:
            new_entity = await _client.get_entity(int(chat_id))
        except ValueError:
            new_entity = await _client.get_entity(chat_id)
    except Exception as exc:
        log.error("Cannot resolve chat_id '%s': %s", chat_id, exc)
        raise

    # Compute normalized chat ID (with -100 prefix for channels)
    new_chat_id = get_peer_id(new_entity)
    title = getattr(new_entity, "title", str(new_entity.id))

    old_chat_id = _target_chat_id
    _target_entity = new_entity
    _target_chat_id = new_chat_id

    log.info(
        "Target chat switched: '%s' (entity.id=%s, chat_id=%s, prev_chat_id=%s)",
        title, new_entity.id, _target_chat_id, old_chat_id,
    )

    # Update state
    state.target_chat_name = title
    return title


async def _on_photo_message(event: events.NewMessage.Event) -> None:
    """
    Persistent handler for ALL incoming messages — ZERO DELAY mode.

    Filters internally by chat_id, photo type, sender, and caption.
    This handler is registered ONCE at startup without a chats filter,
    so it survives disconnect/reconnect and group switching.

    Flow:
      1. Guard: skip if not monitoring or already replied
      2. Chat ID filter: skip if not from the target group
      3. Photo type check
      4. Apply sender/caption filters
      5. Set double-response guard (atomic)
      6. ReadHistoryRequest (mark as read) — FIRST action
      7. Reply INSTANTLY — NO delay, NO sleep
      8. Record latency (actual network time only)
      9. Notify owner
     10. Disconnect userbot (control bot stays alive)
    """
    global _reply_fired

    # ── Guard: monitoring must be active ──────────────────────────────────
    if not state.monitoring_active:
        return
    if state.reply_sent or _reply_fired:
        return

    # ── Chat ID filter (internal, replaces Telethon chats= filter) ────────
    if _target_chat_id is None:
        return

    event_chat_id = event.chat_id
    if event_chat_id != _target_chat_id:
        # Log only when monitoring is active — helps diagnose wrong-group issues
        log.debug(
            "MESSAGE_IGNORED | reason=wrong_chat | event_chat_id=%s | target_chat_id=%s | msg_id=%s",
            event_chat_id, _target_chat_id, event.message.id,
        )
        return

    msg = event.message

    # ── Photo type check (belt-and-suspenders) ────────────────────────────
    if not isinstance(msg.media, MessageMediaPhoto):
        log.debug(
            "MESSAGE_IGNORED | reason=not_photo | chat_id=%s | msg_id=%s | has_media=%s",
            event_chat_id, msg.id, type(msg.media).__name__ if msg.media else "None",
        )
        return

    # ── Sender whitelist ──────────────────────────────────────────────────
    if config.ALLOWED_SENDER_IDS and msg.sender_id not in config.ALLOWED_SENDER_IDS:
        log.debug(
            "MESSAGE_IGNORED | reason=sender_not_allowed | chat_id=%s | msg_id=%s | sender_id=%s",
            event_chat_id, msg.id, msg.sender_id,
        )
        return

    # ── Caption keyword filter ────────────────────────────────────────────
    if config.CAPTION_KEYWORD:
        if config.CAPTION_KEYWORD not in (msg.message or "").lower():
            log.debug(
                "MESSAGE_IGNORED | reason=caption_mismatch | chat_id=%s | msg_id=%s",
                event_chat_id, msg.id,
            )
            return

    # ── PHOTO MATCH — all filters passed ──────────────────────────────────
    log.info(
        "PHOTO_MATCH | chat_id=%s | msg_id=%s | sender_id=%s",
        event_chat_id, msg.id, msg.sender_id,
    )

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
        "✅ REPLY_SENT | '%s' | msg_id=%d | latency=%.0f ms | at=%s",
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
