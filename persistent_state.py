"""
persistent_state.py — Crash-safe persistent state for armed schedule.

Persists armed schedule and reply status to disk so the bot can recover
after a crash/restart.  Uses atomic write (temp file + os.replace) to
guarantee no partial writes.

File location: sessions/armed_state.json
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

import config

log = logging.getLogger(__name__)

_STATE_FILE = os.path.join("sessions", "armed_state.json")


def save_state(
    scheduled_dt: Optional[datetime],
    reply_text: str,
    reply_sent: bool,
    group_id: str = "",
    group_name: str = "",
) -> None:
    """
    Persist current armed state to disk atomically.

    If scheduled_dt is None (system stopped/reset), the state file is deleted.
    """
    if scheduled_dt is None:
        clear_state()
        return

    data = {
        "scheduled_dt": scheduled_dt.isoformat(),
        "reply_text": reply_text,
        "reply_sent": reply_sent,
        "group_id": group_id,
        "group_name": group_name,
        "saved_at": datetime.now(tz=config.CAIRO_TZ).isoformat(),
    }

    os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)

    try:
        # Atomic write: temp file → os.replace (no partial state on disk)
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(_STATE_FILE), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, _STATE_FILE)
        except BaseException:
            # Clean up temp file on any error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        log.debug("State persisted to %s", _STATE_FILE)
    except Exception as exc:
        log.warning("Failed to persist state: %s", exc)


def load_state() -> Optional[dict]:
    """
    Load persisted state from disk.

    Returns a dict with keys: scheduled_dt (str ISO), reply_text, reply_sent,
    saved_at.  Returns None if file is missing or corrupt.
    """
    if not os.path.exists(_STATE_FILE):
        return None

    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Validate required keys
        if "scheduled_dt" not in data or "reply_sent" not in data:
            log.warning("State file missing required keys, ignoring")
            return None
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Corrupt state file %s: %s — ignoring", _STATE_FILE, exc)
        return None


def clear_state() -> None:
    """Delete the persisted state file if it exists."""
    try:
        if os.path.exists(_STATE_FILE):
            os.remove(_STATE_FILE)
            log.debug("Cleared persisted state file")
    except OSError as exc:
        log.warning("Failed to clear state file: %s", exc)
