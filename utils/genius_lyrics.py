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
            timeout=10,
        )
    return _genius


def _clean_title(title: str) -> str:
    """
    Clean a YouTube video title for better Genius search results.
    Removes common tags like (Official Video), [Lyrics], feat., etc.
    """
    # Remove common YouTube tags
    patterns = [
        r'\(Official\s*(Music\s*)?Video\)',
        r'\(Official\s*Audio\)',
        r'\(Lyric\s*Video\)',
        r'\(Lyrics?\)',
        r'\(Visualizer\)',
        r'\(Audio\)',
        r'\(Live\)',
        r'\[Official\s*(Music\s*)?Video\]',
        r'\[Official\s*Audio\]',
        r'\[Lyric\s*Video\]',
        r'\[Lyrics?\]',
        r'\[Visualizer\]',
        r'\[Audio\]',
        r'\[Live\]',
        r'\bMV\b',
        r'\bM/V\b',
        r'\bHD\b',
        r'\b4K\b',
        r'\bofficial\b',
        r'\blyrics?\b',
        r'\bvideo\b',
    ]
    cleaned = title
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Remove extra whitespace and trailing dashes/pipes
    cleaned = re.sub(r'\s*[-|]\s*$', '', cleaned)
    cleaned = re.sub(r'^\s*[-|]\s*', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned if cleaned else title


def _search_lyrics_sync(query: str) -> dict | None:
    """
    Synchronous Genius search. Returns dict with title, artist, lyrics, url, thumbnail.
    """
    try:
        genius = _get_genius()
        song = genius.search_song(query)
        if song:
            return {
                'title': song.title,
                'artist': song.artist,
                'lyrics': song.lyrics,
                'url': song.url,
                'thumbnail': song.song_art_image_thumbnail_url if hasattr(song, 'song_art_image_thumbnail_url') else '',
            }
    except Exception as e:
        logger.error(f"Genius search error: {e}")
    return None


async def search_lyrics(query: str, *, loop: asyncio.AbstractEventLoop = None) -> dict | None:
    """
    Async wrapper for Genius lyrics search.
    Returns dict with: title, artist, lyrics, url, thumbnail
    Returns None if not found.
    """
    loop = loop or asyncio.get_event_loop()
    # Clean YouTube-style title
    cleaned = _clean_title(query)
    logger.info(f'Lyrics search: "{query}" → cleaned: "{cleaned}"')

    result = await loop.run_in_executor(None, partial(_search_lyrics_sync, cleaned))

    # Fallback: try original query if cleaned version failed
    if result is None and cleaned != query:
        logger.info(f'Lyrics fallback: trying original query "{query}"')
        result = await loop.run_in_executor(None, partial(_search_lyrics_sync, query))

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
