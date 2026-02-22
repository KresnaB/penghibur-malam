"""
NowPlayingView — Interactive button controls for the Now Playing embed.
Buttons: Pause/Resume, Skip, Loop, Queue, Autoplay
"""

import discord
from discord import ui

from utils.embed_builder import EmbedBuilder
from utils.embed_builder import EmbedBuilder
from utils.embed_builder import EmbedBuilder
from utils.genius_lyrics import split_lyrics # Keep split_lyrics
from utils.lyrics_service import get_lyrics_concurrently


class NowPlayingView(ui.View):
    """Interactive buttons attached to the Now Playing embed."""

    def __init__(self, player):
        super().__init__(timeout=None)  # Buttons stay active
        self.player = player
        self._update_buttons()

    def _update_buttons(self):
        """Update button styles/labels based on player state."""
        # Pause/Resume button
        if self.player.is_paused:
            self.btn_pause.emoji = "▶️"
            self.btn_pause.label = ""
            self.btn_pause.style = discord.ButtonStyle.success
        else:
            self.btn_pause.emoji = "⏸️"
            self.btn_pause.label = ""
            self.btn_pause.style = discord.ButtonStyle.secondary

        # Loop button
        from core.music_player import LoopMode
        loop_styles = {
            LoopMode.OFF: ("🔁", "", discord.ButtonStyle.secondary),
            LoopMode.SINGLE: ("🔂", "", discord.ButtonStyle.primary),
            LoopMode.QUEUE: ("🔁", "", discord.ButtonStyle.primary),
        }
        emoji, label, style = loop_styles.get(
            self.player.loop_mode,
            ("🔁", "", discord.ButtonStyle.secondary)
        )
        self.btn_loop.emoji = emoji
        self.btn_loop.label = label
        self.btn_loop.style = style

        # Autoplay button
        from core.music_player import AutoplayMode
        self.btn_autoplay.label = ""
        if self.player.autoplay_mode == AutoplayMode.YOUTUBE:
            self.btn_autoplay.emoji = "🔴"
            self.btn_autoplay.style = discord.ButtonStyle.success
        elif self.player.autoplay_mode == AutoplayMode.CUSTOM:
            self.btn_autoplay.emoji = "🟣"
            self.btn_autoplay.style = discord.ButtonStyle.primary
        elif self.player.autoplay_mode == AutoplayMode.CUSTOM2:
            self.btn_autoplay.emoji = "🟠"
            self.btn_autoplay.style = discord.ButtonStyle.danger
        else:
            self.btn_autoplay.emoji = "⚪"
            self.btn_autoplay.style = discord.ButtonStyle.secondary

        # Shuffle button
        from core.music_player import ShuffleMode
        if self.player.queue.size == 0:
            self.btn_shuffle.disabled = True
            self.btn_shuffle.style = discord.ButtonStyle.secondary
            self.btn_shuffle.label = ""
        else:
            self.btn_shuffle.disabled = False
            if self.player.shuffle_mode == ShuffleMode.OFF:
                self.btn_shuffle.style = discord.ButtonStyle.secondary
                self.btn_shuffle.label = ""
            elif self.player.shuffle_mode == ShuffleMode.STANDARD:
                self.btn_shuffle.style = discord.ButtonStyle.success
                self.btn_shuffle.label = ""
            elif self.player.shuffle_mode == ShuffleMode.ALTERNATIVE:
                self.btn_shuffle.style = discord.ButtonStyle.primary
                self.btn_shuffle.label = ""

    async def _update_message(self, interaction: discord.Interaction):
        """Update the embed and buttons after a button press."""
        self._update_buttons()
        if self.player.current:
            embed = EmbedBuilder.now_playing(self.player.current)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

    # ─────────── Pause/Resume ───────────

    @ui.button(emoji="⏸️", label="", style=discord.ButtonStyle.secondary, row=0)
    async def btn_pause(self, interaction: discord.Interaction, button: ui.Button):
        """Toggle pause/resume."""
        if self.player.is_paused:
            await self.player.resume()
        else:
            await self.player.pause()
        await self._update_message(interaction)

    # ─────────── Skip ───────────

    @ui.button(emoji="⏭️", label="", style=discord.ButtonStyle.primary, row=0)
    async def btn_skip(self, interaction: discord.Interaction, button: ui.Button):
        """Skip current track."""
        try:
            # Defer immediately to avoid timeout
            await interaction.response.defer(ephemeral=True)
            
            if self.player.current:
                await interaction.followup.send(
                    embed=EmbedBuilder.success(
                        "⏭️ Skipped",
                        f"**{self.player.current.title}**"
                    ),
                    ephemeral=True
                )
                await self.player.skip()
            else:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Tidak ada lagu yang sedang diputar!"),
                    ephemeral=True
                )
        except discord.NotFound:
            pass  # Interaction died, just ignore
        except Exception as e:
            pass # Ignore other errors to keep bot alive

    # ─────────── Stop ───────────

    @ui.button(emoji="⏹️", label="", style=discord.ButtonStyle.danger, row=0)
    async def btn_stop(self, interaction: discord.Interaction, button: ui.Button):
        """Stop playback."""
        try:
            # Defer to allow time for disconnect
            await interaction.response.defer()
            await self.player.stop()
            await self.player.disconnect()

            # Send stopped confirmation
            embed = EmbedBuilder.info(
                "⏹️ Pemutaran Selesai",
                "Queue dikosongkan dan pemutaran dihentikan."
            )
            await interaction.followup.send(embed=embed)
        except Exception:
            pass

    # ─────────── Shuffle ───────────

    @ui.button(emoji="🔀", label="", style=discord.ButtonStyle.secondary, row=0)
    async def btn_shuffle(self, interaction: discord.Interaction, button: ui.Button):
        """Cycle shuffle modes: Off -> Standard -> Alternative -> Off."""
        from core.music_player import ShuffleMode
        
        # Check queue size again just in case
        if self.player.queue.size == 0:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Queue kosong, tidak bisa shuffle!"),
                ephemeral=True
            )
            return

        new_mode = ShuffleMode.OFF
        if self.player.shuffle_mode == ShuffleMode.OFF:
            new_mode = ShuffleMode.STANDARD
        elif self.player.shuffle_mode == ShuffleMode.STANDARD:
            new_mode = ShuffleMode.ALTERNATIVE
        elif self.player.shuffle_mode == ShuffleMode.ALTERNATIVE:
            new_mode = ShuffleMode.OFF
        
        await self.player.set_shuffle(new_mode)
        await self._update_message(interaction)

    # ─────────── Loop ───────────

    @ui.button(emoji="🔁", label="", style=discord.ButtonStyle.secondary, row=1)
    async def btn_loop(self, interaction: discord.Interaction, button: ui.Button):
        """Cycle through loop modes: off → single → queue → off."""
        from core.music_player import LoopMode
        cycle = {
            LoopMode.OFF: LoopMode.SINGLE,
            LoopMode.SINGLE: LoopMode.QUEUE,
            LoopMode.QUEUE: LoopMode.OFF,
        }
        self.player.loop_mode = cycle.get(self.player.loop_mode, LoopMode.OFF)
        await self._update_message(interaction)

    # ─────────── Autoplay ───────────

    @ui.button(emoji="⚪", label="", style=discord.ButtonStyle.secondary, row=1)
    async def btn_autoplay(self, interaction: discord.Interaction, button: ui.Button):
        """Cycle autoplay: Off -> YouTube -> Custom -> Custom 2 -> Off."""
        from core.music_player import AutoplayMode
        
        if self.player.autoplay_mode == AutoplayMode.OFF:
            self.player.autoplay_mode = AutoplayMode.YOUTUBE
        elif self.player.autoplay_mode == AutoplayMode.YOUTUBE:
            self.player.autoplay_mode = AutoplayMode.CUSTOM
        elif self.player.autoplay_mode == AutoplayMode.CUSTOM:
            self.player.autoplay_mode = AutoplayMode.CUSTOM2
        else:
            self.player.autoplay_mode = AutoplayMode.OFF
            
        # Trigger preload check if enabled
        if self.player.autoplay_mode != AutoplayMode.OFF:
             await self.player._trigger_autoplay_preload()

        await self._update_message(interaction)

    # ─────────── Queue ───────────

    @ui.button(emoji="📜", label="", style=discord.ButtonStyle.secondary, row=1)
    async def btn_queue(self, interaction: discord.Interaction, button: ui.Button):
        """Show the queue."""
        try:
            await interaction.response.defer(ephemeral=True)
            tracks = self.player.queue.as_list(limit=10)
            total = self.player.queue.size
            embed = EmbedBuilder.queue_list(tracks, self.player.current, total)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Queue button error: {e}")
            try:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Gagal memuat queue (error)."),
                    ephemeral=True
                )
            except:
                pass

    # ─────────── Lyrics ───────────

    @ui.button(emoji="🎤", label="", style=discord.ButtonStyle.secondary, row=1)
    async def btn_lyrics(self, interaction: discord.Interaction, button: ui.Button):
        """Fetch lyrics for the current track."""
        try:
            await interaction.response.defer()

            if not self.player.current:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Tidak ada lagu yang sedang diputar!"),
                    ephemeral=True
                )
                return

            # Disable button to prevent spam
            self.btn_lyrics.disabled = True
            self.btn_lyrics.label = ""
            self.btn_lyrics.emoji = "✅"
            self.btn_lyrics.style = discord.ButtonStyle.success
            try:
                if self.player.now_playing_message:
                    await self.player.now_playing_message.edit(view=self)
            except Exception:
                pass

            # Search Lyrics Concurrently (Race)
            duration = self.player.current.duration if self.player.current else None
            result = await get_lyrics_concurrently(self.player.current.title, duration=duration, loop=self.player.bot.loop)

            if not result:
                await interaction.followup.send(
                    embed=EmbedBuilder.error(
                        f"Lirik tidak ditemukan untuk: **{self.player.current.title}**"
                    )
                )
                return

            # Build and send lyrics embed(s)
            lyrics_text = result.get('lyrics') or result.get('syncedLyrics') # Fallback just in case
            if not lyrics_text:
                 await interaction.followup.send(
                    embed=EmbedBuilder.error("Konten lirik kosong.")
                )
                 return

            chunks = split_lyrics(lyrics_text, max_length=4096)
            
            source = result.get('source', 'Unknown')
            color = discord.Color.from_rgb(0, 255, 255) if source == 'Lrclib' else discord.Color.from_rgb(255, 255, 100)

            for i, chunk in enumerate(chunks):
                embed = discord.Embed(
                    title=f"🎤 {result.get('title', 'Lyrics')}" if i == 0 else f"🎤 {result.get('title', 'Lyrics')} (lanjutan)",
                    description=chunk,
                    color=color
                )
                if i == 0:
                    if result.get('artist'):
                        embed.add_field(name="🎙️ Artist", value=result['artist'], inline=True)
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
                self.player.lyrics_messages.append(msg)

        except Exception as e:
            print(f"Lyrics button error: {e}")
            try:
                await interaction.followup.send(
                    embed=EmbedBuilder.error("Gagal memuat lirik.")
                )
            except:
                pass


