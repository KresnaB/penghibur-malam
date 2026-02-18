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
from utils.genius_lyrics import search_lyrics, split_lyrics
from utils.lrclib_lyrics import get_lyrics as get_synced_lyrics

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

    @app_commands.command(name="play", description="Putar lagu dari YouTube (URL, Playlist, atau pencarian)")
    @app_commands.describe(query="YouTube URL, Playlist URL, atau kata kunci pencarian")
    async def play(self, interaction: discord.Interaction, query: str):
        """Play a track or playlist from YouTube."""
        start_time = asyncio.get_event_loop().time()
        logger.info(f"cmd:play START query='{query}' user={interaction.user.id}")

        if not await self._ensure_voice(interaction):
            return

        # Defer immediately because playlist extraction can take time
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
        
        t_connect = asyncio.get_event_loop().time()
        logger.info(f"cmd:play CONNECTED took {t_connect - start_time:.2f}s")

        # Extract track(s) info
        try:
            entries, playlist_title = await YTDLSource.get_info(query, loop=self.bot.loop)
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

        # Process entries
        added_tracks = []
        for entry in entries:
            # Normalize URL
            web_url = entry.get('webpage_url')
            if not web_url:
                if entry.get('url'):
                    if len(entry['url']) == 11:  # Video ID
                        web_url = f"https://www.youtube.com/watch?v={entry['url']}"
                    else:
                        web_url = entry['url']
                elif entry.get('id'):
                    web_url = f"https://www.youtube.com/watch?v={entry['id']}"
                else:
                    continue # Skip invalid entry
            
            # For non-playlist entries, source_url is the STREAM URL from full extraction
            source_url = entry.get('url', '') if not playlist_title else ''
            
            if 'youtube.com/watch' in source_url or 'youtu.be/' in source_url:
                logger.info("cmd:play Detected Webpage URL in source_url, clearing for lazy load.")
                source_url = ''
            elif source_url:
                 logger.info("cmd:play Preserving Stream URL for immediate playback.")
            
            track = Track(
                source_url=source_url,
                title=entry.get('title', 'Unknown'),
                url=web_url,
                duration=entry.get('duration', 0),
                thumbnail=entry.get('thumbnail', ''),
                uploader=entry.get('uploader', 'Unknown'),
                requester=interaction.user
            )
            added_tracks.append(track)

        if not added_tracks:
            await interaction.followup.send(
                embed=EmbedBuilder.error("Gagal memproses lagu dari playlist.")
            )
            return

        # Add to queue
        for track in added_tracks:
            position = await player.add_track(track)

        t_process = asyncio.get_event_loop().time()
        logger.info(f"cmd:play PROCESSED took {t_process - t_extract:.2f}s")

        # Notify user
        if len(added_tracks) == 1:
            track = added_tracks[0]
            if player.is_playing or player.current:
                embed = EmbedBuilder.added_to_queue(track, position)
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(
                    embed=EmbedBuilder.success(
                        "🎵 Memulai Pemutaran",
                        f"**[{track.title}]({track.url})**"
                    )
                )
        else:
            # Playlist added
            desc = f"Menambahkan **{len(added_tracks)}** lagu dari **{playlist_title or 'Playlist'}** ke queue."
            if len(added_tracks) >= 50:
                desc += "\n⚠️ Playlist dibatasi maksimal **50 lagu**. Sisanya tidak dimasukkan."
            embed = EmbedBuilder.success(
                "📜 Playlist Ditambahkan",
                desc
            )
            await interaction.followup.send(embed=embed)

        # Start playback if idle
        if not player.is_playing and not player.current:
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

        # Search Lrclib first
        duration = None
        if not query:
             player = self.get_player(interaction.guild)
             if player.current:
                 duration = player.current.duration

        logger.info(f"Lyrics command: Trying Lrclib for '{search_query}' duration={duration}")
        result = await get_synced_lyrics(search_query, duration=duration)

        # Fallback to Genius
        if not result:
            logger.info(f"Lyrics command: Lrclib failed, falling back to Genius for '{search_query}'")
            result = await search_lyrics(search_query, loop=self.bot.loop)

        if not result:
            await interaction.followup.send(
                embed=EmbedBuilder.error(
                    f"Lirik tidak ditemukan untuk: **{search_query}**\n"
                    "Coba gunakan `/lyrics query:<judul lagu>` dengan kata kunci yang lebih spesifik."
                )
            )
            return

        # Build lyrics embed(s)
        # Check source to determine fields
        source = result.get('source', 'Genius')
        lyrics_text = result.get('syncedLyrics') if source == 'Lrclib' and result.get('syncedLyrics') else result.get('lyrics')
        
        # Fallback to plain if synced is preferred but not available
        if not lyrics_text and source == 'Lrclib':
             lyrics_text = result.get('lyrics')

        if not lyrics_text:
             await interaction.followup.send(
                embed=EmbedBuilder.error(f"Konten lirik kosong ({source}).")
            )
             return

        chunks = split_lyrics(lyrics_text, max_length=4096)
        
        color = discord.Color.from_rgb(255, 255, 100) if source == 'Genius' else discord.Color.from_rgb(0, 255, 255)

        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"🎤 {result.get('title', search_query)}" if i == 0 else f"🎤 {result.get('title', search_query)} (lanjutan)",
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
            # Track for auto-delete when song changes
            player = self.get_player(interaction.guild)
            player.lyrics_messages.append(msg)

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
        else:
            embed.add_field(name="🎵 Sedang Diputar", value="Tidak ada", inline=False)

        # Queue
        embed.add_field(name="📋 Queue", value=f"{player.queue.size} lagu", inline=True)

        # Loop mode
        loop_icons = {"off": "🚫 Off", "single": "🔂 Single", "queue": "🔁 Queue"}
        embed.add_field(
            name="🔁 Loop",
            value=loop_icons.get(player.loop_mode, player.loop_mode),
            inline=True
        )

        # Autoplay
        embed.add_field(
            name="🔄 Autoplay",
            value="ON 🟢" if player.autoplay else "OFF 🔴",
            inline=True
        )

        embed.set_footer(text="Omnia Music 🎶")
        await interaction.response.send_message(embed=embed)

    # ─────────────────────── /help ───────────────────────

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
        embed.add_field(name="/stop", value="Stop pemutaran dan kosongkan queue", inline=False)
        embed.add_field(name="/queue", value="Tampilkan antrian lagu", inline=False)
        embed.add_field(name="/nowplaying", value="Tampilkan lagu yang sedang diputar", inline=False)
        embed.add_field(name="/loop `<mode>`", value="Atur mode loop (Off / Single / Queue)", inline=False)
        embed.add_field(name="/autoplay", value="Toggle autoplay rekomendasi otomatis", inline=False)
        embed.add_field(name="/lyrics `[query]`", value="Cari lirik lagu dari Genius (kosongkan untuk lagu saat ini)", inline=False)
        embed.add_field(name="/status", value="Tampilkan status bot musik", inline=False)
        embed.add_field(name="/help", value="Tampilkan daftar command ini", inline=False)
        embed.set_footer(text="Omnia Music 🎶")
        await interaction.response.send_message(embed=embed)

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
                if player.queue.size > 0 and not player.is_playing and not player.is_paused:
                     logger.info("Bot reconnected. Resuming queue...")
                     try:
                        await player.play_next()
                     except Exception as e:
                        logger.error(f"Failed to resume on reconnect: {e}")
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
                                    await player.text_channel.send(embed=embed)
                                except discord.HTTPException:
                                    pass
                            await player.disconnect()
                            self.cleanup_player(member.guild.id)


async def setup(bot: commands.Bot):
    """Load the Music cog."""
    await bot.add_cog(Music(bot))
    logger.info("Music cog loaded")
