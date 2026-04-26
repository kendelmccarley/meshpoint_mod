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
from typing import Optional

from src.transmit.tx_service import HW_MODEL_PORTDUINO, TxService

logger = logging.getLogger(__name__)

DEFAULT_STARTUP_DELAY_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = 30 * 60


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

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Schedule the broadcast loop. No-op if already running."""
        if self.is_running:
            logger.debug("NodeInfoBroadcaster already running")
            return
        self._running = True
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

    async def _broadcast_once(self) -> None:
        try:
            result = await self._tx.send_nodeinfo(
                long_name=self._long_name,
                short_name=self._short_name,
                hw_model=self._hw_model,
            )
        except Exception:
            logger.exception("NodeInfo send raised")
            return

        if result.success:
            logger.info(
                "NodeInfo broadcast OK: id=%s airtime=%dms",
                result.packet_id, result.airtime_ms,
            )
        else:
            logger.warning(
                "NodeInfo broadcast skipped: %s", result.error or "unknown"
            )
