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
        "selected_group_id",
        "selected_group_name",
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

        # ── Selected group ────────────────────────────────────────────────────
        self.selected_group_id: str = ""
        self.selected_group_name: str = ""

        # ── Recovery flag ─────────────────────────────────────────────────────
        self.recovered_from_disk: bool = False

    # ── Public helpers ────────────────────────────────────────────────────────

    def arm(self, scheduled: datetime, group_id: str = "", group_name: str = "") -> None:
        """Set a new schedule (resets fire guard). Persists to disk."""
        self.scheduled_dt      = scheduled
        self.reply_sent        = False
        self.monitoring_active = False
        if group_id:
            self.selected_group_id   = group_id
            self.selected_group_name = group_name
        self._persist()

    def reset(self) -> None:
        """Full reset — call after /stop or after window timeout. Clears disk state."""
        self.scheduled_dt        = None
        self.monitoring_active   = False
        self.reply_sent          = False
        self.selected_group_id   = ""
        self.selected_group_name = ""
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
            group_id=self.selected_group_id,
            group_name=self.selected_group_name,
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _cancel_tasks(self) -> None:
        for task in (self._arm_task, self._stop_task):
            if task and not task.done():
                task.cancel()
        self._arm_task  = None
        self._stop_task = None

    # ── Status summary (for /status command) ─────────────────────────────────

    @staticmethod
    def _ampm_label(dt: datetime) -> str:
        """Return AM/PM label in Arabic."""
        return "AM (صباحاً)" if dt.hour < 12 else "PM (مساءً)"

    def status_text(self) -> str:
        lines = []

        # Recovery notice
        if self.recovered_from_disk:
            lines.append("🔄 State recovered from previous session")
            lines.append("")

        # Selected group
        if self.selected_group_name:
            lines.append(f"🎯 الجروب: {self.selected_group_name}")
        elif self.target_chat_name:
            lines.append(f"🎯 Target: {self.target_chat_name}")

        # Armed status
        if self.scheduled_dt:
            connect_dt = self.scheduled_dt - timedelta(seconds=120)
            typing_dt  = self.scheduled_dt - timedelta(seconds=90)
            snipe_dt   = self.scheduled_dt - timedelta(seconds=60)
            close_dt   = self.scheduled_dt + timedelta(seconds=180)
            ampm = self._ampm_label(self.scheduled_dt)
            lines.append("🟢 Armed")
            lines.append(
                f"🕐 Target: {self.scheduled_dt.strftime('%Y-%m-%d %I:%M:%S')} {ampm} Cairo"
            )
            lines.append(
                f"🚀 بدء التحضير: {connect_dt.strftime('%I:%M:%S %p')}"
            )
            lines.append(
                f"🏁 نهاية النافذة: {close_dt.strftime('%I:%M:%S %p')}"
            )

            # ── Current phase detection ───────────────────────────────────
            now = datetime.now(tz=config.CAIRO_TZ)

            if self.reply_sent:
                lines.append("")
                lines.append("✅ Reply already sent!")
            elif now < connect_dt:
                remaining = connect_dt - now
                mins, secs = divmod(int(remaining.total_seconds()), 60)
                hours, mins = divmod(mins, 60)
                if hours > 0:
                    lines.append(f"\n⏳ Phase 1 (Connect) starts in: {hours}h {mins}m {secs}s")
                else:
                    lines.append(f"\n⏳ Phase 1 (Connect) starts in: {mins}m {secs}s")
                lines.append("💤 Status: Waiting…")
            elif now < typing_dt:
                remaining = typing_dt - now
                secs = int(remaining.total_seconds())
                lines.append(f"\n🔌 Phase 1: CONNECT & PRE-LOAD")
                lines.append(f"⏳ Typing phase in: {secs}s")
            elif now < snipe_dt:
                remaining = snipe_dt - now
                secs = int(remaining.total_seconds())
                lines.append(f"\n⌨️ Phase 2: TYPING / PRESENCE")
                lines.append(f"⏳ Snipe mode in: {secs}s")
            elif now < self.scheduled_dt:
                remaining = self.scheduled_dt - now
                secs = int(remaining.total_seconds())
                lines.append(f"\n🎯 Phase 3: SILENT SNIPE ⚡")
                lines.append(f"⏳ Target in: {secs}s")
                lines.append("⚡ Waiting for photo…")
            elif now < close_dt:
                remaining = close_dt - now
                mins, secs = divmod(int(remaining.total_seconds()), 60)
                lines.append(f"\n🎯 Phase 3: SILENT SNIPE ⚡ (Grace)")
                lines.append(f"⏳ Grace remaining: {mins}m {secs}s")
                lines.append("⚡ Waiting for photo…")
            else:
                lines.append("\n⏱ Window expired")
        else:
            lines.append("🔴 Not armed")

        # Monitoring flag
        if self.monitoring_active:
            lines.append("📡 Monitoring: ✅ ACTIVE")
        else:
            if not self.reply_sent:
                lines.append("📡 Monitoring: ❌ Off")

        # Reply text
        lines.append(f"💬 Reply: 4 random variants")

        # Last reply info
        if self.reply_sent:
            if self.last_reply_latency_ms is not None:
                lines.append(f"⚡ Latency: {self.last_reply_latency_ms:.1f} ms")
            if self.last_reply_at is not None:
                sent_ampm = self._ampm_label(self.last_reply_at)
                lines.append(
                    f"🕰 Sent at: {self.last_reply_at.strftime('%I:%M:%S')} {sent_ampm} Cairo"
                )

        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────
state = BotState()
