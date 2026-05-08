"""
state.py — Shared in-process runtime state.

Both the userbot and the control-bot import this module so they share the
SAME objects.  No database or file locking needed — everything lives in
memory for the lifetime of the process.

Persistence hooks: key mutations (arm, reset, mark_sent) automatically
persist state to disk via persistent_state module for crash recovery.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

import config
import persistent_state


class BotState:
    """Asyncio-safe container for all runtime state."""

    __slots__ = (
        "scheduled_dt",
        "monitoring_active",
        "reply_text",
        "reply_sent",
        "_arm_task",
        "_stop_task",
        "last_reply_latency_ms",
        "last_reply_at",
        "last_reply_msg_id",
        "target_chat_name",
        "recovered_from_disk",
    )

    def __init__(self) -> None:
        # ── Scheduling ────────────────────────────────────────────────────────
        self.scheduled_dt: Optional[datetime] = None

        # ── Activation window ─────────────────────────────────────────────────
        self.monitoring_active: bool = False

        # ── Reply text ────────────────────────────────────────────────────────
        self.reply_text: str = config.DEFAULT_REPLY_TEXT

        # ── Fire guard ────────────────────────────────────────────────────────
        self.reply_sent: bool = False

        # ── Internal handles ──────────────────────────────────────────────────
        self._arm_task: Optional[asyncio.Task] = None
        self._stop_task: Optional[asyncio.Task] = None

        # ── Latency tracking ──────────────────────────────────────────────────
        self.last_reply_latency_ms: Optional[float] = None
        self.last_reply_at: Optional[datetime] = None
        self.last_reply_msg_id: Optional[int] = None

        # ── Display info ──────────────────────────────────────────────────────
        self.target_chat_name: str = ""

        # ── Recovery flag ─────────────────────────────────────────────────────
        self.recovered_from_disk: bool = False

    # ── Public helpers ────────────────────────────────────────────────────────

    def arm(self, scheduled: datetime) -> None:
        """Set a new schedule (resets fire guard). Persists to disk."""
        self.scheduled_dt      = scheduled
        self.reply_sent        = False
        self.monitoring_active = False
        self._persist()

    def reset(self) -> None:
        """Full reset — call after /stop or after window timeout. Clears disk state."""
        self.scheduled_dt      = None
        self.monitoring_active = False
        self.reply_sent        = False
        self._cancel_tasks()
        persistent_state.clear_state()

    def activate_monitoring(self) -> None:
        self.monitoring_active = True

    def deactivate_monitoring(self) -> None:
        self.monitoring_active = False

    def mark_sent(self, latency_ms: float, sent_at: datetime, msg_id: int = 0) -> None:
        """Record a successful reply and stop monitoring. Persists to disk."""
        self.reply_sent            = True
        self.monitoring_active     = False
        self.last_reply_latency_ms = latency_ms
        self.last_reply_at         = sent_at
        self.last_reply_msg_id     = msg_id
        self._persist()

    def cancel_arm_tasks(self) -> None:
        """Cancel any pending arm/stop asyncio tasks."""
        self._cancel_tasks()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Write current state to disk for crash recovery."""
        persistent_state.save_state(
            scheduled_dt=self.scheduled_dt,
            reply_text=self.reply_text,
            reply_sent=self.reply_sent,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _cancel_tasks(self) -> None:
        for task in (self._arm_task, self._stop_task):
            if task and not task.done():
                task.cancel()
        self._arm_task  = None
        self._stop_task = None

    # ── Status summary (for /status command) ─────────────────────────────────

    def status_text(self) -> str:
        lines = []

        # Recovery notice
        if self.recovered_from_disk:
            lines.append("🔄 State recovered from previous session")
            lines.append("")

        # Armed status
        if self.scheduled_dt:
            open_dt  = self.scheduled_dt - timedelta(minutes=config.PRE_WINDOW_MINUTES)
            close_dt = self.scheduled_dt + timedelta(minutes=config.POST_WINDOW_MINUTES)
            lines.append("🟢 Armed")
            lines.append(
                f"🕐 Scheduled: {self.scheduled_dt.strftime('%Y-%m-%d %H:%M')} Cairo"
            )
            lines.append(
                f"📡 Window: {open_dt.strftime('%H:%M')} – {close_dt.strftime('%H:%M')}"
            )
        else:
            lines.append("🔴 Not armed")

        # Monitoring flag
        if self.monitoring_active:
            lines.append("📡 Monitoring: ✅ ACTIVE")
        else:
            lines.append("📡 Monitoring: ❌ Off")

        # Target chat
        if self.target_chat_name:
            lines.append(f"🎯 Target: {self.target_chat_name}")

        # Reply text
        lines.append(f"💬 Reply text: {self.reply_text}")

        # Last reply info
        if self.reply_sent:
            lines.append("✅ Reply already sent this session")
            if self.last_reply_latency_ms is not None:
                lines.append(f"⚡ Latency: {self.last_reply_latency_ms:.1f} ms")
            if self.last_reply_at is not None:
                lines.append(
                    f"🕰 Sent at: {self.last_reply_at.strftime('%H:%M:%S')} Cairo"
                )

        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────
state = BotState()
