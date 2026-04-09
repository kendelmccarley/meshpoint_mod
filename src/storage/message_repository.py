"""SQLite repository for sent and received mesh messages.

Stores TEXT_MESSAGE packets with conversation grouping for the
local dashboard chat interface. Supports both Meshtastic and
MeshCore messages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.storage.database import DatabaseManager

logger = logging.getLogger(__name__)

BROADCAST_NODE_MT = "broadcast:meshtastic"
BROADCAST_NODE_MC = "broadcast:meshcore"


@dataclass
class Message:
    """A single sent or received message."""

    id: int
    direction: str
    text: str
    node_id: str
    node_name: str
    protocol: str
    channel: int
    timestamp: str
    status: str
    packet_id: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "direction": self.direction,
            "text": self.text,
            "node_id": self.node_id,
            "node_name": self.node_name,
            "protocol": self.protocol,
            "channel": self.channel,
            "timestamp": self.timestamp,
            "status": self.status,
            "packet_id": self.packet_id,
        }


@dataclass
class Conversation:
    """Summary of a conversation with a single node or channel."""

    node_id: str
    node_name: str
    protocol: str
    last_message: str
    last_timestamp: str
    unread_count: int
    is_broadcast: bool

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "protocol": self.protocol,
            "last_message": self.last_message,
            "last_timestamp": self.last_timestamp,
            "unread_count": self.unread_count,
            "is_broadcast": self.is_broadcast,
        }


class MessageRepository:
    """CRUD operations for mesh messages with conversation grouping."""

    def __init__(self, db: DatabaseManager):
        self._db = db

    async def save_sent(
        self,
        text: str,
        node_id: str,
        node_name: str,
        protocol: str,
        channel: int = 0,
        packet_id: str = "",
        status: str = "sent",
    ) -> int:
        """Record an outbound message. Returns the row ID."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            """INSERT INTO messages
               (direction, text, node_id, node_name, protocol,
                channel, timestamp, status, packet_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("sent", text, node_id, node_name, protocol,
             channel, now, status, packet_id),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def save_received(
        self,
        text: str,
        node_id: str,
        node_name: str,
        protocol: str,
        channel: int = 0,
        packet_id: str = "",
    ) -> int:
        """Record an inbound message. Returns the row ID."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            """INSERT INTO messages
               (direction, text, node_id, node_name, protocol,
                channel, timestamp, status, packet_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("received", text, node_id, node_name, protocol,
             channel, now, "delivered", packet_id),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_conversations(self) -> list[Conversation]:
        """List all conversations, most recent first."""
        rows = await self._db.fetch_all(
            """SELECT node_id, node_name, protocol, text, timestamp,
                      SUM(CASE WHEN direction = 'received'
                               AND status != 'read' THEN 1 ELSE 0 END) as unread
               FROM messages
               GROUP BY node_id
               ORDER BY MAX(timestamp) DESC"""
        )
        return [
            Conversation(
                node_id=r["node_id"],
                node_name=r["node_name"] or r["node_id"],
                protocol=r["protocol"],
                last_message=_truncate(r["text"], 80),
                last_timestamp=r["timestamp"],
                unread_count=r["unread"],
                is_broadcast=r["node_id"].startswith("broadcast:"),
            )
            for r in rows
        ]

    async def get_conversation(
        self,
        node_id: str,
        limit: int = 50,
        before: Optional[str] = None,
    ) -> list[Message]:
        """Get paginated messages for a single conversation."""
        if before:
            rows = await self._db.fetch_all(
                """SELECT * FROM messages
                   WHERE node_id = ? AND timestamp < ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (node_id, before, limit),
            )
        else:
            rows = await self._db.fetch_all(
                """SELECT * FROM messages
                   WHERE node_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (node_id, limit),
            )
        messages = [self._row_to_message(r) for r in rows]
        messages.reverse()
        return messages

    async def get_channel_messages(
        self, protocol: str, channel: int = 0, limit: int = 50
    ) -> list[Message]:
        """Get messages from a broadcast channel."""
        node_id = f"broadcast:{protocol}:{channel}"
        return await self.get_conversation(node_id, limit)

    async def mark_read(self, node_id: str) -> None:
        """Mark all received messages in a conversation as read."""
        await self._db.execute(
            """UPDATE messages SET status = 'read'
               WHERE node_id = ? AND direction = 'received'
               AND status != 'read'""",
            (node_id,),
        )
        await self._db.commit()

    async def get_message_count(self) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) as count FROM messages"
        )
        return row["count"] if row else 0

    @staticmethod
    def _row_to_message(row: dict) -> Message:
        return Message(
            id=row["id"],
            direction=row["direction"],
            text=row["text"],
            node_id=row["node_id"],
            node_name=row["node_name"] or "",
            protocol=row["protocol"],
            channel=row["channel"],
            timestamp=row["timestamp"],
            status=row["status"],
            packet_id=row["packet_id"] or "",
        )


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
