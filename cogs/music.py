"""
Music Cog — Slash commands for the music bot.
Handles all user-facing commands and voice state events.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.music_player import MusicPlayer, LoopMode
from core.ytdl_source import Track, YTDLSource
from utils.embed_builder import EmbedBuilder
from utils.now_playing_view import NowPlayingView

logger = logging.getLogger('antigrafity.music')


class Music(commands.Cog):
    """Music commands for Antigrafity bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, MusicPlayer] = {}  # guild_id -> MusicPlayer

    def get_player(self, guild: discord.Guild) -> MusicPlayer:
        """Get or create MusicPlayer for a guild."""
        if guild.id not in self.players:
            player = MusicPlayer(self.bot, guild)
            player._view_factory = lambda p: NowPlayingView(p)
            self.players[guild.id] = player
        return self.players[guild.id]

    def cleanup_player(self, guild_id: int):
        """Remove player for a guild."""
        if guild_id in self.players:
            del self.players[guild_id]

    # ─────────────────────── Helper Checks ───────────────────────

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

    @app_commands.command(name="play", description="Putar lagu dari YouTube (URL atau pencarian)")
    @app_commands.describe(query="YouTube URL atau kata kunci pencarian")
    async def play(self, interaction: discord.Interaction, query: str):
        """Play a track from YouTube URL or search query."""
        if not await self._ensure_voice(interaction):
            return

        await interaction.response.defer()

        player = self.get_player(interaction.guild)
        player.text_channel = interaction.channel

        # Connect to voice channel
        try:
            await player.connect(interaction.user.voice.channel)
        except Exception as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error(f"Gagal join voice channel: `{e}`")
            )
            return

        # Extract track info
        try:
            _, data = await YTDLSource.from_url(query, loop=self.bot.loop)

            track = Track(
                source_url=data.get('url', ''),
                title=data.get('title', 'Unknown'),
                url=data.get('webpage_url', query),
                duration=data.get('duration', 0),
                thumbnail=data.get('thumbnail', ''),
                uploader=data.get('uploader', 'Unknown'),
                requester=interaction.user
            )

        except Exception as e:
            await interaction.followup.send(
                embed=EmbedBuilder.error(f"Gagal mencari lagu: `{e}`")
            )
            return

        # If already playing, add to queue
        if player.is_playing or player.current:
            position = await player.add_track(track)
            embed = EmbedBuilder.added_to_queue(track, position)
            await interaction.followup.send(embed=embed)
        else:
            # Start playing immediately
            await player.add_track(track)
            await interaction.followup.send(
                embed=EmbedBuilder.success(
                    "🎵 Memulai Pemutaran",
                    f"**[{track.title}]({track.url})**"
                )
            )
            await player.play_next()



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
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Tidak ada lagu yang sedang diputar!"),
                ephemeral=True
            )
            return

        current_title = player.current.title if player.current else "Unknown"
        await player.skip()
        await interaction.response.send_message(
            embed=EmbedBuilder.success("⏭️ Skipped", f"**{current_title}**")
        )

    # ─────────────────────── /stop ───────────────────────

    @app_commands.command(name="stop", description="Stop pemutaran dan kosongkan queue")
    async def stop(self, interaction: discord.Interaction):
        """Stop playback, clear queue, and disconnect."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)
        await player.stop()
        await player.disconnect()
        self.cleanup_player(interaction.guild.id)

        await interaction.response.send_message(
            embed=EmbedBuilder.success("⏹️ Stopped", "Pemutaran dihentikan dan queue dikosongkan.")
        )

    # ─────────────────────── /queue ───────────────────────

    @app_commands.command(name="queue", description="Tampilkan antrian lagu")
    async def queue(self, interaction: discord.Interaction):
        """Show the current queue."""
        player = self.get_player(interaction.guild)

        tracks = player.queue.as_list(limit=10)
        total = player.queue.size
        embed = EmbedBuilder.queue_list(tracks, player.current, total)

        # Add loop and autoplay status
        status_parts = []
        if player.loop_mode != LoopMode.OFF:
            status_parts.append(f"🔁 Loop: **{player.loop_mode}**")
        if player.autoplay:
            status_parts.append("🔄 Autoplay: **ON**")
        if status_parts:
            embed.add_field(name="⚙️ Status", value=" • ".join(status_parts), inline=False)

        await interaction.response.send_message(embed=embed)

    # ─────────────────────── /nowplaying ───────────────────────

    @app_commands.command(name="nowplaying", description="Tampilkan lagu yang sedang diputar")
    async def nowplaying(self, interaction: discord.Interaction):
        """Show the currently playing track."""
        player = self.get_player(interaction.guild)

        if not player.current:
            await interaction.response.send_message(
                embed=EmbedBuilder.error("Tidak ada lagu yang sedang diputar!"),
                ephemeral=True
            )
            return

        embed = EmbedBuilder.now_playing(player.current)

        # Add extra info
        info_parts = []
        if player.loop_mode != LoopMode.OFF:
            info_parts.append(f"🔁 Loop: {player.loop_mode}")
        if player.autoplay:
            info_parts.append("🔄 Autoplay: ON")
        info_parts.append(f"📋 Queue: {player.queue.size} lagu")

        embed.add_field(name="⚙️ Info", value=" • ".join(info_parts), inline=False)

        await interaction.response.send_message(embed=embed)

    # ─────────────────────── /loop ───────────────────────

    @app_commands.command(name="loop", description="Atur mode loop")
    @app_commands.describe(mode="Mode loop: off, single, atau queue")
    @app_commands.choices(mode=[
        app_commands.Choice(name="🚫 Off", value="off"),
        app_commands.Choice(name="🔂 Single", value="single"),
        app_commands.Choice(name="🔁 Queue", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: str):
        """Set loop mode."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)
        player.loop_mode = mode

        icons = {"off": "🚫", "single": "🔂", "queue": "🔁"}
        icon = icons.get(mode, "")

        await interaction.response.send_message(
            embed=EmbedBuilder.success(
                f"{icon} Loop Mode",
                f"Loop diatur ke: **{mode}**"
            )
        )

    # ─────────────────────── /autoplay ───────────────────────

    @app_commands.command(name="autoplay", description="Toggle autoplay (rekomendasi otomatis)")
    async def autoplay(self, interaction: discord.Interaction):
        """Toggle autoplay on/off."""
        if not await self._ensure_voice(interaction):
            return
        if not await self._ensure_same_channel(interaction):
            return

        player = self.get_player(interaction.guild)
        player.autoplay = not player.autoplay

        status = "ON 🟢" if player.autoplay else "OFF 🔴"
        desc = ("Bot akan otomatis memutar lagu terkait saat queue kosong."
                if player.autoplay
                else "Autoplay dimatikan.")

        await interaction.response.send_message(
            embed=EmbedBuilder.success(f"🔄 Autoplay: {status}", desc)
        )

    # ─────────────────────── Voice State Listener ───────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        """Auto disconnect when bot is alone in voice channel."""
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
                                    await player.text_channel.send(embed=embed)
                                except discord.HTTPException:
                                    pass
                            await player.disconnect()
                            self.cleanup_player(member.guild.id)


async def setup(bot: commands.Bot):
    """Load the Music cog."""
    await bot.add_cog(Music(bot))
    logger.info("Music cog loaded")
