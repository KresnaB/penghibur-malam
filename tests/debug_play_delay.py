import asyncio
import sys
import os
from dotenv import load_dotenv

sys.path.append(os.getcwd())
load_dotenv(override=True)

from core.ytdl_source import YTDLSource

async def debug_play_logic():
    query = "Never Gonna Give You Up"
    print(f"Testing get_info for query: '{query}'")
    
    # Simulate what Music.play does
    entries, playlist_title = await YTDLSource.get_info(query)
    
    print(f"Playlist Title: '{playlist_title}'") # If this is not None, cogs/music.py treats it as playlist
    
    if entries:
        entry = entries[0]
        url = entry.get('url', 'NO URL')
        print(f"Entry URL start: {url[:50]}...")
        if 'googlevideo' in url:
            print("  -> This is a STREAM URL (Good!)")
        elif 'youtube.com' in url or 'youtu.be' in url:
             print("  -> This is a WEBPAGE URL (Bad if full extraction used)")
        
        # Simulate cogs/music.py logic
        # source_url = entry.get('url', '') if not playlist_title else ''
        
        simulated_source_url = entry.get('url', '') if not playlist_title else ''
        print(f"Simulated source_url in cogs/music.py: '{simulated_source_url}'")
        
        if not simulated_source_url:
             print("❌ cogs/music.py CLEARED the URL! This causes double extraction.")
        else:
             print("✅ cogs/music.py kept the URL.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(debug_play_logic())
