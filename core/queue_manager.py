"""
QueueManager — Async queue wrapper for music tracks.
"""

from __future__ import annotations

import asyncio
from typing import Optional
from core.ytdl_source import Track


class QueueManager:
    """Thread-safe async queue for managing music tracks."""

    def __init__(self):
        self._queue: list[Track] = []
        self._lock = asyncio.Lock()
        self._counter = 0

    async def add(self, track: Track) -> int:
        """Add a track to the queue. Returns queue position."""
        async with self._lock:
            self._counter += 1
            track.insert_id = self._counter
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
            self._counter = 0

    async def remove(self, index: int) -> Optional[Track]:
        """Remove a track at a specific index (0-based). Returns removed track."""
        async with self._lock:
            if 0 <= index < len(self._queue):
                return self._queue.pop(index)
            return None

    async def shuffle(self, mode: int):
        """
        Shuffle the queue based on mode:
        0: Off (Restore original order)
        1: Standard (Random)
        2: Riffle (Interleave)
        """
        import random
        async with self._lock:
            if mode == 0:
                # Restore original order based on insert_id
                self._queue.sort(key=lambda t: t.insert_id)
            elif mode == 1:
                # Standard random shuffle
                random.shuffle(self._queue)
            elif mode == 2:
                # Riffle shuffle (Simulate card shuffling)
                # Split into two halves and interleave
                if len(self._queue) < 2:
                    return

                # Perform a few riffs for better effect
                for _ in range(3):
                    mid = len(self._queue) // 2
                    left = self._queue[:mid]
                    right = self._queue[mid:]
                    self._queue = []
                    while left or right:
                        if left: self._queue.append(left.pop(0))
                        if right: self._queue.append(right.pop(0))

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
