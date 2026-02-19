import os
import logging
import aiohttp
import random
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger('antigrafity.tastedive')

# Known junk: compilations, playlists, non-artist results that TasteDive returns
_JUNK_KEYWORDS = [
    "kids", "children", "nursery", "compilation", "greatest hits",
    "karaoke", "soundtrack", "various", "top 40", "billboard", "radio hits",
    "vlog", "q&a", "history", "exposing", "reaction", "official trailer",
    "unboxing", "review", "tutorial", "how to", "gaming", "stream",
]

def _is_junk(name: str) -> bool:
    name_lower = name.lower()
    return any(k in name_lower for k in _JUNK_KEYWORDS)


class TasteDiveAPI:
    """
    Wrapper for TasteDive API.
    Handles case-insensitive JSON parsing and filters irrelevant results.
    """
    
    API_KEY = os.getenv("TASTEDIVE_API_KEY")
    BASE_URL = "https://tastedive.com/api/similar"
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    @staticmethod
    async def get_recommendations(query: str, type_val: str = "music", limit: int = 10) -> list[dict]:
        """
        Get similar items from TasteDive.
        Returns a list of dicts: [{'name': '...', 'yID': '...'}, ...]
        """
        api_key = TasteDiveAPI.API_KEY or os.getenv("TASTEDIVE_API_KEY")
        if not api_key:
            logger.warning("TasteDive API Key is missing!")
            return []

        params = {
            "q": query,
            "type": type_val,
            "info": 1,          # Need info=1 to get yID field
            "limit": limit,
            "k": api_key
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(TasteDiveAPI.BASE_URL, params=params, headers=TasteDiveAPI.HEADERS) as response:
                    if response.status != 200:
                        logger.error(f"TasteDive API Error: {response.status}")
                        return []
                    
                    data = await response.json()
                    
                    # Handle case sensitivity (Similar vs similar)
                    similar = data.get("Similar") or data.get("similar") or {}
                    results = similar.get("Results") or similar.get("results") or []
                    
                    return results
                    
            except Exception as e:
                logger.error(f"Error fetching TasteDive recommendations: {e}")
                return []

    @staticmethod
    async def get_recommendation_for_track(artist: str, track_title: str) -> tuple[str, str | None] | None:
        """
        High-level helper to get a recommendation for a specific track.
        Returns a tuple of (name, yID) where yID is a YouTube video ID, or None.
        Strategy:
          1. Query "Artist - Title" (most specific, best for songs)
          2. Fallback to "Artist" only
        """
        rec_items = []
        
        # 1. Try "Artist - Title" first — most specific, gives genre-matched results
        if artist and track_title:
            # Avoid "Artist - Artist - Song" if artist is already in title
            if artist.lower() in track_title.lower():
                specific_query = track_title
            else:
                specific_query = f"{artist} - {track_title}"
                
            logger.info(f"TasteDive: Querying '{specific_query}'")
            rec_items = await TasteDiveAPI.get_recommendations(specific_query, type_val="music")

        # 2. Fallback to Artist only
        if not rec_items and artist:
            logger.info(f"TasteDive: Falling back to artist query '{artist}'")
            rec_items = await TasteDiveAPI.get_recommendations(artist, type_val="music")
            
        if not rec_items:
            return None

        # Filter out junk results (compilations, karaoke, etc.)
        good_items = [r for r in rec_items if not _is_junk(r.get("name") or r.get("Name") or "")]
        
        # Use filtered results if we have them, otherwise use all
        pool = good_items if good_items else rec_items

        # Pick one random recommendation
        choice = random.choice(pool)
        name = choice.get("name") or choice.get("Name")
        # yID is a YouTube video ID linked to this artist/track — use it directly if available!
        y_id = choice.get("yID")
        
        logger.info(f"TasteDive: Picked '{name}' (yID={y_id}) from {len(pool)} candidates")
        return (name, y_id)
