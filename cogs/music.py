"""
Music Cog — Slash commands for the music bot.
Handles all user-facing commands and voice state events.
"""

from __future__ import annotations

import asyncio
import os
import logging
import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from core.music_player import MusicPlayer, LoopMode, AutoplayMode
from core.ytdl_source import Track, YTDLSource
from utils.embed_builder import EmbedBuilder
from utils.memory_debug import MemoryMonitor
from utils.now_playing_view import NowPlayingView
from utils.genius_lyrics import search_lyrics, split_lyrics
from utils.lyrics_service import get_lyrics_concurrently
from utils.playlist_store import PlaylistStore
from utils.radio_browser import RADIO_CATEGORY_PRESETS, RADIO_PAGE_SIZE, RadioBrowserClient

logger = logging.getLogger('omnia.music')


class Music(commands.Cog):
    """Music commands for Omnia bot."""

    CHAT_CLEANUP_DELAY = 20

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, MusicPlayer] = {}  # guild_id -> MusicPlayer
        self._background_tasks: set[asyncio.Task] = set()
        self._memory_monitor: MemoryMonitor | None = None
        # Shared playlist storage (per guild, shared by all users)
        base_path = Path(__file__).resolve().parent.parent
        data_path = base_path / "data"
        data_path.mkdir(exist_ok=True)
        self.playlists = PlaylistStore(data_path / "playlists.json")
        self.radio_browser = RadioBrowserClient()

    def get_player(self, guild: discord.Guild) -> MusicPlayer:
        """Get or create MusicPlayer for a guild."""
        if guild.id not in self.players:
            player = MusicPlayer(self.bot, guild)
            player._view_factory = lambda p: NowPlayingView(p)
            player._cleanup_callback = self.cleanup_player
            self.players[guild.id] = player
        return self.players[guild.id]

    def _track_background_task(self, task: asyncio.Task):
        """Keep track of background tasks so they can be cancelled on unload."""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _build_track_from_entry(
        self,
        entry: dict,
        requester: discord.abc.User,
        playlist_title: str | None = None,
    ) -> Track | None:
        """Convert a yt-dlp entry into a Track object."""
        web_url = entry.get("webpage_url")
        if not web_url:
            if entry.get("url"):
                if len(entry["url"]) == 11:
                    web_url = f"https://www.youtube.com/watch?v={entry['url']}"
                else:
                    web_url = entry["url"]
            elif entry.get("id"):
                web_url = f"https://www.youtube.com/watch?v={entry['id']}"
            else:
                return None

        source_url = "" if playlist_title else entry.get("url", "")
        if "youtube.com/watch" in source_url or "youtu.be/" in source_url:
            source_url = ""

        return Track(
            source_url=source_url,
            title=entry.get("title", "Unknown"),
            url=web_url,
            duration=entry.get("duration", 0),
            thumbnail=entry.get("thumbnail", ""),
            uploader=entry.get("uploader", "Unknown"),
            requester=requester,
        )

    async def _enqueue_playlist_background(
        self,
        player: MusicPlayer,
        entries: list[dict],
        requester: discord.abc.User,
        playlist_title: str | None,
        *,
        token: int,
    ):
        """Enqueue the rest of a playlist without blocking playback."""
        try:
            for index, entry in enumerate(entries, start=1):
                if not player.is_playlist_enqueue_active(token):
                    logger.info(
                        "cmd:play playlist enqueue cancelled for guild=%s after %s queued tracks",
                        player.guild.id,
                        index - 1,
                    )
                    return

                track = self._build_track_from_entry(entry, requester, playlist_title=playlist_title)
                if track is None:
                    continue

                await player.add_track(track)

                # Yield periodically so the event loop can start playback and
                # handle other commands while a long playlist is being filled.
                if index % 10 == 0:
                    await asyncio.sleep(0)

                await player.ensure_playing()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "cmd:play playlist background enqueue failed for guild=%s: %s",
                player.guild.id,
                e,
            )

    async def _load_and_enqueue_playlist_background(
        self,
        player: MusicPlayer,
        query: str,
        requester: discord.abc.User,
        playlist_title: str | None,
        *,
        token: int,
    ):
        """Extract the remaining playlist entries and enqueue them in the background."""
        try:
            entries, _ = await YTDLSource.get_info(
                query,
                loop=self.bot.loop,
                playlist_items="2:",
            )
            if not player.is_playlist_enqueue_active(token):
                return
            if entries:
                await self._enqueue_playlist_background(
                    player,
                    entries,
                    requester,
                    playlist_title,
                    token=token,
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "cmd:play playlist background extraction failed for guild=%s: %s",
                player.guild.id,
                e,
            )

    def cleanup_player(self, guild_id: int):
        """Remove player for a guild."""
        if guild_id in self.players:
            del self.players[guild_id]

    async def _load_radio_stations(self, category_key: str, *, limit: int = RADIO_PAGE_SIZE * 3) -> list[dict]:
        """Load radio stations for a category using Radio Browser."""
        return await self.radio_browser.fetch_category(category_key, limit=limit)

    async def cog_load(self):
        """Start optional background services."""
        if os.getenv("DEBUG_MEMORY", "").strip().lower() in {"1", "true", "yes", "on"}:
            interval = int(os.getenv("DEBUG_MEMORY_INTERVAL", "600"))
            self._memory_monitor = MemoryMonitor(
                bot=self.bot,
                players_getter=lambda: list(self.players.values()),
                interval_seconds=interval,
            )
            self._memory_monitor.start()
            logger.info(
                "Memory debug enabled: interval=%ss",
                self._memory_monitor.interval_seconds,
            )

    async def cog_unload(self):
        """Stop optional background services."""
        if self._background_tasks:
            for task in list(self._background_tasks):
                task.cancel()
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        if self._memory_monitor is not None:
            await self._memory_monitor.stop()
            self._memory_monitor = None

    async def _send_embed(
        self,
        interaction: discord.Interaction,
        embed: discord.Embed,
        *,
        ephemeral: bool = False,
        delete_after: int | None = None,
    ):
        """Send an embed and auto-delete non-ephemeral confirmations."""
        if not ephemeral and delete_after is None:
            delete_after = self.CHAT_CLEANUP_DELAY

        payload = {"embed": embed, "ephemeral": ephemeral}
        if interaction.response.is_done():
            if delete_after is not None and not ephemeral:
                message = await interaction.followup.send(**payload, wait=True)

                async def _delete_later(msg: discord.Message, delay: int):
                    await asyncio.sleep(delay)
                    try:
                        await msg.delete()
                    except Exception:
                        pass

                asyncio.create_task(_delete_later(message, delete_after))
            else:
                await interaction.followup.send(**payload)
        else:
            if delete_after is not None and not ephemeral:
                payload["delete_after"] = delete_after
            await interaction.response.send_message(**payload)

    # ─────────────────────── Helper Checks ───────────────────────

    def _parse_timestamp(self, value: str) -> int | None:
        """
        Parse timestamp string into total seconds.
        Supported formats:
        - "90" (detik)
        - "mm:ss"
        - "hh:mm:ss"
        """
        if not value:
            return None

        value = value.strip()

        # Pure seconds
        if value.isdigit():
            return int(value)

        parts = value.split(":")
        if not (1 <= len(parts) <= 3):
            return None

        try:
            parts = [int(p) for p in parts]
        except ValueError:
            return None

        # Normalize to [hh, mm, ss]
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h, m, s = 0, parts[0], parts[1]
        else:  # len == 1
            h, m, s = 0, 0, parts[0]

        if any(x < 0 for x in (h, m, s)):
            return None

        # Basic sanity for mm/ss
        if m >= 60 or s >= 60:
            return None

        return h * 3600 + m * 60 + s

    def _parse_duration(self, value: str) -> int | None:
        """
        Parse duration strings like:
        - `45m`
        - `1h`
        - `1h30m`
        - `90s`
        - `off` / `cancel`
        """
        if not value:
            return None

        value = value.strip().lower()
        if value in {"off", "cancel", "none", "stop"}:
            return 0

        pattern = r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?"
        match = re.fullmatch(pattern, value)
        if not match:
            if value.isdigit():
                return int(value) * 60
            return None

        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = int(match.group(3) or 0)
        total = hours * 3600 + minutes * 60 + seconds
        return total if total > 0 else None

    async def _ensure_voice(self, interaction: discord.Interaction) -> bool:
        """Check that user is in a voice channel. Returns False if not."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Kamu harus berada di voice channel terlebih dahulu!"),
                ephemeral=True
            )
            return False
        return True

    async def _ensure_same_channel(self, interaction: discord.Interaction) -> bool:
        """Check that user is in the same voice channel as bot."""
        vc = interaction.guild.voice_client
        if vc and interaction.user.voice:
            if vc.channel.id != interaction.user.voice.channel.id:
                await interaction.response.send_message(
                    embed=EmbedBuilder.error(
                        f"Kamu harus berada di **{vc.channel.name}** untuk menggunakan command ini!"
                    ),
                    ephemeral=True
                )
                return False
        return True

    # ─────────────────────── /play ───────────────────────

    @app_commands.command(name="play", description="Putar lagu dari YouTube (URL, Playlist, atau pencarian)")
    @app_commands.describe(query="YouTube URL, Playlist URL, atau kata kunci pencarian")
    async def play(self, interaction: discord.Interaction, query: str):
        """Play a track or playlist from YouTube."""
        start_time = asyncio.get_event_loop().time()
        logger.info(f"cmd:play START query='{query}' user={interaction.user.id}")

        if not await self._ensure_voice(interaction):
            return

        # Defer immediately because extraction can take time.
        await interaction.response.defer()

        player = self.get_player(interaction.guild)
        player.text_channel = interaction.channel

        try:
            await player.connect(interaction.user.voice.channel)
        except Exception as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error(f"Gagal join voice channel: `{e}`")
            )
            return

        t_connect = asyncio.get_event_loop().time()
        logger.info(f"cmd:play CONNECTED took {t_connect - start_time:.2f}s")

        try:
            first_playlist_items = "1" if "list=" in query and "list=RD" not in query else None
            entries, playlist_title = await YTDLSource.get_info(
                query,
                loop=self.bot.loop,
                playlist_items=first_playlist_items,
            )
        except Exception as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error(f"Gagal mencari lagu: `{e}`")
            )
            return

        t_extract = asyncio.get_event_loop().time()
        logger.info(f"cmd:play EXTRACTED took {t_extract - t_connect:.2f}s. Entries: {len(entries)}")
        if entries:
            logger.info(f"First entry URL check: Is stream? {'googlevideo' in str(entries[0].get('url', ''))}")

        if not entries:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Tidak ditemukan lagu.")
            )
            return

        first_track = None
        for entry in entries:
            first_track = self._build_track_from_entry(entry, interaction.user, playlist_title=playlist_title)
            if first_track is not None:
                break

        if first_track is None:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Gagal memproses lagu dari playlist.")
            )
            return

        if player.current and player.current.duration == 0 and player.current.source_url:
            current_url = str(player.current.url or "")
            is_youtube_current = "youtube.com/watch" in current_url or "youtu.be/" in current_url
            if not is_youtube_current:
                logger.info(
                    "cmd:play interrupting live stream before starting '%s'",
                    playlist_title or first_track.title,
                )
                await player.stop()
                for _ in range(10):
                    if not getattr(player, "_stopping", False):
                        break
                    await asyncio.sleep(0.1)

        player.cancel_playlist_enqueue()

        is_playlist_query = bool(playlist_title)
        was_playing = player.is_playing or player.current is not None

        position = await player.add_track(first_track)

        # Start playback IMMEDIATELY before sending embed — minimise delay
        if not player.is_playing:
            if player.current and (not player.voice_client or not player.voice_client.is_connected()):
                player.current = None
            # Fire-and-forget so playback begins while we still respond to the user
            asyncio.create_task(player.ensure_playing())

        # Start background loading of remaining playlist tracks
        if is_playlist_query:
            playlist_token = player.begin_playlist_enqueue()
            task = asyncio.create_task(
                self._load_and_enqueue_playlist_background(
                    player,
                    query,
                    interaction.user,
                    playlist_title,
                    token=playlist_token,
                )
            )
            self._track_background_task(task)

        t_process = asyncio.get_event_loop().time()
        logger.info(
            "cmd:play QUEUED first track in %.2fs. Playlist background=%s",
            t_process - t_extract,
            is_playlist_query,
        )

        if not is_playlist_query:
            if was_playing:
                await self._send_embed(interaction, EmbedBuilder.added_to_queue(first_track, position))
            else:
                await self._send_embed(
                    interaction,
                    EmbedBuilder.success(
                        "🎵 Memulai Pemutaran",
                        f"**[{first_track.title}]({first_track.url})**"
                    ),
                )
        else:
            await self._send_embed(
                interaction,
                EmbedBuilder.success(
                    "📜 Playlist Ditambahkan",
                    f"Lagu pertama dari **{playlist_title or 'Playlist'}** sudah dimulai, dan sisa playlist diproses di background.",
                ),
            )
    # ─────────────────────── /skip ───────────────────────

    @app_commands.command(name="skip", description="Skip lagu yang sedang diputar")
    async def skip(self, interaction: discord.Interaction):
        """Skip the current track."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)

        if not player.is_playing:
            await self._send_embed(
                interaction,
                EmbedBuilder.error("Tidak ada lagu yang sedang diputar!"),
                ephemeral=True,
            )
            return

        current_title = player.current.title if player.current else "Unknown"
        await player.skip()
        await self._send_embed(interaction, EmbedBuilder.success("â­ï¸ Skipped", f"**{current_title}**"))

    # ─────────────────────── /seek ───────────────────────

    @app_commands.command(name="seek", description="Loncat ke timestamp tertentu di lagu yang sedang diputar")
    @app_commands.describe(
        timestamp="Timestamp tujuan (detik, mm:ss, atau hh:mm:ss)"
    )
    async def seek(self, interaction: discord.Interaction, timestamp: str):
        """Seek to a specific position in the current track."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)

        if not player.current or not player.is_playing:
            await self._send_embed(
                interaction,
                EmbedBuilder.error("Tidak ada lagu yang sedang diputar!"),
                ephemeral=True,
            )
            return

        seconds = self._parse_timestamp(timestamp)
        if seconds is None:
            await self._send_embed(
                interaction,
                EmbedBuilder.error(
                    "Format timestamp tidak valid.\n"
                    "Gunakan salah satu format berikut:\n"
                    "- `120` (detik)\n"
                    "- `2:30` (menit:detik)\n"
                    "- `1:02:30` (jam:menit:detik)"
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        success = await player.seek(seconds)
        if not success:
            await self._send_embed(
                interaction,
                EmbedBuilder.error("Gagal melakukan seek ke posisi tersebut."),
                ephemeral=True,
            )
            return

        # Bangun teks posisi untuk user
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h > 0:
            pos_str = f"{h:02d}:{m:02d}:{s:02d}"
        else:
            pos_str = f"{m:02d}:{s:02d}"

        await self._send_embed(
            interaction,
            EmbedBuilder.success(
                "â© Seek",
                f"Lompat ke posisi **{pos_str}** pada lagu saat ini."
            )
        )

    # ─────────────────────── /stop ───────────────────────

    @app_commands.command(name="stop", description="Stop pemutaran dan kosongkan queue")
    async def stop(self, interaction: discord.Interaction):
        """Stop playback and clear queue without leaving voice."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)
        await player.stop()

        await self._send_embed(
            interaction,
            EmbedBuilder.success(
                "â¹ï¸ Stopped",
                "Pemutaran dihentikan dan queue dikosongkan. Bot tetap di voice channel."
            )
        )

    # ─────────────────────── /sleep ───────────────────────

    @app_commands.command(name="sleep", description="Atur timer untuk stop dan disconnect otomatis")
    @app_commands.describe(duration="Contoh: 30m, 1h30m, 90s, atau off untuk membatalkan")
    async def sleep(self, interaction: discord.Interaction, duration: str):
        """Set or cancel a sleep timer."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)
        seconds = self._parse_duration(duration)
        if seconds is None:
            await self._send_embed(
                interaction,
                EmbedBuilder.error(
                    "Format timer tidak valid.\n"
                    "Gunakan `30m`, `1h30m`, `90s`, atau `off`."
                ),
                ephemeral=True,
            )
            return

        if seconds == 0:
            await player.cancel_sleep_timer()
            await self._send_embed(
                interaction,
                EmbedBuilder.success("😴 Sleep Timer", "Timer tidur dibatalkan.")
            )
            return

        await player.set_sleep_timer(seconds, label=f"Timer tidur {duration}")
        await self._send_embed(
            interaction,
            EmbedBuilder.success(
                "😴 Sleep Timer",
                f"Bot akan stop dan disconnect dalam **{duration}**."
            )
        )

    # ─────────────────────── /reconnect ───────────────────────

    @app_commands.command(name="reconnect", description="Reset bot dan connect ulang ke voice")
    async def reconnect(self, interaction: discord.Interaction):
        """Force disconnect, reset state, and reconnect to voice."""
        if not await self._ensure_voice(interaction):
            return

        # Defer interaction as this involves disconnect/connect
        await interaction.response.defer()

        guild = interaction.guild
        voice_channel = interaction.user.voice.channel

        # 1. Force Disconnect & Cleanup
        try:
            player = self.get_player(guild)
            await player.stop()     # Clear queue and state
            await player.disconnect()
            
            # Explicitly cleanup
            self.cleanup_player(guild.id)
            
            # Additional cleanup for safety
            if guild.voice_client:
                await guild.voice_client.disconnect(force=True)
                
        except Exception as e:
            logger.warning(f"Error during disconnect phase: {e}")

        await asyncio.sleep(1) # Brief pause

        # 2. Re-Initialize and Connect
        try:
            player = self.get_player(guild)
            player.text_channel = interaction.channel
            await player.connect(voice_channel)
            
            await interaction.followup.send(
                embed=EmbedBuilder.success(
                    "🔄 Reconnected", 
                    f"Bot berhasil di-reset dan terhubung kembali ke **{voice_channel.name}**."
                )
            )
        except Exception as e:
            logger.error(f"Failed to reconnect: {e}")
            await interaction.followup.send(
                embed=EmbedBuilder.error(f"Gagal reconnect: `{e}`")
            )

    # ─────────────────────── /queue ───────────────────────

    @app_commands.command(name="queue", description="Tampilkan antrian lagu")
    async def queue(self, interaction: discord.Interaction):
        """Show the current queue."""
        player = self.get_player(interaction.guild)

        tracks = player.queue.as_list(limit=20)
        total = player.queue.size
        embed = EmbedBuilder.queue_list(tracks, player.current, total)

        # Add loop and autoplay status
        status_parts = []
        if player.loop_mode != LoopMode.OFF:
            status_parts.append(f"ðŸ” Loop: **{player.loop_mode}**")
        if player.autoplay_mode == AutoplayMode.YOUTUBE:
            status_parts.append("🔄 Autoplay: **YouTube**")
        elif player.autoplay_mode == AutoplayMode.CUSTOM:
            status_parts.append("🔄 Autoplay: **Custom 1**")
        elif player.autoplay_mode == AutoplayMode.CUSTOM2:
            status_parts.append("🔄 Autoplay: **Custom 2**")
        if status_parts:
            embed.add_field(name="âš™ï¸ Status", value=" â€¢ ".join(status_parts), inline=False)

        await self._send_embed(interaction, embed)

    # ─────────────────────── /nowplaying ───────────────────────

    @app_commands.command(name="nowplaying", description="Tampilkan lagu yang sedang diputar")
    async def nowplaying(self, interaction: discord.Interaction):
        """Show the currently playing track."""
        player = self.get_player(interaction.guild)

        if not player.current:
            await self._send_embed(
                interaction,
                EmbedBuilder.error("Tidak ada lagu yang sedang diputar!"),
                ephemeral=True,
            )
            return

        embed = EmbedBuilder.now_playing(
            player.current,
            progress=player.current_progress_bar() if hasattr(player, "current_progress_bar") else None,
        )

        # Add extra info
        info_parts = []
        if player.loop_mode != LoopMode.OFF:
            info_parts.append(f"ðŸ” Loop: {player.loop_mode}")
        if player.autoplay_mode != AutoplayMode.OFF:
            if player.autoplay_mode == AutoplayMode.YOUTUBE:
                mode_name = "YouTube"
            elif player.autoplay_mode == AutoplayMode.CUSTOM:
                mode_name = "Custom 1"
            else:
                mode_name = "Custom 2"
            info_parts.append(f"🔄 Autoplay: {mode_name}")
        info_parts.append(f"📋 Queue: {player.queue.size} lagu")

        embed.add_field(name="âš™ï¸ Info", value=" â€¢ ".join(info_parts), inline=False)

        await self._send_embed(interaction, embed)

    # ─────────────────────── /playlist ───────────────────────

    @app_commands.command(name="playlistplay", description="Pilih playlist server untuk diputar")
    async def playlistplay(self, interaction: discord.Interaction):
        """Show saved playlists for this guild and allow user to choose one to play."""
        playlists = await self.playlists.get_playlists(interaction.guild.id)
        if not playlists:
            await self._send_embed(
                interaction,
                EmbedBuilder.info(
                    "📂 Playlist Kosong",
                    "Belum ada playlist yang disimpan untuk server ini.\n"
                    "Gunakan `/playlistcopy` untuk menyalin playlist YouTube."
                ),
                ephemeral=True,
            )
            return

        view = PlaylistSelectView(self, interaction.guild, interaction.user, playlists)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="playlist", description="Tampilkan daftar playlist server")
    async def playlist(self, interaction: discord.Interaction):
        """Show saved playlists for this guild without the select menu."""
        playlists = await self.playlists.get_playlists(interaction.guild.id)
        if not playlists:
            await interaction.response.send_message(
                embed=EmbedBuilder.info(
                    "📂 Playlist Kosong",
                    "Belum ada playlist yang disimpan untuk server ini.\n"
                    "Gunakan `/playlistcopy` untuk menyalin playlist YouTube."
                ),
                ephemeral=True,
            )
            return

        lines = []
        for i, pl in enumerate(playlists, start=1):
            name = str(pl.get("name", "Untitled"))
            track_count = len(pl.get("tracks") or [])
            lines.append(f"`{i}.` **{name}** — {track_count} lagu")
        
        # Max description is 4096 chars, 100 playlists should fit.
        # If not, we can chunk it, but we keep it simple here.
        embed = discord.Embed(
            title="📂 Daftar Playlist Server",
            description="\n".join(lines)[:4096],
            color=discord.Color.from_rgb(138, 43, 226),
        )
        await self._send_embed(interaction, embed)

    # ─────────────────────── /playlistdelete ───────────────────────

    @app_commands.command(name="playlistdelete", description="Hapus playlist yang tersimpan di server")
    async def playlistdelete(self, interaction: discord.Interaction):
        """Show a dropdown of playlists for this guild and delete the selected one."""
        playlists = await self.playlists.get_playlists(interaction.guild.id)
        if not playlists:
            await self._send_embed(
                interaction,
                EmbedBuilder.info(
                    "📂 Playlist Kosong",
                    "Belum ada playlist yang disimpan untuk server ini.\n"
                    "Gunakan `/playlistcopy` untuk menyalin playlist YouTube."
                ),
                ephemeral=True,
            )
            return

        view = PlaylistDeleteView(self, interaction.guild, playlists)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ─────────── /move ───────────

    @app_commands.command(name="move", description="Pindahkan lagu di queue ke posisi lain")
    @app_commands.describe(from_pos="Posisi lagu sekarang (angka)", to_pos="Posisi tujuan (angka)")
    async def move(self, interaction: discord.Interaction, from_pos: int, to_pos: int):
        """Move a track in the queue."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)
        queue_size = player.queue.size

        if queue_size < 1:
             await interaction.response.send_message(
                embed=EmbedBuilder.error("Queue kosong!"),
                ephemeral=True
            )
             return

        # Adjust indices (user input is 1-based, internal is 0-based)
        src_idx = from_pos - 1
        tgt_idx = to_pos - 1

        # Validate source
        if not (0 <= src_idx < queue_size):
            await interaction.response.send_message(
                embed=EmbedBuilder.error(f"Posisi asal tidak valid! (1 - {queue_size})"),
                ephemeral=True
            )
            return
        
        # Move track
        moved_track = await player.queue.move(src_idx, tgt_idx)
        
        if moved_track:
             # Clamp target index for display
             final_pos = max(1, min(to_pos, queue_size))
             await interaction.response.send_message(
                embed=EmbedBuilder.success(
                    "🚚 Moved",
                    f"**{moved_track.title}** dipindahkan dari posisi **{from_pos}** ke **{final_pos}**."
                )
            )
        else:
             await interaction.response.send_message(
                embed=EmbedBuilder.error("Gagal memindahkan lagu."),
                ephemeral=True
            )

    # ─────────────────────── /lyrics ───────────────────────

    @app_commands.command(name="lyrics", description="Cari lirik lagu dari Genius")
    @app_commands.describe(query="Judul lagu (kosongkan untuk lagu yang sedang diputar)")
    async def lyrics(self, interaction: discord.Interaction, query: str = None):
        """Search for song lyrics on Genius."""
        await interaction.response.defer()

        # Determine search query
        search_query = query
        if not search_query:
            player = self.get_player(interaction.guild)
            if player.current:
                search_query = player.current.title
            else:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        "Tidak ada lagu yang sedang diputar!\n"
                        "Gunakan `/lyrics query:<judul lagu>` untuk mencari lirik."
                    ),
                    ephemeral=True
                )
                return

        # Search Lyrics Concurrently (Race)
        duration = None
        if not query:
             player = self.get_player(interaction.guild)
             if player.current:
                 duration = player.current.duration

        logger.info(f"Lyrics command: Racing for '{search_query}' duration={duration}")
        result = await get_lyrics_concurrently(search_query, duration=duration, loop=self.bot.loop)

        if not result:
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    f"Lirik tidak ditemukan untuk: **{search_query}**\n"
                    "Coba gunakan `/lyrics query:<judul lagu>` dengan kata kunci yang lebih spesifik."
                )
            )
            return

        # Build lyrics embed(s)
        lyrics_text = result.get('lyrics') or result.get('syncedLyrics')
        source = result.get('source', 'Unknown')
        
        if not lyrics_text:
             await interaction.followup.send(
                embed=EmbedBuilder.error(f"Konten lirik kosong ({source}).")
            )
             return

        chunks = split_lyrics(lyrics_text, max_length=4096)
        
        color = discord.Color.from_rgb(0, 255, 255) if source == 'Lrclib' else discord.Color.from_rgb(255, 255, 100)

        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"🎤 {result.get('title', search_query)}" if i == 0 else f"🎤 {result.get('title', search_query)} (lanjutan)",
                description=chunk,
                color=color
            )
            if i == 0:
                if result.get('artist'):
                    embed.add_field(name="ðŸŽ™ï¸ Artist", value=result['artist'], inline=True)
                
                if source == 'Genius':
                    embed.add_field(
                        name="🔗 Genius",
                        value=f"[Lihat di Genius]({result['url']})",
                        inline=True
                    )
                    if result.get('thumbnail'):
                        embed.set_thumbnail(url=result['thumbnail'])
            
            embed.set_footer(text=f"Omnia Music 🎶 • Lyrics powered by {source}")

            msg = await interaction.followup.send(embed=embed, wait=True)
            # Track for auto-delete when song changes
            player = self.get_player(interaction.guild)
            player.lyrics_messages.append(msg)

    # ─────────────────────── Playlist Helpers ───────────────────────

    def _build_playlist_display_name(self, base_name: str, user: discord.abc.User) -> str:
        """Build stored playlist name with username suffix."""
        base_name = (base_name or "Playlist").strip()
        username = getattr(user, "display_name", None) or user.name
        return f"{base_name} - {username}"

    # ─────────────────────── /playlistcopy ───────────────────────

    @app_commands.command(
        name="playlistcopy",
        description="Copy playlist YouTube dan simpan sebagai playlist server"
    )
    @app_commands.describe(
        url="URL playlist YouTube",
        name="Nama playlist (opsional). Jika kosong pakai nama bawaan."
    )
    async def playlistcopy(self, interaction: discord.Interaction, url: str, name: str | None = None):
        """Copy a YouTube playlist and save it for this server."""
        await interaction.response.defer()

        # Extract playlist info
        try:
            entries, playlist_title = await YTDLSource.get_info(url, loop=self.bot.loop)
        except Exception as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error(f"Gagal mengambil playlist: `{e}`")
            )
            return

        if not entries:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Playlist kosong atau tidak ditemukan.")
            )
            return

        # Determine name
        base_name = name or playlist_title or "Playlist"
        stored_name = self._build_playlist_display_name(base_name, interaction.user)

        # Build track list (max 50)
        tracks_data = []
        for entry in entries[: PlaylistStore.MAX_TRACKS]:
            web_url = entry.get("webpage_url")
            if not web_url:
                if entry.get("url"):
                    if len(entry["url"]) == 11:
                        web_url = f"https://www.youtube.com/watch?v={entry['url']}"
                    else:
                        web_url = entry["url"]
                elif entry.get("id"):
                    web_url = f"https://www.youtube.com/watch?v={entry['id']}"
                else:
                    continue

            tracks_data.append(
                {
                    "title": entry.get("title", "Unknown"),
                    "url": web_url,
                    "duration": entry.get("duration", 0),
                    "thumbnail": entry.get("thumbnail", ""),
                    "uploader": entry.get("uploader", "Unknown"),
                }
            )

        if not tracks_data:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Gagal menyalin data lagu dari playlist.")
            )
            return

        playlist_payload = {
            "name": stored_name,
            "base_name": base_name,
            "owner_id": interaction.user.id,
            "owner_name": getattr(interaction.user, "display_name", None) or interaction.user.name,
            "source_url": url,
            "track_count": len(tracks_data),
            "tracks": tracks_data,
        }

        ok, err = await self.playlists.add_playlist(interaction.guild.id, playlist_payload)
        if not ok and err == "FULL":
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "Daftar playlist untuk server ini sudah penuh (maksimal 100 playlist).\n"
                    "Hapus beberapa playlist terlebih dahulu dengan `/playlistdelete`."
                )
            )
            return

        # Success
        note = ""
        if len(entries) > PlaylistStore.MAX_TRACKS:
            note = (
                f"\nâš ï¸ Playlist asli memiliki {len(entries)} lagu. "
                f"Hanya **{PlaylistStore.MAX_TRACKS}** lagu pertama yang disimpan."
            )

        await self._send_embed(
            interaction,
            EmbedBuilder.success(
                "✅ Playlist Disalin",
                f"Playlist **{stored_name}** berhasil disimpan untuk server ini.\n"
                f"Total lagu tersimpan: **{len(tracks_data)}**.{note}"
            )
        )

    # ─────────────────────── /loop ───────────────────────

    @app_commands.command(name="loop", description="Atur mode loop")
    @app_commands.describe(mode="Mode loop: off, single, atau queue")
    @app_commands.choices(mode=[
        app_commands.Choice(name="🚫 Off", value="off"),
        app_commands.Choice(name="🔂 Single", value="single"),
        app_commands.Choice(name="ðŸ” Queue", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: str):
        """Set loop mode."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)
        player.loop_mode = mode

        icons = {"off": "ðŸš«", "single": "ðŸ”‚", "queue": "ðŸ”"}
        icon = icons.get(mode, "")

        await self._send_embed(
            interaction,
            EmbedBuilder.success(
                f"{icon} Loop Mode",
                f"Loop diatur ke: **{mode}**"
            )
        )

    # ─────────────────────── /autoplay ───────────────────────

    @app_commands.command(name="autoplay", description="Atur mode autoplay")
    @app_commands.describe(mode="Pilih mode autoplay: off, youtube, custom1, atau custom2")
    @app_commands.choices(mode=[
        app_commands.Choice(name="🔄 Off", value="off"),
        app_commands.Choice(name="â–¶ï¸ YouTube", value="youtube"),
        app_commands.Choice(name="1ï¸âƒ£ Custom 1", value="custom1"),
        app_commands.Choice(name="2ï¸âƒ£ Custom 2", value="custom2"),
    ])
    async def autoplay(self, interaction: discord.Interaction, mode: str):
        """Set autoplay mode."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)
        
        if mode == "youtube":
            player.autoplay_mode = AutoplayMode.YOUTUBE
            status = "YouTube â–¶ï¸"
            desc = "Bot akan memutar rekomendasi dasar dari YouTube saat queue kosong."
        elif mode == "custom1":
            player.autoplay_mode = AutoplayMode.CUSTOM
            status = "Custom 1 1ï¸âƒ£"
            desc = "Bot menggunakan smart filtering (Relevan + Eksploratif) saat queue kosong."
        elif mode == "custom2":
            player.autoplay_mode = AutoplayMode.CUSTOM2
            status = "Custom 2 2ï¸âƒ£"
            desc = "Bot menggunakan rekomendasi eksploratif yang prioritasnya mencari artis/genre baru."
        else:
            player.autoplay_mode = AutoplayMode.OFF
            status = "Off 🔄"
            desc = "Autoplay dimatikan."

        # Trigger preload check if enabled
        if player.autoplay_mode != AutoplayMode.OFF:
            await player._trigger_autoplay_preload()

        await self._send_embed(
            interaction,
            EmbedBuilder.success(f"🔄 Autoplay: {status}", desc)
        )

    # ─────────────────────── /status ───────────────────────

    @app_commands.command(name="status", description="Tampilkan status bot musik")
    async def status(self, interaction: discord.Interaction):
        """Show the bot's current status."""
        player = self.get_player(interaction.guild)
        vc = interaction.guild.voice_client

        embed = discord.Embed(
            title="🤖 Status Bot Musik",
            color=discord.Color.from_rgb(138, 43, 226)
        )

        # Connection status
        if vc and vc.is_connected():
            embed.add_field(
                name="🔊 Voice Channel",
                value=vc.channel.name,
                inline=True
            )
            members = [m.display_name for m in vc.channel.members if not m.bot]
            embed.add_field(
                name="👥 Pendengar",
                value=", ".join(members) if members else "Tidak ada",
                inline=True
            )
        else:
            embed.add_field(
                name="🔇 Voice Channel",
                value="Tidak terhubung",
                inline=True
            )

        # Current track
        if player.current:
            title = player.current.title
            if len(title) > 40:
                title = title[:37] + "..."
            embed.add_field(
                name="🎵 Sedang Diputar",
                value=f"**[{title}]({player.current.url})** [{player.current.duration_str}]",
                inline=False
            )
            progress = player.current_progress_bar() if hasattr(player, "current_progress_bar") else None
            if progress:
                embed.add_field(name="â³ Progress", value=progress, inline=False)
        else:
            embed.add_field(name="🎵 Sedang Diputar", value="Tidak ada", inline=False)

        # Queue
        embed.add_field(name="📋 Queue", value=f"{player.queue.size} lagu", inline=True)

        # Loop mode
        loop_icons = {"off": "ðŸš« Off", "single": "ðŸ”‚ Single", "queue": "ðŸ” Queue"}
        embed.add_field(
            name="ðŸ” Loop",
            value=loop_icons.get(player.loop_mode, player.loop_mode),
            inline=True
        )

        # Autoplay — cycle: Off → YouTube → Custom 1 → Custom 2 → Off
        ap_status = "Off 🔄"
        if player.autoplay_mode == AutoplayMode.YOUTUBE:
            ap_status = "YouTube â–¶ï¸"
        elif player.autoplay_mode == AutoplayMode.CUSTOM:
            ap_status = "Custom 1 1ï¸âƒ£"
        elif player.autoplay_mode == AutoplayMode.CUSTOM2:
            ap_status = "Custom 2 2ï¸âƒ£"
            
        embed.add_field(
            name="🔄 Autoplay",
            value=ap_status,
            inline=True
        )

        # Sleep timer
        sleep_remaining = player.sleep_timer_remaining
        if sleep_remaining is not None:
            minutes, seconds = divmod(int(sleep_remaining), 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                sleep_text = f"{hours}j {minutes}m"
            elif minutes:
                sleep_text = f"{minutes}m {seconds:02d}s"
            else:
                sleep_text = f"{seconds}s"
        else:
            sleep_text = "Tidak aktif"

        embed.add_field(
            name="😴 Sleep Timer",
            value=sleep_text,
            inline=True
        )

        embed.set_footer(text="Omnia Music 🎶")
        await self._send_embed(interaction, embed)

    # ─────────────────────── /help ───────────────────────

    @app_commands.command(name="radio", description="Pilih radio live berdasarkan kategori")
    async def radio(self, interaction: discord.Interaction):
        """Open an interactive radio browser."""
        if not await self._ensure_voice(interaction):
            return

        view = RadioCategoryView(self, interaction.guild, interaction.user)
        await interaction.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    @app_commands.command(name="help", description="Tampilkan daftar command bot musik")
    async def help(self, interaction: discord.Interaction):
        """Show all available commands."""
        embed = discord.Embed(
            title="📖 Daftar Command Omnia Music",
            description="Berikut adalah command yang tersedia:",
            color=discord.Color.from_rgb(138, 43, 226)
        )
        embed.add_field(name="/play `<query>`", value="Putar lagu dari YouTube (URL, Playlist, atau pencarian)", inline=False)
        embed.add_field(name="/skip", value="Skip lagu yang sedang diputar", inline=False)
        embed.add_field(name="/seek `<timestamp>`", value="Loncat ke posisi tertentu di lagu saat ini (detik, mm:ss, atau hh:mm:ss)", inline=False)
        embed.add_field(name="/stop", value="Stop pemutaran dan kosongkan queue", inline=False)
        embed.add_field(name="/sleep `<durasi>`", value="Atur timer tidur, misalnya 30m, 1h30m, atau off untuk batal", inline=False)
        embed.add_field(name="/queue", value="Tampilkan antrian lagu", inline=False)
        embed.add_field(name="/move `<from> <to>`", value="Pindahkan lagu di queue", inline=False)
        embed.add_field(name="/nowplaying", value="Tampilkan lagu yang sedang diputar", inline=False)
        embed.add_field(name="/loop `<mode>`", value="Atur mode loop (Off / Single / Queue)", inline=False)
        embed.add_field(name="/autoplay", value="Toggle autoplay rekomendasi otomatis", inline=False)
        embed.add_field(name="/lyrics `[query]`", value="Cari lirik lagu (Lrclib/Genius)", inline=False)
        embed.add_field(name="/status", value="Tampilkan status bot musik", inline=False)
        embed.add_field(name="/playlistcopy `<url> [name]`", value="Salin playlist YouTube dan simpan sebagai playlist server (maks 50 lagu / playlist)", inline=False)
        embed.add_field(name="/playlist", value="Tampilkan daftar playlist server", inline=False)
        embed.add_field(name="/playlistplay", value="Tampilkan daftar playlist server dan pilih dari dropdown untuk diputar / masuk ke queue", inline=False)
        embed.add_field(name="/playlistdelete", value="Hapus playlist yang tersimpan di server", inline=False)
        embed.add_field(name="/radio", value="Pilih radio live berdasarkan kategori genre, mood, news, local, dan lainnya", inline=False)
        embed.add_field(name="/help", value="Tampilkan daftar command ini", inline=False)
        embed.set_footer(text="Omnia Music 🎶")
        await self._send_embed(interaction, embed)

    # ─────────────────────── Voice State Listener ───────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        """Handle voice state updates for auto-disconnect and reconnection."""
        # 1. Handle Bot Reconnection
        if member.id == self.bot.user.id:
            if before.channel is None and after.channel is not None:
                # Bot joined/reconnected
                player = self.get_player(member.guild)
                # If queue has items but not playing, resume
                # NOTE: Disabled play_next here because it conflicts with the initial connection handshake
                # which also triggers this event before vc.is_connected() is True.
                # if player.queue.size > 0 and not player.is_playing and not player.is_paused:
                #      logger.info("Bot reconnected. Resuming queue...")
                #      try:
                #         await player.play_next()
                #      except Exception as e:
                #         logger.error(f"Failed to resume on reconnect: {e}")
            return

        # 2. Auto Disconnect Logic (ignore bots)
        if member.bot:
            return

        # Check if a user LEFT the bot's voice channel
        if before.channel is not None:
            vc = member.guild.voice_client
            if vc and vc.channel == before.channel:
                # Count non-bot members
                human_members = [m for m in before.channel.members if not m.bot]
                if len(human_members) == 0:
                    # Bot is alone — wait a moment then disconnect
                    await asyncio.sleep(10)  # Give 10 seconds grace period

                    # Re-check
                    if vc.is_connected():
                        human_members = [m for m in vc.channel.members if not m.bot]
                        if len(human_members) == 0:
                            player = self.get_player(member.guild)
                            if player.text_channel:
                                embed = EmbedBuilder.info(
                                    "👋 Auto Disconnect",
                                    "Bot keluar karena sendirian di voice channel."
                                )
                                try:
                                    await player.text_channel.send(embed=embed, delete_after=20)
                                except discord.HTTPException:
                                    pass
                            await player.disconnect()
                            self.cleanup_player(member.guild.id)


PAGE_SIZE = 25  # Discord select menu limit


class PlaylistSelectView(discord.ui.View):
    """Interactive select menu for choosing a saved playlist, with pagination."""

    def __init__(self, music_cog: "Music", guild: discord.Guild, user: discord.Member, playlists: list[dict]):
        super().__init__(timeout=60)
        self.music_cog = music_cog
        self.guild = guild
        self.user = user
        self._all_playlists = list(playlists)
        self._current_page = 0
        self._total_pages = max(1, (len(self._all_playlists) + PAGE_SIZE - 1) // PAGE_SIZE)

        self.playlist_select.options = self._build_options()

        prev_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, label="◀ Previous", row=1, custom_id="pl_sel_prev")
        next_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, label="Next ▶", row=1, custom_id="pl_sel_next")
        prev_btn.callback = self._on_prev
        next_btn.callback = self._on_next
        self.add_item(prev_btn)
        self.add_item(next_btn)
        self._prev_btn = prev_btn
        self._next_btn = next_btn
        self._update_nav_buttons()

    def _build_options(self) -> list[discord.SelectOption]:
        start = self._current_page * PAGE_SIZE
        slice_pl = self._all_playlists[start : start + PAGE_SIZE]
        options = []
        for i, pl in enumerate(slice_pl):
            global_idx = start + i
            name = str(pl.get("name", "Untitled"))
            track_count = len(pl.get("tracks") or [])
            label = name if len(name) <= 90 else name[:87] + "..."
            description = f"{track_count} lagu"
            options.append(discord.SelectOption(label=label, value=str(global_idx), description=description))
        return options

    def _update_nav_buttons(self):
        if hasattr(self, "_prev_btn"):
            self._prev_btn.disabled = self._current_page <= 0
        if hasattr(self, "_next_btn"):
            self._next_btn.disabled = self._current_page >= self._total_pages - 1

    def build_embed(self) -> discord.Embed:
        start = self._current_page * PAGE_SIZE
        slice_pl = self._all_playlists[start : start + PAGE_SIZE]
        total = len(self._all_playlists)
        lines = []
        for i, pl in enumerate(slice_pl, start=start + 1):
            name = str(pl.get("name", "Untitled"))
            track_count = len(pl.get("tracks") or [])
            lines.append(f"`{i}.` **{name}** — {track_count} lagu")
        page_note = f"\n\n📄 Halaman **{self._current_page + 1}** / **{self._total_pages}**"
        if total > PAGE_SIZE:
            page_note += f" • Total **{total}** playlist. Gunakan tombol di bawah untuk pindah halaman."
        embed = discord.Embed(
            title="📂 Playlist Server",
            description="\n".join(lines) + page_note,
            color=discord.Color.from_rgb(138, 43, 226),
        )
        embed.set_footer(text="Pilih playlist dari menu di bawah untuk diputar.")
        return embed

    async def _on_prev(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            return
        self._current_page = max(0, self._current_page - 1)
        self.playlist_select.options = self._build_options()
        self._update_nav_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            return
        self._current_page = min(self._total_pages - 1, self._current_page + 1)
        self.playlist_select.options = self._build_options()
        self._update_nav_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="Pilih playlist untuk diputar...",
        min_values=1,
        max_values=1,
        options=[],
        row=0,
    )
    async def playlist_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        """Handle playlist selection."""
        if interaction.guild != self.guild:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Playlist ini tidak berlaku di server lain."),
                ephemeral=True,
            )
            try: await interaction.message.delete()
            except discord.HTTPException: pass
            return

        music: Music = self.music_cog
        if not await music._ensure_voice(interaction):
            try: await interaction.message.delete()
            except discord.HTTPException: pass
            return
        if not await music._ensure_same_channel(interaction):
            try: await interaction.message.delete()
            except discord.HTTPException: pass
            return

        await interaction.response.defer()
        try: await interaction.message.delete()
        except discord.HTTPException: pass

        if not select.values:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Tidak ada playlist yang dipilih."),
                ephemeral=True,
            )
            return

        try:
            global_idx = int(select.values[0])
        except ValueError:
            global_idx = 0

        if not (0 <= global_idx < len(self._all_playlists)):
            await interaction.followup.send(
                embed=EmbedBuilder.error("Playlist yang dipilih tidak valid."),
                ephemeral=True,
            )
            return

        playlist = self._all_playlists[global_idx]
        tracks_data = playlist.get("tracks") or []
        if not tracks_data:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Playlist ini tidak memiliki lagu tersimpan."),
                ephemeral=True,
            )
            return

        player = music.get_player(self.guild)
        player.text_channel = interaction.channel  # type: ignore[assignment]

        try:
            await player.connect(interaction.user.voice.channel)  # type: ignore[union-attr]
        except Exception as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error(f"Gagal join voice channel: `{e}`"),
                ephemeral=True,
            )
            return

        for t in tracks_data:
            track = Track(
                source_url="",
                title=t.get("title", "Unknown"),
                url=t.get("url", ""),
                duration=t.get("duration", 0),
                thumbnail=t.get("thumbnail", ""),
                uploader=t.get("uploader", "Unknown"),
                requester=interaction.user,
            )
            await player.add_track(track)

        if not player.is_playing:
            if player.current and (not player.voice_client or not player.voice_client.is_connected()):
                player.current = None
            await player.ensure_playing()

        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "🎶 Playlist Diputar",
                f"Menambahkan playlist **{playlist.get('name', 'Untitled')}** "
                f"({len(tracks_data)} lagu) ke queue."
            )
        )


