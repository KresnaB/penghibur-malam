import os
import logging
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

logger = logging.getLogger('antigrafity.spotify')

class SpotifyClient:
    def __init__(self):
        self.client_id = os.getenv('SPOTIFY_CLIENT_ID')
        self.client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
        self.sp = None
        
        if self.client_id and self.client_secret:
            try:
                auth_manager = SpotifyClientCredentials(
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
                self.sp = spotipy.Spotify(auth_manager=auth_manager)
                logger.info("Spotify client initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Spotify client: {e}")
        else:
            logger.warning("Spotify credentials not found in .env.")

    async def get_recommendation(self, query: str) -> str | None:
        """
        Get a recommendation based on a track query (Title - Artist).
        Returns a string "Artist - Title" for the recommended track.
        """
        if not self.sp:
             return None

        try:
            # Run blocking Spotify calls in executor
            loop = asyncio.get_event_loop()
            
            # 1. Search for the seed track
            result = await loop.run_in_executor(
                None, 
                lambda: self.sp.search(q=query, type='track', limit=1)
            )
            
            if not result['tracks']['items']:
                logger.info(f"Spotify: No track found for query '{query}'")
                return None
                
            seed_track = result['tracks']['items'][0]
            seed_id = seed_track['id']
            seed_name = f"{seed_track['artists'][0]['name']} - {seed_track['name']}"
            logger.info(f"Spotify: Found seed track '{seed_name}' ({seed_id})")

            # 2. Get recommendations
            recommendations = await loop.run_in_executor(
                None,
                lambda: self.sp.recommendations(seed_tracks=[seed_id], limit=1)
            )

            if not recommendations['tracks']:
                logger.info("Spotify: No recommendations found.")
                return None

            rec_track = recommendations['tracks'][0]
            rec_string = f"{rec_track['artists'][0]['name']} - {rec_track['name']}"
            logger.info(f"Spotify: Recommended '{rec_string}'")
            
            return rec_string

        except Exception as e:
            logger.error(f"Spotify API error: {e}")
            return None
