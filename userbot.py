"""
userbot.py — Telethon personal-account userbot.

Supports two session modes:
  1. TELETHON_SESSION env var (StringSession) — preferred for Docker/EasyPanel
  2. File-based session at sessions/userbot.session — fallback for local dev
"""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto

import config
from state import state

log = logging.getLogger(__name__)

_client: TelegramClient | None = None
_target_entity = None
_notify_cb = None


def get_client() -> TelegramClient:
    return _client


async def build_userbot(notify_cb=None) -> TelegramClient:
    global _client, _target_entity, _notify_cb
    _notify_cb = notify_cb

    session_string = os.environ.get("TELETHON_SESSION", "").strip()

    if session_string:
        # StringSession from env var (Docker/EasyPanel mode)
        log.info("Using StringSession from TELETHON_SESSION env var")
        _client = TelegramClient(
            StringSession(session_string),
            config.API_ID,
            config.API_HASH,
            connection_retries=-1,
            auto_reconnect=True,
            flood_sleep_threshold=300,
        )
        await _client.connect()
        if not await _client.is_user_authorized():
            log.error("StringSession is NOT authorized. Re-run create_session.py")
            raise RuntimeError("StringSession expired — re-run create_session.py")
    else:
        # File-based session (local dev mode)
        log.info("Using file-based session: %s", config.USERBOT_SESSION)
        _client = TelegramClient(
            config.USERBOT_SESSION,
            config.API_ID,
            config.API_HASH,
            connection_retries=-1,
            auto_reconnect=True,
            flood_sleep_threshold=300,
        )
        try:
            await _client.start(phone=config.PHONE)
        except FloodWaitError as e:
            log.warning("FloodWait %ds — sleeping…", e.seconds)
            await asyncio.sleep(e.seconds + 5)
            await _client.start(phone=config.PHONE)

    me = await _client.get_me()
    log.info("Userbot connected as %s (id=%s)", me.first_name, me.id)

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

    _client.add_event_handler(
        _on_new_message,
        events.NewMessage(chats=_target_entity),
    )
    log.info("Event handler registered on target chat.")
    return _client


async def _on_new_message(event: events.NewMessage.Event) -> None:
    """Hot-path handler. Minimal branching, no logging until reply."""
    if not state.monitoring_active:
        return
    if state.reply_sent:
        return

    msg = event.message
    if not isinstance(msg.media, MessageMediaPhoto):
        return
    if config.ALLOWED_SENDER_IDS and msg.sender_id not in config.ALLOWED_SENDER_IDS:
        return
    if config.CAPTION_KEYWORD:
        if config.CAPTION_KEYWORD not in (msg.message or "").lower():
            return

    state.reply_sent = True
    state.monitoring_active = False
    t0 = time.perf_counter()

    try:
        await _client.send_message(
            entity=_target_entity,
            message=state.reply_text,
            reply_to=msg.id,
        )
    except Exception as exc:
        state.reply_sent = False
        state.monitoring_active = True
        log.error("Reply FAILED (msg_id=%d): %s", msg.id, exc)
        if _notify_cb:
            try: await _notify_cb(f"❌ Reply FAILED: {exc}")
            except Exception: pass
        return

    elapsed_ms = (time.perf_counter() - t0) * 1_000
    now = datetime.now(tz=config.CAIRO_TZ)
    state.mark_sent(elapsed_ms, now, msg.id)
    log.info("✅ Reply sent | msg_id=%d | latency=%.1f ms | at=%s",
             msg.id, elapsed_ms, now.strftime("%H:%M:%S.%f"))

    if _notify_cb:
        try:
            await _notify_cb(
                f"✅ Reply sent!\n⚡ Latency: {elapsed_ms:.1f} ms\n"
                f"🕐 At: {now.strftime('%H:%M:%S')} Cairo\n💬 Text: {state.reply_text}")
        except Exception: pass
