"""Unified message transmission service for Meshtastic and MeshCore.

Routes outbound messages to the appropriate TX path: native SX1261
for Meshtastic, USB/TCP companion for MeshCore.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Optional

from src.models.packet import Protocol
from src.transmit.duty_cycle import DutyCycleTracker

logger = logging.getLogger(__name__)

BROADCAST_ADDR_MT = 0xFFFFFFFF
BROADCAST_ADDR_MC = 0xFFFF


@dataclass
class SendResult:
    """Outcome of a transmission attempt."""

    success: bool
    packet_id: str = ""
    protocol: str = ""
    timestamp: float = 0.0
    error: str = ""
    airtime_ms: int = 0


class TxService:
    """Orchestrates message sending across Meshtastic and MeshCore."""

    def __init__(
        self,
        wrapper=None,
        crypto=None,
        channel_plan=None,
        transmit_config=None,
        meshcore_tx=None,
        duty_tracker: Optional[DutyCycleTracker] = None,
    ):
        self._wrapper = wrapper
        self._crypto = crypto
        self._channel_plan = channel_plan
        self._config = transmit_config
        self._meshcore_tx = meshcore_tx
        self._duty = duty_tracker
        self._builder = None
        self._packet_counter = random.randint(1, 0xFFFF)
        self._source_node_id = self._resolve_node_id()

    @property
    def meshtastic_enabled(self) -> bool:
        return (
            self._config is not None
            and self._config.enabled
            and self._wrapper is not None
        )

    @property
    def meshcore_enabled(self) -> bool:
        return self._meshcore_tx is not None and self._meshcore_tx.connected

    @property
    def source_node_id(self) -> int:
        return self._source_node_id

    async def send_text(
        self,
        text: str,
        destination: int | str = 0,
        protocol: str = "meshtastic",
        channel: int = 0,
        want_ack: bool = False,
    ) -> SendResult:
        """Send a text message over the specified protocol."""
        if protocol.lower() in ("meshtastic", "mt"):
            return await self._send_meshtastic(
                text, destination, channel, want_ack
            )
        elif protocol.lower() in ("meshcore", "mc"):
            return await self._send_meshcore(text, destination, channel)
        else:
            return SendResult(
                success=False, error=f"Unknown protocol: {protocol}"
            )

    async def _send_meshtastic(
        self,
        text: str,
        destination: int | str,
        channel: int,
        want_ack: bool,
    ) -> SendResult:
        """Build and transmit a Meshtastic packet via the SX1261."""
        if not self.meshtastic_enabled:
            return SendResult(
                success=False,
                protocol="meshtastic",
                error="Meshtastic TX not available",
            )

        builder = self._get_builder()
        if builder is None:
            return SendResult(
                success=False,
                protocol="meshtastic",
                error="Packet builder unavailable",
            )

        dest_int = self._resolve_destination(destination, Protocol.MESHTASTIC)
        packet_id = self._next_packet_id()
        channel_hash = self._compute_channel_hash(channel)

        packet_bytes = builder.build_text_message(
            text=text,
            dest=dest_int,
            source_id=self._source_node_id,
            packet_id=packet_id,
            channel_hash=channel_hash,
            hop_limit=3,
            hop_start=3,
            want_ack=want_ack,
        )
        if packet_bytes is None:
            return SendResult(
                success=False,
                protocol="meshtastic",
                packet_id=f"{packet_id:08x}",
                error="Packet build failed",
            )

        tx_pkt = self._build_hal_packet(packet_bytes)
        airtime_ms = await self._get_airtime(tx_pkt)

        if self._duty and not self._duty.check_budget(airtime_ms):
            return SendResult(
                success=False,
                protocol="meshtastic",
                packet_id=f"{packet_id:08x}",
                error="Duty cycle limit reached",
                airtime_ms=airtime_ms,
            )

        result_code = await asyncio.to_thread(self._wrapper.send, tx_pkt)

        if result_code == 0:
            if self._duty:
                self._duty.record_tx(airtime_ms)
            return SendResult(
                success=True,
                protocol="meshtastic",
                packet_id=f"{packet_id:08x}",
                timestamp=time.time(),
                airtime_ms=airtime_ms,
            )
        return SendResult(
            success=False,
            protocol="meshtastic",
            packet_id=f"{packet_id:08x}",
            error=f"lgw_send returned {result_code}",
        )

    async def _send_meshcore(
        self, text: str, destination: int | str, channel: int
    ) -> SendResult:
        """Send a message through the MeshCore companion."""
        if not self.meshcore_enabled:
            return SendResult(
                success=False,
                protocol="meshcore",
                error="MeshCore companion not connected",
            )

        is_broadcast = (
            destination == 0
            or destination == BROADCAST_ADDR_MC
            or str(destination).lower() in ("broadcast", "ffff", "0")
        )

        if is_broadcast:
            mc_result = await self._meshcore_tx.send_channel_message(
                channel, text
            )
        else:
            mc_result = await self._meshcore_tx.send_direct_message(
                destination, text
            )

        return SendResult(
            success=mc_result.success,
            protocol="meshcore",
            packet_id=mc_result.event_type,
            timestamp=time.time(),
            error=mc_result.error,
        )

    def _get_builder(self):
        """Lazy-load the Meshtastic packet builder."""
        if self._builder is not None:
            return self._builder
        try:
            from src.transmit.meshtastic_builder import (
                MeshtasticPacketBuilder,
            )
            self._builder = MeshtasticPacketBuilder(self._crypto)
            return self._builder
        except Exception:
            logger.exception("Failed to load MeshtasticPacketBuilder")
            return None

    def _build_hal_packet(self, packet_bytes: bytes):
        """Populate a LgwPktTxS struct from raw packet bytes."""
        from src.hal.sx1302_types import LgwPktTxS
        from src.hal.sx1302_wrapper import (
            BW_KHZ_TO_HAL,
            BW_250KHZ,
            MOD_LORA,
            TX_MODE_IMMEDIATE,
        )

        plan = self._channel_plan
        tx_pkt = LgwPktTxS()
        tx_pkt.freq_hz = int(plan.tx_freq_hz or plan.radio_0_freq_hz)
        tx_pkt.tx_mode = TX_MODE_IMMEDIATE
        tx_pkt.count_us = 0
        tx_pkt.rf_chain = 0
        tx_pkt.rf_power = self._config.tx_power_dbm
        tx_pkt.modulation = MOD_LORA
        tx_pkt.freq_offset = 0
        tx_pkt.bandwidth = BW_KHZ_TO_HAL.get(
            int(plan.bandwidth_khz), BW_250KHZ
        )
        tx_pkt.datarate = plan.spreading_factor
        tx_pkt.coderate = self._resolve_coderate(plan.coding_rate)
        tx_pkt.invert_pol = False
        tx_pkt.f_dev = 0
        tx_pkt.preamble = 16
        tx_pkt.no_crc = False
        tx_pkt.no_header = False
        tx_pkt.size = len(packet_bytes)

        for i, b in enumerate(packet_bytes[:256]):
            tx_pkt.payload[i] = b

        return tx_pkt

    async def _get_airtime(self, tx_pkt) -> int:
        """Compute airtime via the HAL (or estimate if unavailable)."""
        try:
            return await asyncio.to_thread(
                self._wrapper.get_time_on_air, tx_pkt
            )
        except Exception:
            return self._estimate_airtime(tx_pkt.size, tx_pkt.datarate)

    @staticmethod
    def _estimate_airtime(payload_size: int, sf: int) -> int:
        """Rough airtime estimate (ms) when HAL function unavailable."""
        symbol_time_ms = (2 ** sf) / 250.0
        n_symbols = 8 + max(
            ((8 * payload_size - 4 * sf + 28 + 16) // (4 * sf)) * 5 + 8, 0
        )
        return int((16 + n_symbols) * symbol_time_ms)

    def _next_packet_id(self) -> int:
        self._packet_counter = (self._packet_counter + 1) & 0xFFFFFFFF
        return self._packet_counter

    def _resolve_node_id(self) -> int:
        """Get or generate a 4-byte Meshtastic node ID."""
        if (
            self._config is not None
            and self._config.node_id is not None
            and self._config.node_id != 0
        ):
            return self._config.node_id
        return random.randint(0x01000000, 0xFFFFFFFE)

    def _compute_channel_hash(self, channel: int) -> int:
        """Compute channel hash for the default channel."""
        if self._crypto is None:
            return 0x08
        try:
            key = self._crypto.get_all_keys()[0]
            return self._crypto.compute_channel_hash("", key)
        except (IndexError, Exception):
            return 0x08

    @staticmethod
    def _resolve_destination(
        destination: int | str, protocol: Protocol
    ) -> int:
        if isinstance(destination, str):
            dest_lower = destination.lower()
            if dest_lower in ("broadcast", "all", "ffff", "ffffffff", "0"):
                return BROADCAST_ADDR_MT
            try:
                return int(destination, 16) if destination.startswith("!") else int(destination)
            except ValueError:
                return BROADCAST_ADDR_MT
        if destination == 0:
            return BROADCAST_ADDR_MT
        return destination

    @staticmethod
    def _resolve_coderate(coding_rate: str) -> int:
        """Map coding rate string to HAL constant."""
        rate_map = {
            "4/5": 0x01,
            "4/6": 0x02,
            "4/7": 0x03,
            "4/8": 0x04,
        }
        return rate_map.get(coding_rate, 0x01)
