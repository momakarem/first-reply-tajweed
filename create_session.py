"""
create_session.py — Interactive Telethon session creator.

Run this LOCALLY (not in Docker) to authenticate your Telegram account
and create the session file. Then upload sessions/userbot.session to
your EasyPanel volume.

Usage:
    python create_session.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
PHONE = os.environ.get("PHONE", "")
SESSION_PATH = os.environ.get("USERBOT_SESSION", "sessions/userbot")

if not all([API_ID, API_HASH, PHONE]):
    print("ERROR: Set API_ID, API_HASH, PHONE in .env first")
    sys.exit(1)


async def main():
    from telethon import TelegramClient

    os.makedirs(os.path.dirname(SESSION_PATH) or ".", exist_ok=True)

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start(phone=PHONE)

    me = await client.get_me()
    print(f"\n✅ Authenticated as: {me.first_name} (id={me.id})")
    print(f"📁 Session saved to: {SESSION_PATH}.session")
    print(f"\nUpload this file to your EasyPanel volume at /app/sessions/")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
