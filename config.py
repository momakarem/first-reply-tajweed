"""
config.py — Central configuration loader.

Reads all settings from environment variables (populated via .env).
Validates required values at import time so the process fails fast
if anything is missing.

Security: sensitive values are never exposed via repr/str.
"""

import logging
import os
import stat
import sys
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── Timezone ─────────────────────────────────────────────────────────────────
CAIRO_TZ = ZoneInfo("Africa/Cairo")

# ── Userbot credentials (Telethon personal account) ──────────────────────────
try:
    API_ID: int   = int(os.environ["API_ID"])
    API_HASH: str = os.environ["API_HASH"]
    PHONE: str    = os.environ["PHONE"]
except KeyError as exc:
    sys.exit(f"FATAL: Missing required env var: {exc}")

# ── Control Bot ──────────────────────────────────────────────────────────────
try:
    BOT_TOKEN: str = os.environ["BOT_TOKEN"]
    OWNER_ID: int  = int(os.environ["OWNER_ID"])
except KeyError as exc:
    sys.exit(f"FATAL: Missing required env var: {exc}")

# ── Target groups (loaded dynamically from .env) ─────────────────────────────
# Supports up to 10 groups: GROUP_1_NAME/GROUP_1_ID … GROUP_10_NAME/GROUP_10_ID
GROUPS: list[dict] = []
for _i in range(1, 11):
    _name = os.getenv(f"GROUP_{_i}_NAME", "").strip()
    _gid  = os.getenv(f"GROUP_{_i}_ID", "").strip()
    if _name and _gid:
        GROUPS.append({"name": _name, "id": _gid})

if not GROUPS:
    # Fallback: try legacy TARGET_CHAT env var
    _legacy = os.getenv("TARGET_CHAT", "").strip()
    if _legacy:
        GROUPS.append({"name": "Default Group", "id": _legacy})
    else:
        sys.exit("FATAL: No groups configured. Set GROUP_1_NAME/GROUP_1_ID in .env")

# Default target (first group) — used as fallback
TARGET_CHAT: str = GROUPS[0]["id"]

# ── Default reply text ────────────────────────────────────────────────────────
DEFAULT_REPLY_TEXT: str = os.getenv("DEFAULT_REPLY_TEXT", "مروة محروس 17")

# ── Timing window (minutes) ───────────────────────────────────────────────────
# NOTE: Stealth mode uses seconds internally (120s pre, 180s post).
# These values are kept for status display & crash recovery compatibility.
PRE_WINDOW_MINUTES: int  = int(os.getenv("PRE_WINDOW_MINUTES", "2"))
POST_WINDOW_MINUTES: int = int(os.getenv("POST_WINDOW_MINUTES", "3"))

# ── Session files ─────────────────────────────────────────────────────────────
USERBOT_SESSION: str = os.getenv("USERBOT_SESSION", "sessions/userbot")

# ── Anti-spam cooldown (seconds) ──────────────────────────────────────────────
ANTI_SPAM_COOLDOWN_SEC: float = float(os.getenv("ANTI_SPAM_COOLDOWN_SEC", "2"))

# ── Persistent state file path ────────────────────────────────────────────────
STATE_FILE: str = os.getenv("STATE_FILE", "sessions/armed_state.json")

# ── Optional sender whitelist ─────────────────────────────────────────────────
# Comma-separated Telegram user-ids.  Leave blank to allow all senders.
ALLOWED_SENDER_IDS: list[int] = [
    int(x.strip())
    for x in os.getenv("ALLOWED_SENDER_IDS", "").split(",")
    if x.strip().isdigit()
]

# ── Optional caption keyword filter ──────────────────────────────────────────
# Photo caption must contain this word (case-insensitive).  Leave blank to
# match ANY photo regardless of caption.
CAPTION_KEYWORD: str = os.getenv("CAPTION_KEYWORD", "").strip().lower()

# ── Sensitive values — never log these ────────────────────────────────────────
_SENSITIVE_VALUES = frozenset(filter(None, [API_HASH, BOT_TOKEN]))

# ── Session directory permission check (Linux/macOS only) ─────────────────────
def _check_session_dir_permissions() -> None:
    """Warn if sessions/ directory is world-readable (Linux/macOS only)."""
    if sys.platform == "win32":
        return  # chmod not applicable on Windows
    session_dir = os.path.dirname(USERBOT_SESSION)
    if not session_dir or not os.path.isdir(session_dir):
        return
    try:
        mode = os.stat(session_dir).st_mode
        if mode & stat.S_IROTH:
            log.warning(
                "⚠️  sessions/ directory is world-readable (mode %s). "
                "Consider: chmod 700 %s",
                oct(mode), session_dir,
            )
    except OSError:
        pass

_check_session_dir_permissions()
