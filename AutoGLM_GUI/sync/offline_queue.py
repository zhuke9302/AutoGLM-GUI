from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueuedItem:
    """A single item in the offline queue."""

    id: int
    item_type: str  # "task_run", "task_events", "device_report", "execution_report"
    payload: str  # JSON string
    created_at: float  # Unix timestamp
    retry_count: int


class OfflineQueue:
    """SQLite-backed queue for storing data that failed to report to the server.

    Used when the server is unreachable. Items are replayed when connection is restored.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        capacity: int = 1000,
        expire_hours: int = 72,
    ):
        if db_path is None:
            db_path = Path.home() / ".config" / "autoglm" / "offline_queue.db"
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._capacity = capacity
        self._expire_hours = expire_hours
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        item_type TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        retry_count INTEGER NOT NULL DEFAULT 0
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_queue_type ON queue(item_type)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_queue_created ON queue(created_at)"
                )
                conn.commit()
            finally:
                conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a new SQLite connection with WAL mode."""
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def push(self, item_type: str, payload: dict[str, Any]) -> int | None:
        """Add an item to the queue.

        Returns the item ID, or None if the queue is at capacity.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                # Check capacity
                count = conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
                if count >= self._capacity:
                    logger.warning(
                        "Offline queue at capacity (%d), dropping item", self._capacity
                    )
                    return None

                cursor = conn.execute(
                    "INSERT INTO queue (item_type, payload, created_at, retry_count) VALUES (?, ?, ?, 0)",
                    (item_type, json.dumps(payload, ensure_ascii=False), time.time()),
                )
                conn.commit()
                item_id = cursor.lastrowid
                logger.debug("Queued %s item #%d", item_type, item_id)
                return item_id
            finally:
                conn.close()

    def peek(self, limit: int = 10) -> list[QueuedItem]:
        """Peek at the next items in the queue without removing them."""
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT id, item_type, payload, created_at, retry_count FROM queue ORDER BY id ASC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [
                    QueuedItem(
                        id=r[0],
                        item_type=r[1],
                        payload=r[2],
                        created_at=r[3],
                        retry_count=r[4],
                    )
                    for r in rows
                ]
            finally:
                conn.close()

    def pop(self, item_id: int) -> bool:
        """Remove an item from the queue after successful report."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM queue WHERE id = ?", (item_id,))
                conn.commit()
                return True
            finally:
                conn.close()

    def increment_retry(self, item_id: int) -> None:
        """Increment retry count for an item."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE queue SET retry_count = retry_count + 1 WHERE id = ?",
                    (item_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def size(self) -> int:
        """Return the number of items in the queue."""
        with self._lock:
            conn = self._get_conn()
            try:
                return conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
            finally:
                conn.close()

    def cleanup_expired(self) -> int:
        """Remove items older than expire_hours.

        Returns the number of items removed.
        """
        cutoff = time.time() - (self._expire_hours * 3600)
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM queue WHERE created_at < ?", (cutoff,)
                )
                conn.commit()
                removed = cursor.rowcount
                if removed > 0:
                    logger.info("Cleaned up %d expired offline queue items", removed)
                return removed
            finally:
                conn.close()

    def clear(self) -> None:
        """Clear all items from the queue."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM queue")
                conn.commit()
            finally:
                conn.close()
