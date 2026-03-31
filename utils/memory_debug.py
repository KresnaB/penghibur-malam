"""
Memory debug helpers for long-running bot sessions.

When enabled, this logs process RSS, Python heap usage, and the largest
allocation deltas between snapshots so we can spot slow growth over time.
"""

from __future__ import annotations

import asyncio
import gc
import logging
import os
import tracemalloc
from dataclasses import dataclass
from typing import Callable, Iterable

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None


logger = logging.getLogger("omnia.memory")


@dataclass
class MemoryPlayerSnapshot:
    guild_id: int
    queue_size: int
    current_title: str
    lyrics_messages: int
    has_idle_task: bool
    has_preload_task: bool
    has_progress_task: bool


class MemoryMonitor:
    """Periodically log memory health for the bot."""

    def __init__(
        self,
        *,
        bot,
        players_getter: Callable[[], Iterable],
        interval_seconds: int = 600,
        top_stats: int = 5,
        trace_depth: int = 25,
    ):
        self.bot = bot
        self.players_getter = players_getter
        self.interval_seconds = max(30, int(interval_seconds))
        self.top_stats = max(1, int(top_stats))
        self._task: asyncio.Task | None = None
        self._process = psutil.Process() if psutil else None
        self._previous_snapshot = None
        if not tracemalloc.is_tracing():
            tracemalloc.start(trace_depth)

    def start(self):
        """Start the background loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="memory-monitor")

    async def stop(self):
        """Stop the background loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._task = None

    async def _run(self):
        try:
            while True:
                await asyncio.sleep(self.interval_seconds)
                self.log_snapshot()
        except asyncio.CancelledError:
            pass

    def _collect_players(self) -> list[MemoryPlayerSnapshot]:
        snapshots: list[MemoryPlayerSnapshot] = []
        for player in self.players_getter() or []:
            current_title = getattr(getattr(player, "current", None), "title", "") or "None"
            snapshots.append(
                MemoryPlayerSnapshot(
                    guild_id=getattr(getattr(player, "guild", None), "id", 0),
                    queue_size=getattr(getattr(player, "queue", None), "size", 0) or 0,
                    current_title=current_title,
                    lyrics_messages=len(getattr(player, "lyrics_messages", []) or []),
                    has_idle_task=bool(getattr(player, "_idle_task", None)),
                    has_preload_task=bool(getattr(player, "_preload_task", None)),
                    has_progress_task=bool(getattr(player, "_progress_task", None)),
                )
            )
        return snapshots

    def log_snapshot(self):
        """Log a single memory snapshot."""
        rss_text = "n/a"
        if self._process is not None:
            try:
                rss_bytes = self._process.memory_info().rss
                rss_text = f"{rss_bytes / (1024 * 1024):.1f} MiB"
            except Exception:
                pass

        current, peak = tracemalloc.get_traced_memory()
        gc_counts = gc.get_count()
        tasks_total = len(asyncio.all_tasks())
        players = self._collect_players()
        queue_total = sum(p.queue_size for p in players)
        lyrics_total = sum(p.lyrics_messages for p in players)
        active_players = sum(1 for p in players if p.current_title != "None")

        logger.info(
            "Memory snapshot | rss=%s | py_current=%.1f MiB | py_peak=%.1f MiB | "
            "tasks=%d | players=%d | active=%d | queue=%d | lyrics_msgs=%d | gc=%s",
            rss_text,
            current / (1024 * 1024),
            peak / (1024 * 1024),
            tasks_total,
            len(players),
            active_players,
            queue_total,
            lyrics_total,
            gc_counts,
        )

        if players:
            details = " | ".join(
                f"guild={p.guild_id} queue={p.queue_size} current={p.current_title[:40]!r} lyrics={p.lyrics_messages}"
                for p in players[:5]
            )
            logger.info("Memory players: %s", details)

        snapshot = tracemalloc.take_snapshot()

        if self._previous_snapshot is not None:
            diffs = snapshot.compare_to(self._previous_snapshot, "lineno")
            growth = [item for item in diffs if item.size_diff > 0][: self.top_stats]
            if growth:
                lines = []
                for item in growth:
                    frame = item.traceback[0]
                    lines.append(
                        f"{frame.filename}:{frame.lineno} +{item.size_diff / 1024:.1f} KiB "
                        f"({item.count_diff:+d} blocks)"
                    )
                logger.info("Memory growth hotspots: %s", " | ".join(lines))
        self._previous_snapshot = snapshot
