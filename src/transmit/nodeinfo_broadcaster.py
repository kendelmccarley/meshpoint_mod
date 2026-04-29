"""Periodic Meshtastic NodeInfo broadcaster.

Announces the Meshpoint's identity (node_id, long_name, short_name) on
the mesh so receiving Meshtastic clients can build a stable contact
entry. Without this, recipients have no friendly name to attach to
direct messages from the Meshpoint and DMs may show as 'Sent' in the
dashboard but never arrive.

Identity is captured at construction time. Changes to long_name /
short_name in the dashboard radio tab take effect on the next service
restart, matching the existing UX contract for ``transmit.node_id``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.transmit.tx_service import HW_MODEL_PORTDUINO, TxService

logger = logging.getLogger(__name__)

DEFAULT_STARTUP_DELAY_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 180 * 60

INTERVAL_DISABLED = 0
INTERVAL_MIN_MINUTES = 5
INTERVAL_MAX_MINUTES = 1440


def clamp_interval_minutes(value: int) -> int:
    """Clamp the interval to the supported range; log WARN if out of bounds.

    ``0`` is the documented disable sentinel and passes through unchanged.
    Negative values are also treated as disabled (with a WARN). Otherwise
    the value is clamped to ``5..1440`` since below 5 minutes is impolite
    on busy meshes and above 24 hours risks new clients in range not
    discovering the Meshpoint within a reasonable window.
    """
    if value == INTERVAL_DISABLED:
        return INTERVAL_DISABLED
    if value < 0:
        logger.warning(
            "transmit.nodeinfo.interval_minutes=%d is negative, "
            "treating as disabled (0).",
            value,
        )
        return INTERVAL_DISABLED
    if value < INTERVAL_MIN_MINUTES:
        logger.warning(
            "transmit.nodeinfo.interval_minutes=%d is below minimum %d, "
            "clamping. Below 5 minutes is impolite on busy meshes. "
            "Set to 0 to disable broadcasts entirely.",
            value, INTERVAL_MIN_MINUTES,
        )
        return INTERVAL_MIN_MINUTES
    if value > INTERVAL_MAX_MINUTES:
        logger.warning(
            "transmit.nodeinfo.interval_minutes=%d is above maximum %d, "
            "clamping. Above 24 hours risks new clients in range not "
            "discovering you.",
            value, INTERVAL_MAX_MINUTES,
        )
        return INTERVAL_MAX_MINUTES
    return value


class NodeInfoBroadcaster:
    """Schedules periodic NodeInfo broadcasts via :class:`TxService`."""

    def __init__(
        self,
        tx_service: TxService,
        long_name: str,
        short_name: str,
        *,
        startup_delay_seconds: int = DEFAULT_STARTUP_DELAY_SECONDS,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        hw_model: int = HW_MODEL_PORTDUINO,
    ):
        self._tx = tx_service
        self._long_name = long_name
        self._short_name = short_name
        self._startup_delay = startup_delay_seconds
        self._interval = interval_seconds
        self._hw_model = hw_model
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._started_at: Optional[datetime] = None
        self._last_sent_at: Optional[datetime] = None

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    @property
    def interval_seconds(self) -> int:
        return self._interval

    @property
    def startup_delay_seconds(self) -> int:
        return self._startup_delay

    @property
    def last_sent_at(self) -> Optional[datetime]:
        return self._last_sent_at

    @property
    def next_due_at(self) -> Optional[datetime]:
        """Wall-clock time of the next scheduled broadcast.

        Before the first broadcast, this is start time + startup delay.
        After the first broadcast, it's last_sent_at + interval.
        Returns ``None`` if the broadcaster hasn't been started yet.
        """
        if not self._running:
            return None
        if self._last_sent_at is not None:
            return self._last_sent_at + timedelta(seconds=self._interval)
        if self._started_at is not None:
            return self._started_at + timedelta(seconds=self._startup_delay)
        return None

    async def start(self) -> None:
        """Schedule the broadcast loop. No-op if already running."""
        if self.is_running:
            logger.debug("NodeInfoBroadcaster already running")
            return
        self._running = True
        self._started_at = datetime.now(timezone.utc)
        self._task = asyncio.create_task(
            self._loop(), name="nodeinfo-broadcaster"
        )
        logger.info(
            "NodeInfo broadcaster scheduled: first TX in %ds, "
            "interval %ds, long=%r short=%r",
            self._startup_delay, self._interval,
            self._long_name, self._short_name,
        )

    async def stop(self, timeout: float = 5.0) -> None:
        """Cancel the broadcast loop and wait for it to finish."""
        self._running = False
        task = self._task
        if task is None:
            return
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        finally:
            self._task = None

    async def _loop(self) -> None:
        try:
            await asyncio.sleep(self._startup_delay)
            while self._running:
                await self._broadcast_once()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.debug("NodeInfo broadcaster cancelled")
            raise
        except Exception:
            logger.exception("NodeInfo broadcaster loop crashed")

    async def _broadcast_once(self):
        return await self.broadcast_now()

    async def broadcast_now(self):
        """Send a single NodeInfo broadcast right now.

        Public entry point used by the "Send Now" button on the radio
        tab and by the periodic loop. Updates ``last_sent_at`` on
        success so the dashboard countdown re-anchors. Returns the
        underlying :class:`SendResult` so callers can surface errors;
        never raises.
        """
        try:
            result = await self._tx.send_nodeinfo(
                long_name=self._long_name,
                short_name=self._short_name,
                hw_model=self._hw_model,
            )
        except Exception as exc:
            logger.exception("NodeInfo send raised")
            from src.transmit.tx_service import SendResult
            return SendResult(
                success=False, protocol="meshtastic", error=str(exc),
            )

        if result.success:
            self._last_sent_at = datetime.now(timezone.utc)
            logger.info(
                "NodeInfo broadcast OK: id=%s airtime=%dms",
                result.packet_id, result.airtime_ms,
            )
        else:
            logger.warning(
                "NodeInfo broadcast skipped: %s", result.error or "unknown"
            )
        return result
