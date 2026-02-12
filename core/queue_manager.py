"""
QueueManager — Async queue wrapper for music tracks.
"""

import asyncio
from typing import Optional
from core.ytdl_source import Track


class QueueManager:
    """Thread-safe async queue for managing music tracks."""

    def __init__(self):
        self._queue: list[Track] = []
        self._lock = asyncio.Lock()

    async def add(self, track: Track) -> int:
        """Add a track to the queue. Returns queue position."""
        async with self._lock:
            self._queue.append(track)
            return len(self._queue)

    async def get_next(self) -> Optional[Track]:
        """Get and remove the next track from the queue."""
        async with self._lock:
            if self._queue:
                return self._queue.pop(0)
            return None

    async def clear(self):
        """Clear all tracks from the queue."""
        async with self._lock:
            self._queue.clear()

    async def remove(self, index: int) -> Optional[Track]:
        """Remove a track at a specific index (0-based). Returns removed track."""
        async with self._lock:
            if 0 <= index < len(self._queue):
                return self._queue.pop(index)
            return None

    async def shuffle(self):
        """Shuffle the queue."""
        import random
        async with self._lock:
            random.shuffle(self._queue)

    @property
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self._queue) == 0

    @property
    def size(self) -> int:
        """Get number of tracks in queue."""
        return len(self._queue)

    def as_list(self, limit: int = 10) -> list[Track]:
        """Get a copy of the queue as a list, limited to `limit` items."""
        return self._queue[:limit]

    async def put_front(self, track: Track):
        """Put a track at the front of the queue (for loop single)."""
        async with self._lock:
            self._queue.insert(0, track)

    async def put_back(self, track: Track):
        """Put a track at the back of the queue (for loop queue)."""
        async with self._lock:
            self._queue.append(track)
