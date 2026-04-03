"""
YTDLSource — yt-dlp audio source for Discord voice.
Handles YouTube URL extraction and keyword search.
"""

import asyncio
import copy
import logging
import os
import re
import shutil
from dataclasses import dataclass

import discord
import yt_dlp

logger = logging.getLogger('omnia.ytdl')
POT_PROVIDER_URL = os.getenv('POT_PROVIDER_URL', 'http://pot-provider:4416')
POT_PROVIDER_BASE = POT_PROVIDER_URL.rstrip('/')
COOKIE_FILE = os.getenv('YTDLP_COOKIEFILE', '/app/cookies.txt')
VISITOR_DATA = os.getenv('YTDLP_VISITOR_DATA', '').strip()
USE_COOKIES = os.getenv('YTDLP_USE_COOKIES', '').strip().lower() in {"1", "true", "yes", "on"}

# --- Startup diagnostic: check if PO Token plugin is installed ---
def _check_pot_plugin():
    """Check if bgutil-ytdlp-pot-provider plugin is installed and reachable."""
    try:
        import bgutil_ytdlp_pot_provider
        logger.info(f"✅ PO Token plugin loaded: bgutil-ytdlp-pot-provider")
    except ImportError:
        logger.warning("❌ PO Token plugin NOT installed: bgutil-ytdlp-pot-provider")

    # Check if pot-provider server is reachable
    node_path = shutil.which('node')
    if node_path:
        logger.info(f"Node.js runtime detected at: {node_path}")
    else:
        logger.warning("Node.js runtime not found in PATH; yt-dlp JS extraction may degrade.")

    import urllib.request
    try:
        req = urllib.request.urlopen(f"{POT_PROVIDER_BASE}/ping", timeout=3)
        logger.info(f"✅ PO Token server reachable at pot-provider:4416 (status {req.status})")
    except Exception as e:
        logger.warning(f"⚠️ PO Token server NOT reachable at pot-provider:4416: {e}")

_check_pot_plugin()
logger.info(f"Using PO Token provider base URL: {POT_PROVIDER_URL}")

# yt-dlp configuration
BASE_YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': False,
    'no_warnings': False,
    'verbose': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'socket_timeout': 20,
    'retries': 3,
    'extractor_retries': 3,
    'extract_flat': False,
    # Enable Node.js as JS runtime (yt-dlp only enables deno by default)
    'js_runtimes': {'node': {}, 'deno': {}},
    # Download helper scripts for JS challenge solving (Must be a list)
    'remote_components': ['ejs:github'],
    'allow_unplayable_formats': True,
    # Use mobile clients (android, ios) which are more reliable for audio extraction
    'extractor_args': {
        'youtube': ['player_client=ios,android,tv'],
        # Make sure PO Token provider finds the URL (plugin namespace is pot:bgutil:http)
        'pot:bgutil:http': [f'base_url={POT_PROVIDER_URL}']
    },
    'cachedir': False,
}

if USE_COOKIES and os.path.isfile(COOKIE_FILE):
    BASE_YTDL_FORMAT_OPTIONS['cookiefile'] = COOKIE_FILE
    logger.info(f"Using yt-dlp cookie file: {COOKIE_FILE}")
else:
    logger.info("yt-dlp cookie file disabled; using unauthenticated clients by default")

if VISITOR_DATA:
    BASE_YTDL_FORMAT_OPTIONS.setdefault('extractor_args', {}).setdefault('youtube', []).append(
        f'visitor_data={VISITOR_DATA}'
    )
    logger.info("Using yt-dlp visitor_data from environment")


def build_ytdl_options(**overrides):
    """Build yt-dlp options while preserving PO Token provider settings."""
    opts = copy.deepcopy(BASE_YTDL_FORMAT_OPTIONS)
    opts.update(overrides)
    return opts

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -analyzeduration 0 -probesize 32',
    'options': '-vn',
}

def _is_drm_error(error: Exception) -> bool:
    """Return True when yt-dlp indicates the target media is DRM-protected."""
    message = str(error).lower()
    return '[drm]' in message or 'drm protection' in message


def _extract_youtube_video_id(value: str) -> str | None:
    """Extract a YouTube video id from a URL or return None."""
    match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', value or '')
    return match.group(1) if match else None


@dataclass(slots=True)
class RequesterInfo:
    """Lightweight requester snapshot that avoids keeping a full Member alive."""

    id: int
    name: str
    display_name: str


