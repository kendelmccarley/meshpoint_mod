"""REST endpoints for NodeInfo broadcast configuration and control.

Mounted under ``/api/config/nodeinfo*``. Three concerns:

- :func:`build_nodeinfo_status` builds the live block consumed by
  :mod:`config_routes` ``GET /api/config`` so the radio tab countdown
  card has both persisted config and live broadcaster telemetry.
- :func:`update_nodeinfo` writes the cadence to ``local.yaml``.
- :func:`send_nodeinfo_now` triggers the "Send Now" button on the
  radio tab.

Split out of ``config_routes.py`` to keep that file under the 500-line
cap and because NodeInfo cadence is its own UX surface in v0.7.1.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import AppConfig, save_section_to_yaml

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config/nodeinfo", tags=["config"])

_config: AppConfig | None = None
_nodeinfo_broadcaster = None


def init_routes(
    config: AppConfig,
    nodeinfo_broadcaster=None,
) -> None:
    global _config, _nodeinfo_broadcaster
    _config = config
    _nodeinfo_broadcaster = nodeinfo_broadcaster


def build_nodeinfo_status(ni) -> dict:
    """Build the NodeInfo block for ``GET /api/config``.

    Includes both the persisted config (interval, startup delay) and
    live broadcaster telemetry (running flag, last_sent_at, next_due_at)
    that the Radio tab uses to render the countdown card.
    Timestamps are emitted as UTC ISO-8601 strings so the JS Date
    constructor parses them losslessly.
    """
    last_sent = None
    next_due = None
    running = False
    if _nodeinfo_broadcaster is not None:
        running = _nodeinfo_broadcaster.is_running
        if _nodeinfo_broadcaster.last_sent_at is not None:
            last_sent = _nodeinfo_broadcaster.last_sent_at.isoformat()
        if _nodeinfo_broadcaster.next_due_at is not None:
            next_due = _nodeinfo_broadcaster.next_due_at.isoformat()
    return {
        "interval_minutes": ni.interval_minutes,
        "startup_delay_seconds": ni.startup_delay_seconds,
        "running": running,
        "last_sent_at": last_sent,
        "next_due_at": next_due,
    }


class NodeInfoUpdate(BaseModel):
    interval_minutes: Optional[int] = None
    startup_delay_seconds: Optional[int] = None


@router.put("")
async def update_nodeinfo(req: NodeInfoUpdate):
    """Update NodeInfo broadcast cadence. Always restart-required.

    Set ``interval_minutes`` to ``0`` to disable periodic broadcasts.
    Otherwise valid range is ``5..1440``.
    """
    if _config is None:
        raise HTTPException(503, "Config not loaded")

    ni = _config.transmit.nodeinfo
    updates: dict = {}

    if req.interval_minutes is not None:
        if req.interval_minutes != 0 and not 5 <= req.interval_minutes <= 1440:
            raise HTTPException(
                400,
                "interval_minutes must be 0 (disabled) or 5-1440 "
                "(5 min to 24 hr)",
            )
        ni.interval_minutes = req.interval_minutes
        updates["interval_minutes"] = req.interval_minutes
    if req.startup_delay_seconds is not None:
        if not 0 <= req.startup_delay_seconds <= 3600:
            raise HTTPException(
                400, "startup_delay_seconds must be 0-3600"
            )
        ni.startup_delay_seconds = req.startup_delay_seconds
        updates["startup_delay_seconds"] = req.startup_delay_seconds

    if updates:
        full_nodeinfo = {
            "interval_minutes": ni.interval_minutes,
            "startup_delay_seconds": ni.startup_delay_seconds,
        }
        try:
            save_section_to_yaml(
                "transmit", {"nodeinfo": full_nodeinfo}
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc))

    return {
        "saved": True,
        "restart_required": bool(updates),
        "updates": updates,
    }


@router.post("/send")
async def send_nodeinfo_now():
    """Trigger an immediate NodeInfo broadcast (the 'Send Now' button).

    Returns 503 when the broadcaster isn't running, which can happen
    if TX is disabled, the Meshtastic radio backend isn't ready, or
    the cadence is set to 0. On success, the broadcaster's
    ``last_sent_at`` is re-anchored so the dashboard countdown
    immediately reflects the new schedule.
    """
    if _nodeinfo_broadcaster is None:
        raise HTTPException(
            503,
            "NodeInfo broadcaster not active "
            "(TX disabled, radio not ready, or cadence set to 0).",
        )
    result = await _nodeinfo_broadcaster.broadcast_now()
    return {
        "success": result.success,
        "packet_id": result.packet_id,
        "airtime_ms": result.airtime_ms,
        "error": result.error,
    }