class PlaylistDeleteView(discord.ui.View):
    """Interactive select menu for deleting a saved playlist, with pagination."""

    def __init__(self, music_cog: "Music", guild: discord.Guild, playlists: list[dict]):
        super().__init__(timeout=60)
        self.music_cog = music_cog
        self.guild = guild
        self._all_playlists = list(playlists)
        self._current_page = 0
        self._total_pages = max(1, (len(self._all_playlists) + PAGE_SIZE - 1) // PAGE_SIZE)

        self.playlist_select.options = self._build_options()

        prev_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, label="◀ Previous", row=1, custom_id="pl_del_prev")
        next_btn = discord.ui.Button(style=discord.ButtonStyle.secondary, label="Next ▶", row=1, custom_id="pl_del_next")
        prev_btn.callback = self._on_prev
        next_btn.callback = self._on_next
        self.add_item(prev_btn)
        self.add_item(next_btn)
        self._prev_btn = prev_btn
        self._next_btn = next_btn
        self._update_nav_buttons()

    def _build_options(self) -> list[discord.SelectOption]:
        start = self._current_page * PAGE_SIZE
        slice_pl = self._all_playlists[start : start + PAGE_SIZE]
        options = []
        for i, pl in enumerate(slice_pl):
            global_idx = start + i
            name = str(pl.get("name", "Untitled"))
            track_count = len(pl.get("tracks") or [])
            label = name if len(name) <= 90 else name[:87] + "..."
            description = f"{track_count} lagu"
            options.append(discord.SelectOption(label=label, value=str(global_idx), description=description))
        return options

    def _update_nav_buttons(self):
        if hasattr(self, "_prev_btn"):
            self._prev_btn.disabled = self._current_page <= 0
        if hasattr(self, "_next_btn"):
            self._next_btn.disabled = self._current_page >= self._total_pages - 1

    def build_embed(self) -> discord.Embed:
        start = self._current_page * PAGE_SIZE
        slice_pl = self._all_playlists[start : start + PAGE_SIZE]
        total = len(self._all_playlists)
        lines = []
        for i, pl in enumerate(slice_pl, start=start + 1):
            name = str(pl.get("name", "Untitled"))
            track_count = len(pl.get("tracks") or [])
            lines.append(f"`{i}.` **{name}** — {track_count} lagu")
        page_note = f"\n\n📄 Halaman **{self._current_page + 1}** / **{self._total_pages}**"
        if total > PAGE_SIZE:
            page_note += f" • Total **{total}** playlist. Gunakan tombol di bawah untuk pindah halaman."
        embed = discord.Embed(
            title="ðŸ—‘ï¸ Hapus Playlist Server",
            description="\n".join(lines) + page_note,
            color=discord.Color.from_rgb(220, 20, 60),
        )
        embed.set_footer(text="Pilih playlist yang ingin dihapus dari menu di bawah.")
        return embed

    async def _on_prev(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            return
        self._current_page = max(0, self._current_page - 1)
        self.playlist_select.options = self._build_options()
        self._update_nav_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            return
        self._current_page = min(self._total_pages - 1, self._current_page + 1)
        self.playlist_select.options = self._build_options()
        self._update_nav_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.select(
        placeholder="Pilih playlist untuk dihapus...",
        min_values=1,
        max_values=1,
        options=[],
        row=0,
    )
    async def playlist_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        """Handle playlist deletion selection."""
        if interaction.guild != self.guild:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Playlist ini tidak berlaku di server lain."),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        if not select.values:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Tidak ada playlist yang dipilih."),
                ephemeral=True,
            )
            return

        try:
            global_idx = int(select.values[0])
        except ValueError:
            global_idx = 0

        if not (0 <= global_idx < len(self._all_playlists)):
            await interaction.followup.send(
                embed=EmbedBuilder.error("Playlist yang dipilih tidak valid."),
                ephemeral=True,
            )
            return

        playlist = self._all_playlists[global_idx]
        name = str(playlist.get("name", "Untitled"))

        deleted = await self.music_cog.playlists.delete_playlist(self.guild.id, name)
        if not deleted:
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    "Playlist tidak ditemukan atau sudah dihapus.\n"
                    "Coba buka ulang `/playlistdelete` untuk menyegarkan daftar."
                ),
                ephemeral=True,
            )
            return

        for child in self.children:
            if isinstance(child, discord.ui.Select):
                child.disabled = True

        await interaction.followup.send(
            embed=EmbedBuilder.success(
                "ðŸ—‘ï¸ Playlist Dihapus",
                f"Playlist **{name}** telah dihapus dari server ini."
            ),
            ephemeral=True,
        )


