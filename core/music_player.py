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

logger = logging.getLogger('omnia.player')


class LoopMode:
    OFF = 'off'
    SINGLE = 'single'
    QUEUE = 'queue'


class ShuffleMode:
    OFF = 0
    STANDARD = 1
    ALTERNATIVE = 2


class AutoplayMode:
    OFF = 0
    YOUTUBE = 1
    CUSTOM = 2


class MusicPlayer:
    """Music player instance for a single guild."""

    IDLE_TIMEOUT = 180  # 3 minutes

    def __init__(self, bot: discord.Client, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue = QueueManager()
        self.current: Track | None = None
        self.loop_mode: str = LoopMode.OFF
        self.shuffle_mode: int = ShuffleMode.OFF
        self.autoplay_mode: int = AutoplayMode.OFF
        self.text_channel: discord.TextChannel | None = None
        self.now_playing_message: discord.Message | None = None
        self.lyrics_messages: list[discord.Message] = []  # Track lyrics messages for cleanup
        self._view_factory = None  # Callback to create NowPlayingView
        self._idle_task: asyncio.Task | None = None
        self._preload_task: asyncio.Task | None = None
        self._next_autoplay: Track | None = None
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
        
        # Ensure buttons are removed
        await self._disable_now_playing_buttons()
        
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
            logger.warning("Voice client is disconnected in play_next(). Attempting reconnect...")
            # If we lost connection but still have a channel to connect to
            if self.guild.me.voice and self.guild.me.voice.channel:
                try:
                     # Wait a moment before reconnecting
                     await asyncio.sleep(2)
                     await self.connect(self.guild.me.voice.channel)
                     logger.info("Successfully reconnected to voice channel.")
                     # Proceed as normal after successful reconnect
                     vc = self.voice_client
                     if not vc or not vc.is_connected():
                         logger.error("Reconnect failed. Stopping playback.")
                         return
                except Exception as e:
                     logger.error(f"Failed to auto-reconnect: {e}")
                     return
            else:
                logger.warning("No voice channel found to reconnect to. Stopping playback.")
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

        if next_track:
            # If we are playing from queue, any previous autoplay recommendation is stale
            self._next_autoplay = None

        if next_track is None:
            # Queue empty — try autoplay
            if self.autoplay_mode != AutoplayMode.OFF and self.current:
                # Check pre-fetched autoplay first
                if self._next_autoplay:
                    next_track = self._next_autoplay
                    self._next_autoplay = None  # Consume it
                else:
                    autoplay_track = await self._get_autoplay_track()
                    if autoplay_track:
                        next_track = autoplay_track

            if next_track is None:
                # Nothing to play — notify and start idle timer
                self.current = None
                self._cancel_preload() # Cancel any pending preload
                self._next_autoplay = None
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

        # Wait for any pending pre-load to finish
        if self._preload_task and not self._preload_task.done():
            try:
                # Wait up to 10s for pre-load (it should be faster)
                logger.info("Waiting for pre-load to complete...")
                await asyncio.wait_for(self._preload_task, timeout=10.0)
            except Exception as e:
                logger.warning(f"Waited for pre-load but it failed/timed out: {e}")

        try:
            # Create audio source — reuse source_url if already extracted
            if next_track.source_url:
                logger.info(f"Using pre-loaded URL for: {next_track.title}")
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

            # Trigger pre-loading for the NEXT track
            self._schedule_preload()

        except Exception as e:
            logger.error(f'Error playing track: {e}')
            
            # Detect potential network/socket errors
            error_str = str(e).lower()
            is_network_error = any(err in error_str for err in ['socket', 'connection', 'reset', 'broken pipe', 'timeout'])
            
            if self.text_channel:
                 msg = f"Gagal memutar: **{next_track.title}**\n`{e}`"
                 if is_network_error:
                     msg += "\n*Tampaknya terjadi gangguan jaringan. Mencoba reconnect...*"
                 embed = EmbedBuilder.error(msg)
                 try:
                     await self.text_channel.send(embed=embed)
                 except discord.HTTPException:
                     pass
            
            # Prevent rapid queue draining on network failure
            await asyncio.sleep(5)
            
            if is_network_error:
                 logger.warning("Network error detected. Refunding track to queue and attempting reconnect loop.")
                 # Refund the track so it isn't lost
                 await self.queue.put_front(next_track)
                 self.current = None
                 
                 # Force disconnect to reset state so play_next() auto-reconnects cleanly
                 try:
                      if vc and vc.is_connected():
                           await vc.disconnect(force=True)
                 except Exception:
                      pass
            
            # Try next track (which will trigger reconnect if disconnected, and play the refunded track)
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
        """Delete the current Now Playing message and lyrics messages."""
        # Delete lyrics messages first
        await self._delete_lyrics_messages()
        
        if self.now_playing_message:
            try:
                await self.now_playing_message.delete()
            except (discord.HTTPException, Exception):
                pass
            self.now_playing_message = None

    async def _delete_lyrics_messages(self):
        """Delete all tracked lyrics messages."""
        for msg in self.lyrics_messages:
            try:
                await msg.delete()
            except (discord.HTTPException, Exception):
                pass
        self.lyrics_messages.clear()

    async def stop(self):
        """Stop playback and clear queue."""
        await self.queue.clear()
        self.current = None
        self.loop_mode = LoopMode.OFF
        self.shuffle_mode = ShuffleMode.OFF
        self.current = None
        self.loop_mode = LoopMode.OFF
        self.shuffle_mode = ShuffleMode.OFF
        self._play_history.clear()
        self._next_autoplay = None
        
        # Remove buttons
        await self._disable_now_playing_buttons()
        
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.stop()

    async def set_shuffle(self, mode: int):
        """Set shuffle mode and shuffle queue."""
        self.shuffle_mode = mode
        await self.queue.shuffle(mode)

    async def _get_autoplay_track(self) -> Track | None:
        """Get a recommended track for autoplay."""
        if not self.current or not self.current.url:
            return None

        try:
            logger.info(f'Autoplay: searching related for "{self.current.title}" (Mode: {self.autoplay_mode})')

            query_url = self.current.url
            
            # --- YOUTUBE ---
            # Default logic: Get related videos from YouTube
            
            related = await YTDLSource.get_related(
                query_url,
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

            if self.autoplay_mode == AutoplayMode.CUSTOM:
                # Custom scoring (Explorative + Related) without cover/live penalty
                def score_video(video):
                    score = random.uniform(0, 10) # Explorative randomness
                    title = video.get('title', '').lower()
                    
                    # Boost for related artist
                    current_uploader = self.current.uploader.lower() if self.current.uploader else ""
                    if current_uploader and len(current_uploader) > 2 and current_uploader in title:
                         score += 5
                         
                    # Boost for related words
                    current_words = [w for w in self.current.title.lower().split() if len(w) > 3]
                    match_count = sum(1 for w in current_words if w in title)
                    score += match_count * 2
                    
                    return score

                fresh.sort(key=score_video, reverse=True)
                # Pick randomly from the top 3 scored candidates for an explorative edge
                candidates = fresh[:3]
                chosen = random.choice(candidates)
                logger.info(f'Autoplay (Custom): Top candidates -> {[c.get("title") for c in candidates]}')
            else:
                # Pick a random one from the filtered results (original pure YouTube mode)
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
                # Disable buttons FIRST
                await self._disable_now_playing_buttons()

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

    # ─────────────────────── Preload Logic ───────────────────────

    async def _trigger_autoplay_preload(self):
        """
        Manually trigger preload if autoplay is turned on mid-song.
        Only runs if queue is empty and we are currently playing.
        """
        if self.queue.size == 0 and self.current and self.autoplay_mode != AutoplayMode.OFF:
            logger.info("Autoplay toggled ON: Triggering immediate preload...")
            self._schedule_preload()

    def _schedule_preload(self):
        """Schedule pre-loading of the next track."""
        self._cancel_preload()
        self._preload_task = asyncio.create_task(self._preload_next_track())

    def _cancel_preload(self):
        """Cancel existing preload task."""
        if self._preload_task and not self._preload_task.done():
            self._preload_task.cancel()
            self._preload_task = None

    async def _preload_next_track(self):
        """
        Pre-resolve the URL for the next track in the queue.
        This ensures 'skip' and auto-play are instant.
        """
        try:
            # Wait a bit to let the current playback stabilize
            # Reduced to 1s to ensure it's ready before the song ends (short songs)
            await asyncio.sleep(1)
            
            # Peek at next track
            next_track = await self.queue.peek_next()
            if not next_track:
                # Queue is empty. If autoplay is ON, pre-fetch the recommendation!
                if self.autoplay_mode != AutoplayMode.OFF and self.current and not self._next_autoplay:
                     try:
                        logger.info(f"Pre-loading autoplay for: {self.current.title}")
                        # _get_autoplay_track returns a full Track object with source_url already resolved
                        track = await self._get_autoplay_track()
                        if track:
                            self._next_autoplay = track
                            logger.info(f"Pre-loaded autoplay track: {track.title}")
                     except Exception as e:
                        logger.warning(f"Autoplay pre-load failed: {e}")
                return

            # Clear stale autoplay if queue is not empty (user added song)
            if self._next_autoplay:
                self._next_autoplay = None

            if next_track.source_url:
                # Already resolved
                return

            logger.info(f"Pre-loading next track: {next_track.title}")
            data = await YTDLSource.get_stream_data(next_track.url, loop=self.bot.loop)
            
            if data and data.get('url'):
                next_track.source_url = data['url']
                logger.info(f"Pre-loaded successfully: {next_track.title}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"Pre-load failed: {e}")
