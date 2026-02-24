"""
PlaylistStore — Simple JSON-based storage for per-guild playlists.

Playlists are shared per server (guild), not per-user.
Each guild can have up to MAX_PLAYLISTS playlists.
Each playlist is truncated to MAX_TRACKS tracks when saved.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class PlaylistStore:
    """JSON-backed playlist storage with per-guild separation."""

    MAX_PLAYLISTS = 100
    MAX_TRACKS = 50

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock = asyncio.Lock()
        self._data: Dict[str, List[Dict[str, Any]]] = {}

    async def _load(self):
        """Load playlists from disk into memory."""
        async with self._lock:
            if self._data:
                return
            if not self._path.exists():
                self._data = {"guilds": {}}
                return
            try:
                raw = self._path.read_text(encoding="utf-8")
                if not raw.strip():
                    self._data = {"guilds": {}}
                    return
                self._data = json.loads(raw)
                if "guilds" not in self._data or not isinstance(self._data["guilds"], dict):
                    self._data = {"guilds": {}}
            except Exception:
                # If file is corrupted, reset in-memory structure (do not overwrite on disk yet)
                self._data = {"guilds": {}}

    async def _save(self):
        """Persist current playlists to disk."""
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self._path)

    async def get_playlists(self, guild_id: int) -> List[Dict[str, Any]]:
        """Return list of playlists for a guild."""
        await self._load()
        gid = str(guild_id)
        return list(self._data.get("guilds", {}).get(gid, []))

    async def add_playlist(self, guild_id: int, playlist: Dict[str, Any]) -> (bool, Optional[str]):
        """
        Add a playlist for a guild.
        Returns (success, error_message).
        """
        await self._load()
        gid = str(guild_id)
        guilds = self._data.setdefault("guilds", {})
        plist = guilds.setdefault(gid, [])

        if len(plist) >= self.MAX_PLAYLISTS:
            return False, "FULL"

        # Enforce track limit when saving
        tracks = playlist.get("tracks") or []
        if len(tracks) > self.MAX_TRACKS:
            playlist = dict(playlist)
            playlist["tracks"] = tracks[: self.MAX_TRACKS]

        plist.append(playlist)
        await self._save()
        return True, None

    async def delete_playlist(self, guild_id: int, name: str) -> bool:
        """
        Delete first playlist whose name matches (case-insensitive).
        Returns True if deleted.
        """
        await self._load()
        gid = str(guild_id)
        guilds = self._data.setdefault("guilds", {})
        plist = guilds.get(gid)
        if not plist:
            return False

        name_lower = name.strip().lower()
        for idx, pl in enumerate(plist):
            if str(pl.get("name", "")).strip().lower() == name_lower:
                del plist[idx]
                if not plist:
                    guilds.pop(gid, None)
                await self._save()
                return True
        return False

