"""
EmbedBuilder — Rich embed helpers for the music bot.
"""

from __future__ import annotations

import discord
from core.ytdl_source import Track


class EmbedBuilder:
    """Helper class for creating Discord embeds."""

    # Color palette
    COLOR_PLAYING = discord.Color.from_rgb(138, 43, 226)   # Purple
    COLOR_QUEUE = discord.Color.from_rgb(30, 144, 255)     # Dodger blue
    COLOR_SUCCESS = discord.Color.from_rgb(46, 204, 113)   # Green
    COLOR_ERROR = discord.Color.from_rgb(231, 76, 60)      # Red
    COLOR_INFO = discord.Color.from_rgb(52, 152, 219)      # Blue
    COLOR_AUTOPLAY = discord.Color.from_rgb(255, 165, 0)   # Orange
    COLOR_TASTEDIVE = discord.Color.from_rgb(0, 191, 255)  # Deep Sky Blue

    @staticmethod
    def now_playing(track: Track) -> discord.Embed:
        """Create a Now Playing embed."""
        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**[{track.title}]({track.url})**",
            color=EmbedBuilder.COLOR_PLAYING
        )
        embed.add_field(name="⏱️ Durasi", value=track.duration_str, inline=True)
        embed.add_field(name="🎤 Uploader", value=track.uploader, inline=True)
        embed.add_field(
            name="👤 Requested by",
            value=track.requester.display_name if track.requester else "Unknown",
            inline=True
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.set_footer(text="Omnia Music 🎶")
        return embed

    @staticmethod
    def added_to_queue(track: Track, position: int) -> discord.Embed:
        """Create an Added to Queue embed."""
        embed = discord.Embed(
            title="📥 Ditambahkan ke Queue",
            description=f"**[{track.title}]({track.url})**",
            color=EmbedBuilder.COLOR_SUCCESS
        )
        embed.add_field(name="⏱️ Durasi", value=track.duration_str, inline=True)
        embed.add_field(name="📍 Posisi", value=f"#{position}", inline=True)
        embed.add_field(
            name="👤 Requested by",
            value=track.requester.display_name if track.requester else "Unknown",
            inline=True
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        return embed

    @staticmethod
    def queue_list(tracks: list, current: Track | None, total_size: int) -> discord.Embed:
        """Create a Queue list embed. Supports paging via multiple fields."""
        embed = discord.Embed(
            title="📜 Music Queue",
            color=EmbedBuilder.COLOR_QUEUE
        )

        if current:
            embed.add_field(
                name="🎵 Sedang Diputar",
                value=f"**[{current.title}]({current.url})** [{current.duration_str}]",
                inline=False
            )

        if not tracks:
            embed.add_field(
                name="📋 Antrian",
                value="*Queue kosong*",
                inline=False
            )
            embed.set_footer(text="Omnia Music 🎶")
            return embed

        # Process tracks
        current_field_text = ""
        current_field_index = 0
        field_limit = 1024
        
        for i, track in enumerate(tracks, 1):
            # Truncate title
            title = track.title
            if len(title) > 40:
                title = title[:37] + "..."
            
            line = f"`{i}.` **[{title}]({track.url})** [{track.duration_str}]\n"
            
            # Check length for current field (leave buffer for footer if this is the last chunk)
            if len(current_field_text) + len(line) > 1000:
                # Field full, add it and start new one
                field_name = f"📋 Antrian ({total_size} lagu)" if current_field_index == 0 else "📋 Antrian (Lanjutan)"
                embed.add_field(name=field_name, value=current_field_text, inline=False)
                current_field_text = ""
                current_field_index += 1
            
            current_field_text += line

        # Add remaining text
        if current_field_text:
            # Check if we need to add "and X others"
            if total_size > len(tracks):
                remaining = total_size - len(tracks)
                footer = f"\n*... dan {remaining} lagu lainnya*"
                
                # If fits in current field
                if len(current_field_text) + len(footer) <= 1024:
                    current_field_text += footer
                else:
                    # If doesn't fit, add current field then new field for footer (rare but possible)
                    field_name = f"📋 Antrian ({total_size} lagu)" if current_field_index == 0 else "📋 Antrian (Lanjutan)"
                    embed.add_field(name=field_name, value=current_field_text, inline=False)
                    current_field_text = footer
                    current_field_index += 1

            field_name = f"📋 Antrian ({total_size} lagu)" if current_field_index == 0 else "📋 Antrian (Lanjutan)"
            embed.add_field(name=field_name, value=current_field_text, inline=False)

        embed.set_footer(text="Omnia Music 🎶")
        return embed

    @staticmethod
    def autoplay_next(track: Track) -> discord.Embed:
        """Create an Autoplay embed."""
        embed = discord.Embed(
            title="🔄 Autoplay",
            description=f"**[{track.title}]({track.url})**",
            color=EmbedBuilder.COLOR_AUTOPLAY
        )
        embed.add_field(name="⏱️ Durasi", value=track.duration_str, inline=True)
        embed.add_field(name="🎤 Uploader", value=track.uploader, inline=True)
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        embed.set_footer(text="Autoplay • Omnia Music 🎶")
        return embed

    @staticmethod
    def error(message: str) -> discord.Embed:
        """Create an error embed."""
        return discord.Embed(
            title="❌ Error",
            description=message,
            color=EmbedBuilder.COLOR_ERROR
        )

    @staticmethod
    def info(title: str, description: str) -> discord.Embed:
        """Create a generic info embed."""
        return discord.Embed(
            title=title,
            description=description,
            color=EmbedBuilder.COLOR_INFO
        )

    @staticmethod
    def success(title: str, description: str) -> discord.Embed:
        """Create a success embed."""
        return discord.Embed(
            title=title,
            description=description,
            color=EmbedBuilder.COLOR_SUCCESS
        )
