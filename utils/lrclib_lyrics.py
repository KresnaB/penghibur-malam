
import aiohttp
import logging
from utils.genius_lyrics import clean_title, extract_metadata

logger = logging.getLogger('omnia.lrclib')

async def get_lyrics(query: str, duration: int = None) -> dict | None:
    """
    Fetch lyrics from Lrclib API.
    Prioritizes synced lyrics.
    Returns dict with 'lyrics', 'syncedLyrics', 'title', 'artist', 'url' (if applicable) or None.
    """
    
    # 1. Clean title and extract metadata
    cleaned_query = clean_title(query)
    metadata = extract_metadata(cleaned_query)
    
    track_name = metadata.get('title', cleaned_query)
    artist_name = metadata.get('artist')

    # 2. Build parameters for /api/get
    params = {
        'track_name': track_name,
    }
    if artist_name:
        params['artist_name'] = artist_name
    if duration:
        params['duration'] = duration

    logger.info(f"Lrclib fetching: {params}")

    async with aiohttp.ClientSession() as session:
        try:
            # Try precise match first
            async with session.get('https://lrclib.net/api/get', params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Check if we got valid lyrics
                    if data and (data.get('plainLyrics') or data.get('syncedLyrics')):
                        return _format_response(data)
                elif resp.status == 404:
                    logger.info("Lrclib /api/get not found. Trying search...")
                else:
                    logger.warning(f"Lrclib /api/get failed with {resp.status}")

            # Fallback: Search API
            # If precise match failed, try searching
            search_params = {'q': f"{artist_name} {track_name}" if artist_name else track_name}
            async with session.get('https://lrclib.net/api/search', params=search_params) as resp:
                if resp.status == 200:
                    results = await resp.json()
                    if results and isinstance(results, list):
                        # Filter results by duration if available (allow +/- 5 seconds difference)
                        best_match = None
                        if duration:
                            for res in results:
                                if abs(res.get('duration', 0) - duration) <= 5:
                                    best_match = res
                                    break
                        
                        # If no duration match or no duration provided, take the first one
                        if not best_match and results:
                            best_match = results[0]

                        if best_match:
                             return _format_response(best_match)
        
        except Exception as e:
            logger.error(f"Lrclib error: {e}")
            return None

    return None

def _format_response(data: dict) -> dict:
    """Standardize response. User requested PLAIN lyrics only."""
    return {
        'title': data.get('trackName'),
        'artist': data.get('artistName'),
        'lyrics': data.get('plainLyrics'),
        'syncedLyrics': None, # User requested plain lyrics only
        'url': None, 
        'thumbnail': None,
        'source': 'Lrclib'
    }
