"""
create_session.py — Generate a Telethon StringSession.

Run LOCALLY, then paste the output as TELETHON_SESSION env var in EasyPanel.

Usage: python create_session.py
"""
import asyncio, os, sys
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
PHONE = os.environ.get("PHONE", "")

if not all([API_ID, API_HASH, PHONE]):
    print("ERROR: Set API_ID, API_HASH, PHONE in .env first"); sys.exit(1)

async def main():
    print("Creating Telethon StringSession...\n")
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.start(phone=PHONE)
    me = await client.get_me()
    s = client.session.save()
    print(f"\nDONE! Authenticated as: {me.first_name} (id={me.id})\n")
    print("Copy this string and paste as TELETHON_SESSION in EasyPanel:\n")
    print("-" * 60)
    print(s)
    print("-" * 60)
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
