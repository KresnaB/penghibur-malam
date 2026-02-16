"""
GeniusLyrics — Fetch song lyrics from Genius API.
Uses lyricsgenius library with the Genius Access Token.
"""

import os
import re
import logging
import asyncio
from functools import partial

import lyricsgenius

logger = logging.getLogger('antigrafity.lyrics')

# Initialize Genius client
_genius = None


def _get_genius():
    """Lazy-init Genius client."""
    global _genius
    if _genius is None:
        token = os.getenv('GENIUS_ACCESS_TOKEN')
        if not token:
            raise ValueError("GENIUS_ACCESS_TOKEN tidak ditemukan di .env!")
        _genius = lyricsgenius.Genius(
            token,
            verbose=False,
            remove_section_headers=False,
            skip_non_songs=True,
            timeout=30,
        )
    return _genius



NOISE_KEYWORDS = [
    "official", "video", "audio", "lyrics", "lyric",
    "hd", "4k", "mv", "music video", "visualizer",
    "remastered", "live", "version", "edit",
    "explicit", "clean"
]


def _clean_title(title: str) -> str:
    """
    Clean YouTube title aggressively for Genius API search.
    Goal: return pure song title only.
    """

    original = title
    cleaned = title.lower()

    # 1️⃣ Remove content inside () and []
    cleaned = re.sub(r'\([^)]*\)', '', cleaned)
    cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)

    # 2️⃣ Remove common noise keywords
    for word in NOISE_KEYWORDS:
        cleaned = re.sub(rf'\b{re.escape(word)}\b', '', cleaned)

    # 3️⃣ Normalize separators
    cleaned = cleaned.replace('|', '-')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # 5️⃣ Remove "feat", "ft", "featuring"
    cleaned = re.sub(r'\b(feat|ft|featuring)\b.*', '', cleaned)

    # 6️⃣ Final whitespace and separator cleanup
    cleaned = re.sub(r'\s*[-|]\s*$', '', cleaned)
    cleaned = re.sub(r'^\s*[-|]\s*', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned if cleaned else original


def _extract_metadata(query: str) -> dict:
    """
    Attempt to extract artist and title from a query string.
    Returns dict with 'artist' and 'title' if successful, else content is just 'title'.
    """
    # Common separators: " - ", " : ", " | "
    # Improved regex to handle optional spaces for colon/pipe, but distinct spaces for dash
    separators = [r'\s-\s', r'\s*:\s*', r'\s*\|\s*']

    for sep in separators:
        parts = re.split(sep, query, maxsplit=1)
        if len(parts) == 2:
            return {'artist': parts[0].strip(), 'title': parts[1].strip()}

    return {'title': query.strip()}


def _search_lyrics_sync(title: str, artist: str = "") -> dict | None:
    """
    Synchronous Genius search with retry logic.
    Returns dict with title, artist, lyrics, url, thumbnail.
    """
    import time
    max_retries = 3

    for attempt in range(max_retries):
        try:
            genius = _get_genius()
            song = genius.search_song(title, artist)
            if song:
                return {
                    'title': song.title,
                    'artist': song.artist,
                    'lyrics': song.lyrics,
                    'url': song.url,
                }
            return None  # Song not found, no need to retry
        except Exception as e:
            logger.warning(f"Genius search attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))  # Backoff: 2s, 4s
            else:
                logger.error(f"Genius search failed after {max_retries} attempts: {e}")
    return None


async def search_lyrics(query: str, *, loop: asyncio.AbstractEventLoop = None) -> dict | None:
    """
    Async wrapper for Genius lyrics search.
    Strategies:
    1. Structured Search (Artist - Title) if separator found.
    2. Structured Search (Title - Artist) swap.
    3. Cleaned Query Search.
    4. Original Query Search.
    """
    loop = loop or asyncio.get_event_loop()

    # 1. Clean the title
    cleaned = _clean_title(query)
    logger.info(f'Lyrics search: "{query}" → cleaned: "{cleaned}"')

    # 2. Extract metadata
    metadata = _extract_metadata(cleaned)

    # Helper to run sync search
    async def run_search(t, a=""):
        return await loop.run_in_executor(None, partial(_search_lyrics_sync, t, a))

    result = None

    # Strategy 1: Cleaned query (Primary)
    # This is usually fastest and most robust as it relies on Genius's search relevance
    logger.info(f'Lyrics strategy: Cleaned query "{cleaned}"')
    result = await run_search(cleaned)

    # Strategy 2: Structured search (Fallback)
    if not result and 'artist' in metadata:
        artist, title = metadata['artist'], metadata['title']
        logger.info(f'Lyrics strategy: Structured "{artist}" - "{title}"')
        
        # Try Artist - Title
        result = await run_search(title, artist)
        
        # Try Title - Artist (swap) if failed
        if not result:
            logger.info(f'Lyrics strategy: Structured Swap "{title}" - "{artist}"')
            result = await run_search(artist, title)

    # Strategy 3: Original query (Last resort)
    if not result and cleaned != query:
        logger.info(f'Lyrics strategy: Original query "{query}"')
        result = await run_search(query)

    return result


def split_lyrics(lyrics: str, max_length: int = 4096) -> list[str]:
    """
    Split lyrics into chunks that fit within Discord embed limits.
    Tries to split at paragraph boundaries.
    """
    if len(lyrics) <= max_length:
        return [lyrics]

    chunks = []
    current = ""

    for line in lyrics.split('\n'):
        # Check if adding this line would exceed the limit
        if len(current) + len(line) + 1 > max_length:
            if current:
                chunks.append(current.strip())
            current = line + '\n'
        else:
            current += line + '\n'

    if current.strip():
        chunks.append(current.strip())

    return chunks