class RadioCategoryView(discord.ui.View):
    """First-step radio menu for choosing a station group."""

    def __init__(self, music_cog: "Music", guild: discord.Guild, user: discord.Member):
        super().__init__(timeout=120)
        self.music_cog = music_cog
        self.guild = guild
        self.user = user

        self.category_select = discord.ui.Select(
            placeholder="Pilih kategori radio...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label=cfg["label"],
                    value=key,
                    description=cfg["description"],
                )
                for key, cfg in RADIO_CATEGORY_PRESETS.items()
            ],
            row=0,
        )
        self.category_select.callback = self._on_category_select
        self.add_item(self.category_select)

    def build_embed(self) -> discord.Embed:
        lines = [
            "`Genre` untuk pop, rock, jazz, lo-fi, EDM, dan sejenisnya.",
            "`Mood` untuk channel chill, relax, study, dan focus.",
            "`News / Talk` untuk berita, obrolan, dan program informatif.",
            "`Local` untuk radio dari Indonesia dan negara sekitar.",
            "`Lainnya` untuk oldies, world, instrumental, dan opsi tambahan.",
        ]
        embed = discord.Embed(
            title="📻 Radio",
            description="Pilih kategori dulu, lalu pilih stasiun yang ingin diputar.\n\n" + "\n".join(lines),
            color=discord.Color.from_rgb(138, 43, 226),
        )
        embed.set_footer(text="Omnia Music 🎶")
        return embed

    async def _on_category_select(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Menu radio ini tidak berlaku di server lain."),
                ephemeral=True,
            )
            return

        if not await self.music_cog._ensure_voice(interaction):
            return

        category_key = self.category_select.values[0] if self.category_select.values else ""
        await interaction.response.defer()

        stations = await self.music_cog._load_radio_stations(category_key)
        if not stations:
            await interaction.edit_original_response(
                embed=EmbedBuilder.error(
                    "Tidak ada stasiun radio yang berhasil dimuat untuk kategori ini.\n"
                    "Coba pilih kategori lain."
                ),
                view=self,
            )
            return

        view = RadioStationView(
            music_cog=self.music_cog,
            guild=self.guild,
            user=self.user,
            category_key=category_key,
            stations=stations,
            parent_view=self,
        )
        await interaction.edit_original_response(embed=view.build_embed(), view=view)


