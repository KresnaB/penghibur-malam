import os
import logging
import aiohttp
import urllib.parse
import random
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger('antigrafity.tastedive')

class TasteDiveAPI:
    """
    Wrapper for TasteDive API.
    Handles case-insensitive JSON parsing (API sometimes returns 'Similar' vs 'similar').
    """
    
    API_KEY = os.getenv("TASTEDIVE_API_KEY")
    BASE_URL = "https://tastedive.com/api/similar"
    
    # TasteDive might require a User-Agent to return valid JSON results
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    @staticmethod
    async def get_recommendations(query: str, type_val: str = "music", limit: int = 5) -> list[dict]:
        """
        Get similar items from TasteDive.
        Returns a list of dicts: [{'Name': '...', 'yID': '...'}, ...]
        """
        api_key = TasteDiveAPI.API_KEY or os.getenv("TASTEDIVE_API_KEY")
        if not api_key:
             logger.warning("TasteDive API Key is missing! recommendations will fail.")
             return []

        params = {
            "q": query,
            "type": type_val,
            "info": 1,
            "limit": limit,
            "k": api_key
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(TasteDiveAPI.BASE_URL, params=params, headers=TasteDiveAPI.HEADERS) as response:
                    if response.status != 200:
                        logger.error(f"TasteDive API Error: {response.status} - {await response.text()}")
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
    async def get_recommendation_for_track(artist: str, track_title: str) -> str | None:
        """
        High-level helper to get a recommendation query for a specific track.
        Tries to search by 'Artist' first (TasteDive is better with bands).
        Returns a query string suitable for YouTube search (e.g. 'Artist - Song').
        """
        # TasteDive works best with Artist names or Movie titles.
        # Searching "Linkin Park" is better than "Numb Linkin Park".
        
        rec_items = []
        
        # 1. Try Full Track Query first (Better relevance)
        # "Joji - Slow Dancing in the Dark" gives better results than just "Joji"
        full_query = f"{artist} {track_title}"
        logger.info(f"TasteDive: Searching similar to '{full_query}'")
        rec_items = await TasteDiveAPI.get_recommendations(full_query, type_val="music")

        # 2. Fallback to Artist Search if specific song fails
        if not rec_items and artist:
            logger.info(f"TasteDive: No results for song, falling back to artist '{artist}'")
            rec_items = await TasteDiveAPI.get_recommendations(artist, type_val="music")
            
        if not rec_items:
            return None
            
        # Pick one random recommendation
        choice = random.choice(rec_items)
        name = choice.get("Name") or choice.get("name")
        
        # If it has a YouTube ID/Teaser, that's great, but we still prefer searching YT
        # ourselves to get the best audio stream, unless we trust yID.
        # But yID from TasteDive might be old/dead.
        # Safe bet: Return the Name, let MusicPlayer search it.
        
        return name
