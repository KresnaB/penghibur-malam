"""
YTDLSource — yt-dlp audio source for Discord voice.
Handles YouTube URL extraction and keyword search.
"""

import asyncio
import discord
import yt_dlp

# yt-dlp configuration
YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': False,
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(YTDL_FORMAT_OPTIONS)


class Track:
    """Represents a music track with metadata."""

    def __init__(self, source_url: str, title: str, url: str, duration: int,
                 thumbnail: str, uploader: str, requester: discord.Member):
        self.source_url = source_url
        self.title = title
        self.url = url
        self.duration = duration
        self.thumbnail = thumbnail
        self.uploader = uploader
        self.requester = requester

    @property
    def duration_str(self) -> str:
        """Format duration as MM:SS or HH:MM:SS."""
        if not self.duration:
            return "Live"
        hours, remainder = divmod(self.duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class YTDLSource(discord.PCMVolumeTransformer):
    """Audio source from yt-dlp with volume control."""

    def __init__(self, source: discord.AudioSource, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown')
        self.url = data.get('webpage_url', '')
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail', '')
        self.uploader = data.get('uploader', 'Unknown')

    @classmethod
    async def from_url(cls, query: str, *, loop: asyncio.AbstractEventLoop = None):
        """
        Extract audio from a YouTube URL or search query.
        Returns (YTDLSource, data_dict).
        """
        loop = loop or asyncio.get_event_loop()

        # Determine if it's a URL or search query
        if not query.startswith(('http://', 'https://')):
            query = f'ytsearch1:{query}'

        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(query, download=False)
        )

        # If search results, take the first entry
        if 'entries' in data:
            if not data['entries']:
                raise ValueError("Tidak ditemukan hasil untuk pencarian tersebut.")
            data = data['entries'][0]

        source_url = data.get('url')
        if not source_url:
            raise ValueError("Gagal mendapatkan URL audio.")

        source = discord.FFmpegPCMAudio(source_url, **FFMPEG_OPTIONS)
        return cls(source, data=data), data

    @classmethod
    async def get_related(cls, video_url: str, title: str = "", *, loop: asyncio.AbstractEventLoop = None) -> list:
        """
        Get related videos for autoplay.
        Returns list of dicts with 'url' and 'title' keys.
        
        Strategy:
        1. Try YouTube Radio Mix (RD playlist) for the video
        2. Fallback: search YouTube with the track title
        """
        loop = loop or asyncio.get_event_loop()
        import re
        import logging
        logger = logging.getLogger('antigrafity.ytdl')

        related = []

        # --- Strategy 1: YouTube Radio Mix ---
        try:
            # Extract video ID from URL
            video_id = None
            id_match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', video_url)
            if id_match:
                video_id = id_match.group(1)

            if video_id:
                mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
                mix_opts = {
                    **YTDL_FORMAT_OPTIONS,
                    'noplaylist': False,  # Allow playlist extraction
                    'extract_flat': 'in_playlist',
                    'playlist_items': '2-6',  # Skip first (current song)
                    'quiet': True,
                }
                ydl_mix = yt_dlp.YoutubeDL(mix_opts)
                mix_data = await loop.run_in_executor(
                    None, lambda: ydl_mix.extract_info(mix_url, download=False)
                )
                if mix_data and 'entries' in mix_data:
                    for entry in mix_data['entries']:
                        if entry and (entry.get('url') or entry.get('id')):
                            url = entry.get('url') or f"https://www.youtube.com/watch?v={entry['id']}"
                            related.append({
                                'url': url,
                                'title': entry.get('title', 'Unknown')
                            })
                    if related:
                        logger.info(f"Autoplay: Found {len(related)} tracks from YouTube Mix")
                        return related
        except Exception as e:
            logger.warning(f"Autoplay Mix failed: {e}")

        # --- Strategy 2: Search YouTube with track title ---
        try:
            search_query = title if title else video_url
            # Clean up title for better search results
            search_query = re.sub(r'\(.*?\)|\[.*?\]', '', search_query).strip()
            search_query = f"ytsearch5:{search_query} music"

            search_opts = {**YTDL_FORMAT_OPTIONS, 'extract_flat': True}
            ydl_search = yt_dlp.YoutubeDL(search_opts)
            search_data = await loop.run_in_executor(
                None, lambda: ydl_search.extract_info(search_query, download=False)
            )
            if search_data and 'entries' in search_data:
                for entry in search_data['entries']:
                    if entry and (entry.get('url') or entry.get('id')):
                        entry_url = entry.get('url') or f"https://www.youtube.com/watch?v={entry['id']}"
                        # Skip if it's the same video
                        if video_url and entry.get('id') and entry['id'] in video_url:
                            continue
                        related.append({
                            'url': entry_url,
                            'title': entry.get('title', 'Unknown')
                        })
                if related:
                    logger.info(f"Autoplay: Found {len(related)} tracks from YouTube Search")
                    return related
        except Exception as e:
            logger.warning(f"Autoplay Search failed: {e}")

        return related
