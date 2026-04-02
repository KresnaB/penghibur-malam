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
    CUSTOM2 = 3


class MusicPlayer:
    """Music player instance for a single guild."""

    IDLE_TIMEOUT = 180  # 3 minutes
    CHAT_CLEANUP_DELAY = 20
    GAPLESS_WAIT_TIMEOUT = 2.0
    PLAYBACK_RETRY_LIMIT = 2
    FADE_IN_SECONDS = 0.35
    FADE_OUT_SECONDS = 0.8

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
        self._now_playing_view = None
        self.lyrics_messages: list[discord.Message] = []  # Track lyrics messages for cleanup
        self._view_factory = None  # Callback to create NowPlayingView
        self._idle_task: asyncio.Task | None = None
        self._preload_task: asyncio.Task | None = None
        self._next_autoplay: Track | None = None
        self._playing = asyncio.Event()
        self._play_history: list[str] = []  # Track URLs that have been played
        self._seeking = False  # True while replacing source for seek (ignore after_play from old source)
        self._stopping = False  # True while a manual stop is draining the current source
        self._sleep_task: asyncio.Task | None = None
        self._sleep_until: float | None = None
        self._sleep_label: str | None = None
        self._playback_attempts: dict[str, int] = {}
        self._track_started_at: float | None = None
        self._track_paused_elapsed: float | None = None
        self._progress_task: asyncio.Task | None = None
        self._active_source: discord.AudioSource | None = None

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

    @property
    def sleep_timer_remaining(self) -> float | None:
        """Return remaining sleep timer seconds, if any."""
        if self._sleep_until is None:
            return None
        remaining = self._sleep_until - asyncio.get_event_loop().time()
        return max(0.0, remaining)

    @property
    def current_elapsed_seconds(self) -> float:
        """Return the elapsed playback time for the active track."""
        if self._track_paused_elapsed is not None:
            return max(0.0, self._track_paused_elapsed)
        if self._track_started_at is None:
            return 0.0
        return max(0.0, asyncio.get_event_loop().time() - self._track_started_at)

    @property
    def current_progress_ratio(self) -> float | None:
        """Return progress ratio for the current track if duration is known."""
        if not self.current or not self.current.duration:
            return None
        return min(1.0, self.current_elapsed_seconds / max(self.current.duration, 1))

    @property
    def current_progress_text(self) -> str | None:
        """Return a formatted progress label for the active track."""
        if not self.current:
            return None

        elapsed = int(self.current_elapsed_seconds)
        if not self.current.duration:
            return f"Live • {self._format_timestamp(elapsed)}"

        total = int(self.current.duration)
        return f"{self._format_timestamp(elapsed)} / {self._format_timestamp(total)}"

    def current_progress_bar(self, width: int = 14) -> str | None:
        """Return a compact visual progress bar for the active track."""
        if not self.current:
            return None

        if not self.current.duration:
            return "● Live stream"

        ratio = self.current_progress_ratio or 0.0
        filled = min(width, max(0, int(round(width * ratio))))
        bar = "█" * filled + "░" * (width - filled)
        return f"`{bar}` {self.current_progress_text}"

    async def pause(self):
        """Pause playback."""
        vc = self.voice_client
        if vc and vc.is_playing():
            self._track_paused_elapsed = self.current_elapsed_seconds
            vc.pause()

    async def resume(self):
        """Resume playback."""
        vc = self.voice_client
        if vc and vc.is_paused():
            if self._track_paused_elapsed is not None:
                self._track_started_at = asyncio.get_event_loop().time() - self._track_paused_elapsed
                self._track_paused_elapsed = None
            vc.resume()

    async def seek(self, position: int) -> bool:
        """
        Seek to a specific position (in seconds) in the current track.
        Returns True if seek was started, False otherwise.
        """
        vc = self.voice_client
        if not vc or not self.current:
            return False

        if position < 0:
            position = 0

        # Clamp to track duration if known
        if self.current.duration and position >= self.current.duration:
            # Allow seeking near the end but not past it
            position = max(self.current.duration - 3, 0)

        # Ensure we have a direct stream URL to feed into ffmpeg
        source_url = getattr(self.current, "source_url", None)
        if not source_url:
            try:
                data = await YTDLSource.get_stream_data(self.current.url, loop=self.bot.loop)
                if not data or not data.get("url"):
                    return False
                source_url = data["url"]
                self.current.source_url = source_url
            except Exception as e:
                logger.error(f"Seek: failed to resolve stream URL: {e}")
                return False

        # Prepare new source starting from the requested position
        ffmpeg_before = (
            f"-ss {int(position)} "
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
        )

        def after_play(error):
            if error:
                logger.error(f"Player error after seek: {error}")
            asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

        try:
            if vc.is_playing() or vc.is_paused():
                self._seeking = True
                self._cleanup_active_source()
                vc.stop()
                await asyncio.sleep(0.3)

            source = discord.FFmpegPCMAudio(
                source_url,
                before_options=ffmpeg_before,
                options="-vn",
            )
            source = discord.PCMVolumeTransformer(source, volume=0.5)
            self._track_started_at = asyncio.get_event_loop().time() - position
            self._track_paused_elapsed = None
            self._active_source = source
            vc.play(source, after=after_play)
            return True
        except Exception as e:
            logger.error(f"Seek: error while starting playback at {position}s: {e}")
            return False

    async def connect(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        """Connect to a voice channel."""
        vc = self.voice_client
        if vc:
            if not vc.is_connected():
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
                return await channel.connect(self_deaf=True)
            if vc.channel.id != channel.id:
                await vc.move_to(channel)
            return vc
        return await channel.connect(self_deaf=True)

    async def disconnect(self):
        """Disconnect from voice and cleanup."""
        self._cancel_idle_timer()
        await self.cancel_sleep_timer()
        self._cancel_progress_updater()
        if self._now_playing_view:
            try:
                self._now_playing_view.stop()
            except Exception:
                pass
            self._now_playing_view = None
        
        # Ensure buttons are removed
        await self._disable_now_playing_buttons()
        
        vc = self.voice_client
        if vc and vc.is_connected():
            if vc.is_playing() or vc.is_paused():
                self._cleanup_active_source()
                vc.stop()
            await vc.disconnect()
        self.current = None
        self._track_started_at = None
        self._track_paused_elapsed = None
        self._cleanup_active_source()
        await self.queue.clear()
        cleanup_callback = getattr(self, "_cleanup_callback", None)
        if callable(cleanup_callback):
            try:
                cleanup_callback(self.guild.id)
            except Exception:
                pass

    async def cancel_sleep_timer(self):
        """Cancel any scheduled sleep timer."""
        self._sleep_until = None
        self._sleep_label = None
        current_task = asyncio.current_task()
        if self._sleep_task and not self._sleep_task.done() and self._sleep_task is not current_task:
            self._sleep_task.cancel()
            try:
                await self._sleep_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._sleep_task = None

    def _cancel_progress_updater(self):
        """Stop the periodic now playing progress updater."""
        if self._progress_task:
            if not self._progress_task.done():
                self._progress_task.cancel()
            # Drop the reference either way so completed tasks can be collected.
            self._progress_task = None

    def _start_progress_updater(self):
        """Start the periodic progress updater for the now playing message."""
        self._cancel_progress_updater()
        if self.current and self.now_playing_message:
            self._progress_task = asyncio.create_task(self._progress_update_loop())

    def _get_now_playing_view(self):
        """Return the active now playing view, creating it if needed."""
        if self._now_playing_view is None and self._view_factory:
            self._now_playing_view = self._view_factory(self)
        return self._now_playing_view

    async def _progress_update_loop(self):
        """Periodically refresh the now playing embed with live progress."""
        try:
            while self.current and self.now_playing_message and self.voice_client and self.voice_client.is_connected():
                await asyncio.sleep(15)
                if not self.current or not self.now_playing_message:
                    return
                try:
                    embed = self._build_now_playing_embed()
                    view = self._get_now_playing_view()
                    if view and hasattr(view, "_update_buttons"):
                        view._update_buttons()
                    await self.now_playing_message.edit(embed=embed, view=view)
                except (discord.HTTPException, discord.NotFound):
                    return
                except Exception as e:
                    logger.debug(f"Progress updater failed: {e}")
                    return
        except asyncio.CancelledError:
            pass

    async def set_sleep_timer(self, delay_seconds: int, *, label: str | None = None):
        """Set a sleep timer that disconnects the bot later."""
        delay_seconds = max(1, int(delay_seconds))
        await self.cancel_sleep_timer()
        self._sleep_until = asyncio.get_event_loop().time() + delay_seconds
        self._sleep_label = label
        self._sleep_task = asyncio.create_task(self._sleep_disconnect_after(delay_seconds))

    async def _sleep_disconnect_after(self, delay_seconds: int):
        """Worker for the sleep timer."""
        try:
            await asyncio.sleep(delay_seconds)
            if not self.voice_client or not self.voice_client.is_connected():
                return

            if self.text_channel:
                message = "Timer tidur selesai."
                if self._sleep_label:
                    message = f"{self._sleep_label}. {message}"
                embed = EmbedBuilder.info("😴 Sleep Timer", message)
                try:
                    await self.text_channel.send(embed=embed, delete_after=self.CHAT_CLEANUP_DELAY)
                except discord.HTTPException:
                    pass

            await self.stop()
            await self.disconnect()
        except asyncio.CancelledError:
            pass

    async def add_track(self, track: Track) -> int:
        """Add a track to the queue. Returns position."""
        position = await self.queue.add(track)
        return position

    async def prune_queue(self) -> list[Track]:
        """Remove tracks that are clearly invalid or unplayable."""
        removed = await self.queue.prune(
            lambda track: bool(
                track
                and getattr(track, "title", "").strip()
                and (getattr(track, "url", "").strip() or getattr(track, "source_url", "").strip())
            )
        )

        if removed and self.text_channel:
            names = ", ".join(f"**{track.title}**" for track in removed[:3])
            more = "" if len(removed) <= 3 else f" (+{len(removed) - 3} lainnya)"
            embed = EmbedBuilder.info(
                "🧹 Queue Pruned",
                f"Track invalid dihapus otomatis: {names}{more}"
            )
            try:
                await self.text_channel.send(embed=embed, delete_after=self.CHAT_CLEANUP_DELAY)
            except discord.HTTPException:
                pass

        return removed

    def _set_track_start(self, offset_seconds: float = 0.0):
        """Remember when the current track started playing."""
        self._track_started_at = asyncio.get_event_loop().time() - max(0.0, offset_seconds)
        self._track_paused_elapsed = None

    def _reset_track_progress(self):
        """Clear playback progress tracking."""
        self._track_started_at = None
        self._track_paused_elapsed = None

    def _build_now_playing_embed(self) -> discord.Embed | None:
        """Build the now playing embed with current progress."""
        if not self.current:
            return None
        return EmbedBuilder.now_playing(self.current, progress=self.current_progress_bar())

    @staticmethod
    def _format_timestamp(total_seconds: int | float) -> str:
        """Format seconds as H:MM:SS or M:SS."""
        total = max(0, int(total_seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    async def play_next(self):
        """Play the next track in the queue."""
        # If we're in the middle of a seek, the old source's after_play fired — ignore it
        if getattr(self, '_seeking', False):
            self._seeking = False
            return

        # Manual stop should not behave like a natural track end.
        if getattr(self, '_stopping', False):
            self._stopping = False
            self._cancel_idle_timer()
            self._cancel_preload()
            self._next_autoplay = None
            return

        self._cancel_idle_timer()
        await self.prune_queue()

        vc = self.voice_client
        if not vc or not vc.is_connected():
            logger.warning("Voice client is disconnected in play_next(). Attempting reconnect...")
            # If we lost connection but still have a channel to connect to
            voice_state = self.guild.me.voice
            target_channel = voice_state.channel if voice_state else None

            if target_channel:
                try:
                     # Wait a moment before reconnecting
                     await asyncio.sleep(2)
                     await self.connect(target_channel)
                     logger.info("Successfully reconnected to voice channel.")
                     # Proceed as normal after successful reconnect
                     vc = self.voice_client
                     if not vc or not vc.is_connected():
                         logger.error("Reconnect failed. Stopping playback.")
                         self.current = None
                         self._reset_track_progress()
                         self._cancel_progress_updater()
                         self._cancel_preload()
                         self._next_autoplay = None
                         self._start_idle_timer()
                         return
                except Exception as e:
                     logger.error(f"Failed to auto-reconnect: {e}")
                     self.current = None
                     self._reset_track_progress()
                     self._cancel_progress_updater()
                     self._cancel_preload()
                     self._next_autoplay = None
                     self._start_idle_timer()
                     return
            else:
                logger.warning("No voice channel found to reconnect to. Stopping playback.")
                self.current = None
                self._reset_track_progress()
                self._cancel_progress_updater()
                self._cancel_preload()
                self._next_autoplay = None
                self._start_idle_timer()
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
                self._reset_track_progress()
                self._cancel_preload() # Cancel any pending preload
                self._cancel_progress_updater()
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
                        await self.text_channel.send(embed=embed, delete_after=self.CHAT_CLEANUP_DELAY)
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
                # Keep the wait short so the next track starts with minimal gap.
                logger.info("Waiting for pre-load to complete...")
                await asyncio.wait_for(self._preload_task, timeout=self.GAPLESS_WAIT_TIMEOUT)
            except Exception as e:
                logger.warning(f"Waited for pre-load but it failed/timed out: {e}")

        try:
            # Create audio source — reuse source_url if already extracted
            if next_track.source_url:
                logger.info(f"Using pre-loaded URL for: {next_track.title}")
                source = discord.FFmpegPCMAudio(
                    next_track.source_url,
                    **self._build_ffmpeg_options(next_track)
                )
                source = discord.PCMVolumeTransformer(source, volume=0.5)
            else:
                source, _ = await YTDLSource.from_url(
                    next_track.url,
                    loop=self.bot.loop,
                    title_hint=next_track.title,
                    uploader_hint=next_track.uploader,
                    ffmpeg_options=self._build_ffmpeg_options(next_track),
                )

            def after_play(error):
                if error:
                    logger.error(f'Player error: {error}')
                    asyncio.run_coroutine_threadsafe(
                        self._recover_from_playback_error(next_track, error),
                        self.bot.loop,
                    )
                    return
                asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

            # Stop if somehow already playing
            if vc.is_playing() or vc.is_paused():
                self._cleanup_active_source()
                vc.stop()
                await asyncio.sleep(0.5)

            self._active_source = source
            vc.play(source, after=after_play)
            self._playback_attempts.pop(self._track_key(next_track), None)
            self._set_track_start(0)

            # Trigger pre-loading for the NEXT track
            self._schedule_preload()

        except Exception as e:
            logger.error(f'Error playing track: {e}')
            if self.text_channel:
                message = f"Gagal memutar: **{next_track.title}**\n`{e}`"
                if self._is_temporary_playback_error(e):
                    message += "\n*Tampaknya ada gangguan stream. Bot akan mencoba lagi.*"
                embed = EmbedBuilder.error(message)
                try:
                    await self.text_channel.send(embed=embed, delete_after=self.CHAT_CLEANUP_DELAY)
                except discord.HTTPException:
                    pass

            key = self._track_key(next_track)
            attempts = self._playback_attempts.get(key, 0)
            if self._is_temporary_playback_error(e) and attempts < self.PLAYBACK_RETRY_LIMIT:
                self._playback_attempts[key] = attempts + 1
                await self.queue.put_front(next_track)
                self.current = None
                try:
                    if vc and vc.is_connected():
                        await vc.disconnect(force=True)
                except Exception:
                    pass
                await asyncio.sleep(2 ** attempts)

            # Try next track. If the same track was refunded, it will be retried first.
            await self.play_next()
            return

        # Send embed OUTSIDE the try block — embed errors won't trigger play_next
        try:
            await self._disable_now_playing_buttons()
            if self.text_channel:
                embed = self._build_now_playing_embed()
                view = self._get_now_playing_view()
                if embed:
                    self.now_playing_message = await self.text_channel.send(
                        embed=embed, view=view
                    )
                    self._start_progress_updater()
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
        self._cancel_progress_updater()
        if self._now_playing_view:
            try:
                self._now_playing_view.stop()
            except Exception:
                pass
            self._now_playing_view = None

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
        self._reset_track_progress()
        self.loop_mode = LoopMode.OFF
        self.shuffle_mode = ShuffleMode.OFF
        self.current = None
        self.loop_mode = LoopMode.OFF
        self.shuffle_mode = ShuffleMode.OFF
        self._play_history.clear()
        self._next_autoplay = None
        self._reset_track_progress()
        await self.cancel_sleep_timer()
        self._cancel_progress_updater()
        
        # Remove buttons
        await self._disable_now_playing_buttons()
        
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            self._stopping = True
            self._cleanup_active_source()
            vc.stop()
            await asyncio.sleep(0)
            self._cleanup_active_source()

    def _track_key(self, track: Track | None) -> str:
        """Build a stable key for retry bookkeeping."""
        if not track:
            return ""
        return track.url or track.source_url or track.title

    def _build_ffmpeg_options(self, track: Track) -> dict[str, str]:
        """Build ffmpeg options with gentle fades for smoother transitions."""
        filters = [f"afade=t=in:st=0:d={self.FADE_IN_SECONDS}"]
        if track.duration and track.duration > int(self.FADE_OUT_SECONDS) + 1:
            fade_start = max(track.duration - self.FADE_OUT_SECONDS, 0)
            filters.append(f"afade=t=out:st={fade_start}:d={self.FADE_OUT_SECONDS}")
        return {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn -af " + ",".join(filters),
        }

    def _is_temporary_playback_error(self, error: Exception | str) -> bool:
        """Classify playback failures that should be retried."""
        message = str(error).lower()
        tokens = (
            "socket",
            "connection",
            "reset",
            "broken pipe",
            "timeout",
            "timed out",
            "503",
            "502",
            "500",
            "403",
            "remote end closed",
            "ffmpeg",
            "http error",
        )
        return any(token in message for token in tokens)

    async def _recover_from_playback_error(self, track: Track, error: Exception | str):
        """Retry the current track after a temporary failure."""
        key = self._track_key(track)
        attempts = self._playback_attempts.get(key, 0)

        if attempts >= self.PLAYBACK_RETRY_LIMIT:
            logger.warning(f"Playback retries exhausted for {track.title}")
            self._playback_attempts.pop(key, None)
            self.current = None
            await self.play_next()
            return

        self._playback_attempts[key] = attempts + 1

        if self.text_channel:
            if self._is_temporary_playback_error(error):
                body = f"{track.title}\nStream error terdeteksi. Mencoba ulang..."
            else:
                body = f"{track.title}\nPlayback gagal. Mencoba pemulihan..."
            embed = EmbedBuilder.info("🔄 Playback Recovery", body)
            try:
                await self.text_channel.send(embed=embed, delete_after=self.CHAT_CLEANUP_DELAY)
            except discord.HTTPException:
                pass

        await asyncio.sleep(2 ** attempts)

        await self.queue.put_front(track)
        self.current = None

        vc = self.voice_client
        if vc and vc.is_connected():
            try:
                self._cleanup_active_source()
                await vc.disconnect(force=True)
            except Exception:
                pass

        await self.play_next()

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

            if self.autoplay_mode in (AutoplayMode.CUSTOM, AutoplayMode.CUSTOM2):
                # Custom scoring (Explorative + Related) without cover/live penalty
                def score_video(video):
                    score = random.uniform(0, 10) # Explorative randomness
                    title = video.get('title', '').lower()
                    
                    # Boost for related artist
                    current_uploader = self.current.uploader.lower() if self.current.uploader else ""
                    if current_uploader and len(current_uploader) > 2 and current_uploader in title:
                         score += 5
                         
                    # Boost/Penalty for related words
                    current_words = [w for w in self.current.title.lower().split() if len(w) > 3]
                    match_count = sum(1 for w in current_words if w in title)
                    if self.autoplay_mode == AutoplayMode.CUSTOM2:
                        score -= match_count * 2  # Explorative: penalize exact matches
                    else:
                        score += match_count * 2
                    
                    return score

                fresh.sort(key=score_video, reverse=True)
                # Pick randomly from the top candidates
                num_candidates = 10 if self.autoplay_mode == AutoplayMode.CUSTOM2 else 3
                candidates = fresh[:num_candidates]
                chosen = random.choice(candidates)
                mode_name = "Custom 2" if self.autoplay_mode == AutoplayMode.CUSTOM2 else "Custom"
                logger.info(f'Autoplay ({mode_name}): Top candidates -> {[c.get("title") for c in candidates]}')
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
        if self._idle_task:
            if not self._idle_task.done():
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
                        await self.text_channel.send(embed=embed, delete_after=self.CHAT_CLEANUP_DELAY)
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
        if self._preload_task:
            if not self._preload_task.done():
                self._preload_task.cancel()
            self._preload_task = None

    def _cleanup_active_source(self):
        """Best-effort cleanup for the current FFmpeg-backed audio source."""
        source = self._active_source
        self._active_source = None
        if source is None:
            return
        cleanup = getattr(source, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                pass

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
