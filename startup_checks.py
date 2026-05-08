"""
startup_checks.py — Pre-flight verification at boot.

Ensures all Telegram connections, authorizations, and chat access
are valid before entering the main event loop.
"""

import logging

from telegram import Bot

from telethon import TelegramClient

import config

log = logging.getLogger(__name__)


async def check_bot_connection(bot: Bot) -> None:
    """Verify the control bot is connected and authorized."""
    me = await bot.get_me()
    log.info(
        "✅ Control bot authorized: @%s (id=%s)",
        me.username or me.first_name,
        me.id,
    )


async def check_owner_access(bot: Bot) -> None:
    """Verify the bot can reach the owner (OWNER_ID)."""
    try:
        chat = await bot.get_chat(config.OWNER_ID)
        name = chat.first_name or chat.username or str(chat.id)
        log.info("✅ Owner reachable: %s (id=%s)", name, config.OWNER_ID)
    except Exception as exc:
        log.error(
            "❌ Cannot reach OWNER_ID %s: %s — "
            "make sure you've started a conversation with the bot",
            config.OWNER_ID,
            exc,
        )
        raise


async def check_target_chat(userbot: TelegramClient) -> str:
    """
    Verify the userbot can access TARGET_CHAT.

    Returns the chat title for use in status displays.
    """
    try:
        raw = config.TARGET_CHAT
        try:
            entity = await userbot.get_entity(int(raw))
        except ValueError:
            entity = await userbot.get_entity(raw)
        title = getattr(entity, "title", None) or str(entity.id)
        log.info("✅ Target chat accessible: '%s' (id=%s)", title, entity.id)
        return title
    except Exception as exc:
        log.error(
            "❌ Cannot access TARGET_CHAT '%s': %s",
            config.TARGET_CHAT,
            exc,
        )
        raise


async def check_session_validity(userbot: TelegramClient) -> None:
    """Verify the userbot session is authorized."""
    if not await userbot.is_user_authorized():
        log.error("❌ Userbot session is NOT authorized — re-authenticate")
        raise RuntimeError("Userbot session not authorized")
    me = await userbot.get_me()
    log.info(
        "✅ Userbot session valid: %s (id=%s)", me.first_name, me.id
    )


async def run_all_checks(bot: Bot, userbot: TelegramClient) -> str:
    """
    Run all pre-flight checks.  Raises on fatal failure.

    Returns the target chat title.
    """
    log.info("─── Running startup checks ───")
    await check_bot_connection(bot)
    await check_owner_access(bot)
    await check_session_validity(userbot)
    target_title = await check_target_chat(userbot)
    log.info("─── All startup checks passed ───")
    return target_title
