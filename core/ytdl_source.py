"""
YTDLSource — yt-dlp audio source for Discord voice.
Handles YouTube URL extraction and keyword search.
"""

import asyncio
import re
import logging
import discord
import yt_dlp

logger = logging.getLogger('omnia.ytdl')

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
    'cachedir': False,
    # Anti-blocking: Use cookies.txt if available
    'cookiefile': 'cookies.txt',
    # Spoof User-Agent
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.youtube.com/',
    }
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 0 -probesize 32',
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
        self.duration = int(duration) if duration else 0
        self.thumbnail = thumbnail
        self.uploader = uploader
        self.requester = requester
        self.insert_id = 0  # For tracking original order

    @property
    def duration_str(self) -> str:
        """Format duration as MM:SS or HH:MM:SS."""
        if not self.duration:
            return "Live"
        total = int(self.duration)
        hours, remainder = divmod(total, 3600)
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
    async def get_info(cls, query: str, *, loop: asyncio.AbstractEventLoop = None):
        """
        Extract track info without downloading audio.
        Handles playlists and single tracks.
        Returns (list_of_entries, playlist_title).
        """
        loop = loop or asyncio.get_event_loop()

        # Check if it's a search query
        is_search = not query.startswith(('http://', 'https://'))
        if is_search:
            query = f'ytsearch1:{query}'

        # Options: allow playlist, extract flat for speed
        opts = YTDL_FORMAT_OPTIONS.copy()
        opts['noplaylist'] = False

        # Detect YouTube Radio/Mix URLs (list=RD...) — treat as single song
        is_radio = not is_search and 'list=RD' in query
        if is_radio:
            # Extract just the video ID and play as single song
            video_match = re.search(r'[?&]v=([^&]+)', query)
            if video_match:
                query = f'https://www.youtube.com/watch?v={video_match.group(1)}'
            opts['noplaylist'] = True
        elif not is_search and 'list=' in query:
            # Regular playlist: extract flat for speed
            opts['extract_flat'] = 'in_playlist'
            opts['playlistend'] = 50  # Limit to 50 songs max
        elif is_search:
             # Search: use extract_flat to avoid downloading audio stream metadata up-front, making responses instant
            opts['extract_flat'] = 'in_playlist'

        ydl = yt_dlp.YoutubeDL(opts)
        
        # Retry logic for network errors
        data = None
        last_error = None
        for attempt in range(3):
            try:
                data = await loop.run_in_executor(
                    None, lambda: ydl.extract_info(query, download=False)
                )
                break
            except Exception as e:
                last_error = e
                # Check for common network errors
                error_str = str(e).lower()
                network_errors = [
                    'dns', 'socket', 'connection', 'temporary failure', 
                    'timeout', 'reset', 'refused', 'handshake', 'remote end closed'
                ]
                if any(err in error_str for err in network_errors):
                    wait = 2 ** attempt
                    logger.warning(f"YTDL network error, retrying in {wait}s... ({e})")
                    await asyncio.sleep(wait)
                    continue
                raise e

        if not data and last_error:
            raise last_error
        
        if not data:
            raise ValueError("Tidak ditemukan data.")

        entries = []
        is_playlist = False
        playlist_title = data.get('title', 'Unknown Playlist')

        if 'entries' in data:
            # It's a playlist or search result
            if is_search:
                # Search result: take first one
                if data.get('entries'):
                    entry = data['entries'][0]
                elif is_search and 'entries' not in data:
                    # Sometimes ytsearch1 returns the dict directly if not flat
                    entry = data
                else:
                    entry = None

                if entry:
                    # Fix up data
                    if not entry.get('url'):
                        entry['url'] = f"https://www.youtube.com/watch?v={entry['id']}"
                    
                    # If we did full extraction, 'url' might be the googlevideo link.
                    # We want the webpage_url for the Track object, but we can store the stream url if needed.
                    # Standardize: entry['url'] should be webpage_url for Track compatibility
                    webpage_url = entry.get('webpage_url')
                    if not webpage_url and entry.get('id'):
                        webpage_url = f"https://www.youtube.com/watch?v={entry['id']}"
                    
                    entry['webpage_url'] = webpage_url
                    entries = [entry]
                else:
                    entries = []
            else:
                # Playlist URL
                is_playlist = True
                all_entries = list(data['entries'])
                entries = all_entries[:50]  # Cap at 50 songs
                # Fix up playlist entries if flat extracted
                for entry in entries:
                     if not entry.get('url') and entry.get('id'):
                        entry['url'] = f"https://www.youtube.com/watch?v={entry['id']}"
                     if not entry.get('thumbnail') and entry.get('id'):
                        entry['thumbnail'] = f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg"

        else:
            # Single video (full extraction usually, unless forced flat)
            entries = [data]

        if not entries:
            raise ValueError("Tidak ditemukan hasil.")
            
        return entries, (playlist_title if is_playlist else None)


    @classmethod
    async def get_stream_data(cls, query: str, *, loop: asyncio.AbstractEventLoop = None) -> dict:
        """
        Extract stream data (audio URL) for a specific video.
        Used for pre-fetching or playback.
        """
        loop = loop or asyncio.get_event_loop()

        # Retry logic for extraction
        data = None
        last_error = None
        for attempt in range(3):
            try:
                data = await loop.run_in_executor(
                    None, lambda: ytdl.extract_info(query, download=False)
                )
                break
            except Exception as e:
                last_error = e
                # Check for common network errors
                error_str = str(e).lower()
                network_errors = [
                    'dns', 'socket', 'connection', 'temporary failure', 
                    'timeout', 'reset', 'refused', 'handshake', 'remote end closed'
                ]
                if any(err in error_str for err in network_errors):
                    wait = 2 ** attempt
                    logger.warning(f"YTDL extraction error (playback), retrying in {wait}s... ({e})")
                    await asyncio.sleep(wait)
                    continue
                raise e
        
        if not data and last_error:
            raise last_error

        if 'entries' in data:
            data = data['entries'][0]
            
        return data

    @classmethod
    async def from_url(cls, query: str, *, loop: asyncio.AbstractEventLoop = None):
        """
        Create audio source from a SPECIFIC URL (used by player).
        """
        data = await cls.get_stream_data(query, loop=loop)

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
        # logger already initialized at module level

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