class Track:
    """Represents a music track with metadata."""

    __slots__ = (
        "source_url",
        "title",
        "url",
        "duration",
        "thumbnail",
        "uploader",
        "requester",
        "insert_id",
    )

    def __init__(self, source_url: str, title: str, url: str, duration: int,
                 thumbnail: str, uploader: str, requester: discord.Member):
        self.source_url = source_url
        self.title = title
        self.url = url
        self.duration = int(duration) if duration else 0
        self.thumbnail = thumbnail
        self.uploader = uploader
        if requester is not None:
            self.requester = RequesterInfo(
                id=getattr(requester, "id", 0) or 0,
                name=getattr(requester, "name", None) or "Unknown",
                display_name=getattr(requester, "display_name", None)
                or getattr(requester, "name", None)
                or "Unknown",
            )
        else:
            self.requester = None
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
    async def _fetch_oembed_title(cls, video_url: str, *, loop: asyncio.AbstractEventLoop = None) -> str | None:
        """Fetch a YouTube title via oEmbed to build a fallback search query."""
        loop = loop or asyncio.get_event_loop()

        def _request_title():
            import json
            import urllib.parse
            import urllib.request

            endpoint = (
                "https://www.youtube.com/oembed?url="
                f"{urllib.parse.quote(video_url, safe='')}&format=json"
            )
            with urllib.request.urlopen(endpoint, timeout=10) as response:
                payload = json.load(response)
            return payload.get('title')

        try:
            return await loop.run_in_executor(None, _request_title)
        except Exception as e:
            logger.warning(f"Failed to fetch oEmbed title for DRM fallback: {e}")
            return None

    @classmethod
    async def _find_non_drm_alternative(
        cls,
        *,
        video_url: str,
        loop: asyncio.AbstractEventLoop = None,
        title_hint: str = "",
        uploader_hint: str = "",
    ) -> dict | None:
        """Search for a non-DRM alternative when the requested video cannot be played."""
        loop = loop or asyncio.get_event_loop()

        search_terms = []
        if title_hint:
            if uploader_hint and uploader_hint.lower() not in title_hint.lower():
                search_terms.append(f"{title_hint} {uploader_hint}")
            search_terms.append(title_hint)

        oembed_title = await cls._fetch_oembed_title(video_url, loop=loop)
        if oembed_title and oembed_title not in search_terms:
            search_terms.append(oembed_title)

        if not search_terms:
            video_id = _extract_youtube_video_id(video_url)
            if video_id:
                search_terms.append(video_id)

        original_id = _extract_youtube_video_id(video_url)
        for term in search_terms:
            query = f"ytsearch5:{term} audio"
            opts = build_ytdl_options(noplaylist=True, extract_flat='in_playlist')
            ydl_search = yt_dlp.YoutubeDL(opts)
            try:
                logger.warning(f'DRM fallback: searching alternative for "{term}"')
                data = await loop.run_in_executor(
                    None, lambda: ydl_search.extract_info(query, download=False)
                )
            except Exception as e:
                logger.warning(f"DRM fallback search failed for '{term}': {e}")
                continue

            entries = data.get('entries') if isinstance(data, dict) else None
            if not entries:
                continue

            for entry in entries:
                if not entry:
                    continue
                entry_id = entry.get('id')
                if original_id and entry_id == original_id:
                    continue
                alt_url = entry.get('webpage_url')
                if not alt_url:
                    if entry.get('url') and str(entry.get('url', '')).startswith('http'):
                        alt_url = entry['url']
                    elif entry_id:
                        alt_url = f"https://www.youtube.com/watch?v={entry_id}"
                if not alt_url:
                    continue
                entry['webpage_url'] = alt_url
                logger.warning(f"DRM fallback selected alternative: {entry.get('title', alt_url)}")
                return entry

        return None

    @classmethod
    async def get_info(
        cls,
        query: str,
        *,
        loop: asyncio.AbstractEventLoop = None,
        playlist_items: str | None = None,
    ):
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
        opts = build_ytdl_options(noplaylist=False)

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
            if playlist_items:
                opts['playlist_items'] = playlist_items
            else:
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
                if _is_drm_error(e) and not is_search:
                    logger.warning(f"DRM detected during get_info for {query}. Trying alternative search.")
                    alternative = await cls._find_non_drm_alternative(video_url=query, loop=loop)
                    if alternative:
                        data = {'entries': [alternative]}
                        is_search = True
                        break
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
    async def get_stream_data(
        cls,
        query: str,
        *,
        loop: asyncio.AbstractEventLoop = None,
        title_hint: str = "",
        uploader_hint: str = "",
    ) -> dict:
        """
        Extract stream data (audio URL) for a specific video.
        Used for pre-fetching or playback.
        """
        loop = loop or asyncio.get_event_loop()
        # Create a fresh instance per extraction so yt-dlp state is not shared
        # across concurrent playback, preload, and seek operations.
        ytdl = yt_dlp.YoutubeDL(build_ytdl_options())

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
                if _is_drm_error(e):
                    logger.warning(f"DRM detected during stream extraction for {query}. Trying alternative search.")
                    alternative = await cls._find_non_drm_alternative(
                        video_url=query,
                        loop=loop,
                        title_hint=title_hint,
                        uploader_hint=uploader_hint,
                    )
                    if alternative:
                        alt_url = alternative.get('webpage_url') or alternative.get('url')
                        if not alt_url:
                            continue
                        data = await loop.run_in_executor(
                            None, lambda: ytdl.extract_info(alt_url, download=False)
                        )
                        break
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
    async def from_url(
        cls,
        query: str,
        *,
        loop: asyncio.AbstractEventLoop = None,
        title_hint: str = "",
        uploader_hint: str = "",
        ffmpeg_options: dict | None = None,
    ):
        """
        Create audio source from a SPECIFIC URL (used by player).
        """
        data = await cls.get_stream_data(
            query,
            loop=loop,
            title_hint=title_hint,
            uploader_hint=uploader_hint,
        )

        source_url = data.get('url')
        if not source_url:
            raise ValueError("Gagal mendapatkan URL audio.")

        source = discord.FFmpegPCMAudio(source_url, **(ffmpeg_options or FFMPEG_OPTIONS))
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
                mix_opts = build_ytdl_options(
                    noplaylist=False,  # Allow playlist extraction
                    extract_flat='in_playlist',
                    playlist_items='2-6',  # Skip first (current song)
                    quiet=True,
                )
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

            search_opts = build_ytdl_options(extract_flat=True)
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