class RadioStationView(discord.ui.View):
    """Second-step radio menu for choosing a station to play."""

    def __init__(
        self,
        music_cog: "Music",
        guild: discord.Guild,
        user: discord.Member,
        category_key: str,
        stations: list[dict],
        parent_view: RadioCategoryView,
    ):
        super().__init__(timeout=120)
        self.music_cog = music_cog
        self.guild = guild
        self.user = user
        self.category_key = category_key
        self.parent_view = parent_view
        self._all_stations = list(stations)
        self._current_page = 0
        self._total_pages = max(1, (len(self._all_stations) + RADIO_PAGE_SIZE - 1) // RADIO_PAGE_SIZE)

        self.station_select = discord.ui.Select(
            placeholder="Pilih stasiun radio...",
            min_values=1,
            max_values=1,
            options=self._build_options(),
            row=0,
        )
        self.station_select.callback = self._on_station_select
        self.add_item(self.station_select)

        self.prev_button = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="◀ Previous",
            row=1,
        )
        self.next_button = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Next ▶",
            row=1,
        )
        self.back_button = discord.ui.Button(
            style=discord.ButtonStyle.primary,
            label="Back",
            row=1,
        )
        self.prev_button.callback = self._on_prev
        self.next_button.callback = self._on_next
        self.back_button.callback = self._on_back
        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.add_item(self.back_button)
        self._update_nav_buttons()

    def _category_label(self) -> str:
        return str(RADIO_CATEGORY_PRESETS.get(self.category_key, {}).get("label", self.category_key))

    def _build_options(self) -> list[discord.SelectOption]:
        start = self._current_page * RADIO_PAGE_SIZE
        slice_stations = self._all_stations[start : start + RADIO_PAGE_SIZE]
        options: list[discord.SelectOption] = []
        for i, station in enumerate(slice_stations):
            global_idx = start + i
            label = str(station.get("name", "Unknown Station"))
            if len(label) > 90:
                label = label[:87] + "..."
            description = str(station.get("description", "Radio stream"))
            if len(description) > 100:
                description = description[:97] + "..."
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(global_idx),
                    description=description,
                )
            )
        return options

    def _update_nav_buttons(self):
        self.prev_button.disabled = self._current_page <= 0
        self.next_button.disabled = self._current_page >= self._total_pages - 1

    def build_embed(self) -> discord.Embed:
        start = self._current_page * RADIO_PAGE_SIZE
        slice_stations = self._all_stations[start : start + RADIO_PAGE_SIZE]
        lines = []
        for i, station in enumerate(slice_stations, start=start + 1):
            name = str(station.get("name", "Unknown Station"))
            desc = str(station.get("description", "Radio stream"))
            lines.append(f"`{i}.` **{name}** — {desc}")

        page_note = f"\n\nHalaman **{self._current_page + 1}** / **{self._total_pages}**"
        embed = discord.Embed(
            title=f"📻 Radio • {self._category_label()}",
            description="\n".join(lines) + page_note,
            color=discord.Color.from_rgb(30, 144, 255),
        )
        embed.set_footer(text="Pilih stasiun untuk mulai streaming.")
        return embed

    async def _on_prev(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            return
        self._current_page = max(0, self._current_page - 1)
        self.station_select.options = self._build_options()
        self._update_nav_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            return
        self._current_page = min(self._total_pages - 1, self._current_page + 1)
        self.station_select.options = self._build_options()
        self._update_nav_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_back(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            return
        await interaction.response.edit_message(embed=self.parent_view.build_embed(), view=self.parent_view)

    async def _on_station_select(self, interaction: discord.Interaction):
        if interaction.guild != self.guild:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Menu radio ini tidak berlaku di server lain."),
                ephemeral=True,
            )
            return

        if not await self.music_cog._ensure_voice(interaction):
            return
        if not await self.music_cog._ensure_same_channel(interaction):
            return

        if not self.station_select.values:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Tidak ada stasiun yang dipilih."),
                ephemeral=True,
            )
            return

        try:
            global_idx = int(self.station_select.values[0])
        except ValueError:
            global_idx = -1

        if not (0 <= global_idx < len(self._all_stations)):
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Stasiun yang dipilih tidak valid."),
                ephemeral=True,
            )
            return

        station = self._all_stations[global_idx]
        stream_url = str(station.get("stream_url") or "").strip()
        if not stream_url:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Stream URL stasiun ini tidak tersedia."),
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        player = self.music_cog.get_player(interaction.guild)
        player.text_channel = interaction.channel  # type: ignore[assignment]

        try:
            await player.stop()
            for _ in range(10):
                if not getattr(player, "_stopping", False):
                    break
                await asyncio.sleep(0.1)
            await player.connect(interaction.user.voice.channel)  # type: ignore[union-attr]

            radio_track = Track(
                source_url=stream_url,
                title=str(station.get("name", "Radio Stream")),
                url=str(station.get("homepage") or stream_url),
                duration=0,
                thumbnail=str(station.get("favicon") or ""),
                uploader=str(
                    station.get("country")
                    or station.get("country_code")
                    or station.get("language")
                    or "Radio Browser"
                ),
                requester=interaction.user,
            )
            await player.add_track(radio_track)
            if player.current and (not player.voice_client or not player.voice_client.is_connected()):
                player.current = None
            await player.ensure_playing()
        except Exception as e:
            await interaction.edit_original_response(
                embed=EmbedBuilder.error(f"Gagal memutar stasiun radio: `{e}`"),
                view=self,
            )
            return

        station_name = str(station.get("name", "Radio Stream"))
        station_homepage = str(station.get("homepage") or stream_url)
        await interaction.edit_original_response(
            embed=EmbedBuilder.success(
                "📻 Radio Diputar",
                f"Sedang memutar **[{station_name}]({station_homepage})**.",
            ),
            view=None,
        )


async def setup(bot: commands.Bot):
    """Load the Music cog."""
    await bot.add_cog(Music(bot))
    logger.info("Music cog loaded")
