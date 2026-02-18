
import asyncio
import logging
from typing import Optional
from utils.genius_lyrics import search_lyrics as search_genius
from utils.lrclib_lyrics import get_lyrics as get_lrclib

logger = logging.getLogger('antigrafity.lyrics_service')

async def get_lyrics_concurrently(query: str, duration: int = None, loop: asyncio.AbstractEventLoop = None) -> Optional[dict]:
    """
    Race Lrclib and Genius to get lyrics.
    Returns the result from the first provider to respond with valid data.
    """
    loop = loop or asyncio.get_event_loop()
    
    # Create tasks
    task_lrclib = asyncio.create_task(get_lrclib(query, duration))
    task_genius = asyncio.create_task(search_genius(query, loop=loop))
    
    pending = {task_lrclib, task_genius}
    
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        
        for task in done:
            try:
                result = task.result()
                if result:
                    # Valid result found!
                    logger.info(f"Lyrics race won by: {result.get('source', 'Unknown')}")
                    
                    # Cancel remaining tasks
                    for p in pending:
                        p.cancel()
                        
                    return result
            except Exception as e:
                logger.error(f"Lyrics task failed: {e}")
                
    logger.info("Lyrics race finished: No lyrics found from any source.")
    return None
