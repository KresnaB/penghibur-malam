"""
NowPlayingView — Interactive button controls for the Now Playing embed.
Buttons: Pause/Resume, Skip, Loop, Queue, Autoplay
"""

import discord
from discord import ui

from utils.embed_builder import EmbedBuilder


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
            self.btn_pause.label = "Resume"
            self.btn_pause.style = discord.ButtonStyle.success
        else:
            self.btn_pause.emoji = "⏸️"
            self.btn_pause.label = "Pause"
            self.btn_pause.style = discord.ButtonStyle.secondary

        # Loop button
        from core.music_player import LoopMode
        loop_styles = {
            LoopMode.OFF: ("🔁", "Loop", discord.ButtonStyle.secondary),
            LoopMode.SINGLE: ("🔂", "Loop: 1", discord.ButtonStyle.primary),
            LoopMode.QUEUE: ("🔁", "Loop: All", discord.ButtonStyle.primary),
        }
        emoji, label, style = loop_styles.get(
            self.player.loop_mode,
            ("🔁", "Loop", discord.ButtonStyle.secondary)
        )
        self.btn_loop.emoji = emoji
        self.btn_loop.label = label
        self.btn_loop.style = style

        # Autoplay button
        if self.player.autoplay:
            self.btn_autoplay.label = "Autoplay: ON"
            self.btn_autoplay.style = discord.ButtonStyle.success
        else:
            self.btn_autoplay.label = "Autoplay"
            self.btn_autoplay.style = discord.ButtonStyle.secondary

    async def _update_message(self, interaction: discord.Interaction):
        """Update the embed and buttons after a button press."""
        self._update_buttons()
        if self.player.current:
            embed = EmbedBuilder.now_playing(self.player.current)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)

    # ─────────── Pause/Resume ───────────

    @ui.button(emoji="⏸️", label="Pause", style=discord.ButtonStyle.secondary, row=0)
    async def btn_pause(self, interaction: discord.Interaction, button: ui.Button):
        """Toggle pause/resume."""
        if self.player.is_paused:
            await self.player.resume()
        else:
            await self.player.pause()
        await self._update_message(interaction)

    # ─────────── Skip ───────────

    @ui.button(emoji="⏭️", label="Skip", style=discord.ButtonStyle.primary, row=0)
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

    @ui.button(emoji="⏹️", label="Stop", style=discord.ButtonStyle.danger, row=0)
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

    # ─────────── Loop ───────────

    @ui.button(emoji="🔁", label="Loop", style=discord.ButtonStyle.secondary, row=1)
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

    @ui.button(emoji="🔄", label="Autoplay", style=discord.ButtonStyle.secondary, row=1)
    async def btn_autoplay(self, interaction: discord.Interaction, button: ui.Button):
        """Toggle autoplay."""
        self.player.autoplay = not self.player.autoplay
        await self._update_message(interaction)

    # ─────────── Queue ───────────

    @ui.button(emoji="📜", label="Queue", style=discord.ButtonStyle.secondary, row=1)
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
