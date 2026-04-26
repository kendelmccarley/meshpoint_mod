"""Tests for NodeInfoBroadcaster lifecycle and resilience."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from src.transmit.nodeinfo_broadcaster import NodeInfoBroadcaster
from src.transmit.tx_service import SendResult


class _FakeTxService:
    """TxService stub recording calls to ``send_nodeinfo``."""

    def __init__(self, *, results=None, raises=None):
        self.calls: list[dict] = []
        self._results = list(results or [])
        self._raises = list(raises or [])
        self.send_nodeinfo = AsyncMock(side_effect=self._dispatch)

    async def _dispatch(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            exc = self._raises.pop(0)
            if exc is not None:
                raise exc
        if self._results:
            return self._results.pop(0)
        return SendResult(
            success=True, packet_id="00000001",
            protocol="meshtastic", airtime_ms=10,
        )


def _ok() -> SendResult:
    return SendResult(
        success=True, packet_id="abc", protocol="meshtastic", airtime_ms=12
    )


def _fail(error: str) -> SendResult:
    return SendResult(success=False, protocol="meshtastic", error=error)


class TestNodeInfoBroadcasterLifecycle(unittest.IsolatedAsyncioTestCase):

    async def test_start_creates_task_and_is_running(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10_000,
            interval_seconds=10_000,
        )
        await b.start()
        self.assertTrue(b.is_running)
        await b.stop()
        self.assertFalse(b.is_running)

    async def test_double_start_is_idempotent(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=10_000,
            interval_seconds=10_000,
        )
        await b.start()
        first_task = b._task
        await b.start()
        self.assertIs(b._task, first_task)
        await b.stop()

    async def test_stop_without_start_is_safe(self):
        tx = _FakeTxService()
        b = NodeInfoBroadcaster(tx, "Long", "SHRT")
        await b.stop()
        self.assertFalse(b.is_running)

    async def test_startup_delay_is_honored(self):
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(len(tx.calls), 1)

    async def test_interval_runs_multiple_broadcasts(self):
        tx = _FakeTxService(results=[_ok(), _ok(), _ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=0,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertGreaterEqual(len(tx.calls), 2)

    async def test_loop_survives_send_exception(self):
        tx = _FakeTxService(
            results=[_ok(), _ok()],
            raises=[RuntimeError("boom"), None, None],
        )
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=0,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertGreaterEqual(len(tx.calls), 2)

    async def test_loop_survives_failed_send_result(self):
        tx = _FakeTxService(
            results=[_fail("Duty cycle limit reached"), _ok()]
        )
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=0,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertGreaterEqual(len(tx.calls), 2)

    async def test_passes_long_and_short_name(self):
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "MyMeshpoint", "MMP1",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(tx.calls[0]["long_name"], "MyMeshpoint")
        self.assertEqual(tx.calls[0]["short_name"], "MMP1")

    async def test_default_hw_model_is_portduino(self):
        """v0.6.7 shipped PRIVATE_HW which renders as 'Private' on community maps."""
        from src.transmit.tx_service import HW_MODEL_PORTDUINO
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(tx.calls[0]["hw_model"], HW_MODEL_PORTDUINO)
        self.assertEqual(tx.calls[0]["hw_model"], 37)

    async def test_hw_model_override_respected(self):
        from src.transmit.tx_service import HW_MODEL_PRIVATE_HW
        tx = _FakeTxService(results=[_ok()])
        b = NodeInfoBroadcaster(
            tx, "Long", "SHRT",
            startup_delay_seconds=0,
            interval_seconds=10_000,
            hw_model=HW_MODEL_PRIVATE_HW,
        )
        await b.start()
        await asyncio.sleep(0.05)
        await b.stop()
        self.assertEqual(tx.calls[0]["hw_model"], HW_MODEL_PRIVATE_HW)


if __name__ == "__main__":
    unittest.main()
