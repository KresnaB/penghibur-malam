"""
MusicPlayer — Per-guild music player state management.
Handles playback, queue processing, idle timeout, and autoplay.
"""

from __future__ import annotations

import asyncio
import logging
import random

import discord

from core.queue_manager import QueueManager
from core.ytdl_source import Track, YTDLSource
from utils.embed_builder import EmbedBuilder

logger = logging.getLogger('antigrafity.player')


class LoopMode:
    OFF = 'off'
    SINGLE = 'single'
    QUEUE = 'queue'


class MusicPlayer:
    """Music player instance for a single guild."""

    IDLE_TIMEOUT = 180  # 3 minutes

    def __init__(self, bot: discord.Client, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue = QueueManager()
        self.current: Track | None = None
        self.loop_mode: str = LoopMode.OFF
        self.autoplay: bool = False
        self.text_channel: discord.TextChannel | None = None
        self.now_playing_message: discord.Message | None = None
        self._view_factory = None  # Callback to create NowPlayingView
        self._idle_task: asyncio.Task | None = None
        self._playing = asyncio.Event()
        self._play_history: list[str] = []  # Track URLs that have been played

    @property
    def voice_client(self) -> discord.VoiceClient | None:
        """Get the current voice client for this guild."""
        return self.guild.voice_client

    @property
    def is_playing(self) -> bool:
        """Check if currently playing audio."""
        vc = self.voice_client
        return vc is not None and (vc.is_playing() or vc.is_paused())

    @property
    def is_paused(self) -> bool:
        """Check if audio is paused."""
        vc = self.voice_client
        return vc is not None and vc.is_paused()

    async def pause(self):
        """Pause playback."""
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.pause()

    async def resume(self):
        """Resume playback."""
        vc = self.voice_client
        if vc and vc.is_paused():
            vc.resume()

    async def connect(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        """Connect to a voice channel."""
        vc = self.voice_client
        if vc:
            if vc.channel.id != channel.id:
                await vc.move_to(channel)
            return vc
        return await channel.connect(self_deaf=True)

    async def disconnect(self):
        """Disconnect from voice and cleanup."""
        self._cancel_idle_timer()
        vc = self.voice_client
        if vc and vc.is_connected():
            if vc.is_playing():
                vc.stop()
            await vc.disconnect()
        self.current = None
        await self.queue.clear()

    async def add_track(self, track: Track) -> int:
        """Add a track to the queue. Returns position."""
        position = await self.queue.add(track)
        return position

    async def play_next(self):
        """Play the next track in the queue."""
        self._cancel_idle_timer()

        vc = self.voice_client
        if not vc or not vc.is_connected():
            return

        # Handle loop modes
        if self.current and self.loop_mode == LoopMode.SINGLE:
            # Re-queue the same track at the front
            await self.queue.put_front(self.current)
        elif self.current and self.loop_mode == LoopMode.QUEUE:
            # Re-queue at the back
            await self.queue.put_back(self.current)

        # Get next track
        next_track = await self.queue.get_next()

        if next_track is None:
            # Queue empty — try autoplay
            if self.autoplay and self.current:
                autoplay_track = await self._get_autoplay_track()
                if autoplay_track:
                    next_track = autoplay_track

            if next_track is None:
                # Nothing to play — notify and start idle timer
                self.current = None
                self._start_idle_timer()

                # Disable buttons on old Now Playing message
                await self._disable_now_playing_buttons()

                # Send queue empty notification
                if self.text_channel:
                    embed = EmbedBuilder.info(
                        "⏹️ Pemutaran Selesai",
                        "Queue kosong, tidak ada lagu selanjutnya.\nGunakan `/play` untuk memutar lagu baru."
                    )
                    try:
                        await self.text_channel.send(embed=embed)
                    except discord.HTTPException:
                        pass
                return

        self.current = next_track
        # Track play history for autoplay deduplication
        if next_track.url:
            self._play_history.append(next_track.url)
            # Keep history capped at 50
            if len(self._play_history) > 50:
                self._play_history = self._play_history[-50:]

        try:
            # Create audio source — reuse source_url if already extracted
            if next_track.source_url:
                source = discord.FFmpegPCMAudio(
                    next_track.source_url,
                    before_options='-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                    options='-vn'
                )
                source = discord.PCMVolumeTransformer(source, volume=0.5)
            else:
                source, _ = await YTDLSource.from_url(
                    next_track.url, loop=self.bot.loop
                )

            def after_play(error):
                if error:
                    logger.error(f'Player error: {error}')
                # Schedule next track
                asyncio.run_coroutine_threadsafe(
                    self.play_next(), self.bot.loop
                )

            # Stop if somehow already playing
            if vc.is_playing():
                vc.stop()
                await asyncio.sleep(0.5)

            vc.play(source, after=after_play)

        except Exception as e:
            logger.error(f'Error playing track: {e}')
            if self.text_channel:
                embed = EmbedBuilder.error(f"Gagal memutar: **{next_track.title}**\n`{e}`")
                try:
                    await self.text_channel.send(embed=embed)
                except discord.HTTPException:
                    pass
            # Try next track
            await self.play_next()
            return

        # Send embed OUTSIDE the try block — embed errors won't trigger play_next
        try:
            await self._disable_now_playing_buttons()
            if self.text_channel:
                embed = EmbedBuilder.now_playing(next_track)
                view = None
                if self._view_factory:
                    view = self._view_factory(self)
                self.now_playing_message = await self.text_channel.send(
                    embed=embed, view=view
                )
        except Exception as e:
            logger.warning(f'Error sending now playing embed: {e}')

    async def skip(self):
        """Skip the current track."""
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            # Temporarily disable single loop for skip
            old_loop = self.loop_mode
            if self.loop_mode == LoopMode.SINGLE:
                self.loop_mode = LoopMode.OFF
            vc.stop()  # This triggers after_play → play_next
            # Restore loop mode after a brief delay
            if old_loop == LoopMode.SINGLE:
                await asyncio.sleep(0.5)
                self.loop_mode = old_loop

    async def _disable_now_playing_buttons(self):
        """Delete the current Now Playing message."""
        if self.now_playing_message:
            try:
                await self.now_playing_message.delete()
            except (discord.HTTPException, Exception):
                pass
            self.now_playing_message = None

    async def stop(self):
        """Stop playback and clear queue."""
        await self.queue.clear()
        self.current = None
        self.loop_mode = LoopMode.OFF
        self._play_history.clear()
        
        # Remove buttons
        await self._disable_now_playing_buttons()
        
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.stop()

    async def _get_autoplay_track(self) -> Track | None:
        """Get a recommended track for autoplay."""
        if not self.current or not self.current.url:
            return None

        try:
            logger.info(f'Autoplay: searching related for "{self.current.title}"')

            related = await YTDLSource.get_related(
                self.current.url,
                title=self.current.title,
                loop=self.bot.loop
            )

            if not related:
                logger.warning('Autoplay: no related tracks found')
                return None

            # Filter out songs that have already been played
            fresh = [
                r for r in related
                if (r['url'] if isinstance(r, dict) else r) not in self._play_history
            ]

            if not fresh:
                logger.info('Autoplay: all related tracks already played, using full list')
                fresh = related  # Fallback if everything was played

            # Pick a random one from the filtered results
            chosen = random.choice(fresh)
            chosen_url = chosen['url'] if isinstance(chosen, dict) else chosen

            logger.info(f'Autoplay: chose "{chosen.get("title", chosen_url) if isinstance(chosen, dict) else chosen_url}"')

            # Extract full info for playback
            _, data = await YTDLSource.from_url(chosen_url, loop=self.bot.loop)

            track = Track(
                source_url=data.get('url', ''),
                title=data.get('title', 'Unknown'),
                url=data.get('webpage_url', chosen_url),
                duration=data.get('duration', 0),
                thumbnail=data.get('thumbnail', ''),
                uploader=data.get('uploader', 'Unknown'),
                requester=self.bot.user  # Autoplay = requested by bot
            )

            return track

        except Exception as e:
            logger.error(f'Autoplay error: {e}')
            return None

    def _start_idle_timer(self):
        """Start idle disconnect timer."""
        self._cancel_idle_timer()
        self._idle_task = asyncio.create_task(self._idle_disconnect())

    def _cancel_idle_timer(self):
        """Cancel idle disconnect timer."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_disconnect(self):
        """Disconnect after idle timeout."""
        try:
            await asyncio.sleep(self.IDLE_TIMEOUT)
            if not self.is_playing and self.voice_client:
                if self.text_channel:
                    embed = EmbedBuilder.info(
                        "⏹️ Auto Disconnect",
                        f"Bot keluar karena idle selama {self.IDLE_TIMEOUT // 60} menit."
                    )
                    try:
                        await self.text_channel.send(embed=embed)
                    except discord.HTTPException:
                        pass
                await self.disconnect()
        except asyncio.CancelledError:
            pass
