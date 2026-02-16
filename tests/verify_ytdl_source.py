
import asyncio
import sys
import os
import time

# Ensure we can import from core
sys.path.append(os.getcwd())

from core.ytdl_source import YTDLSource

async def test_search():
    query = "Bruno Mars - That’s What I Like"
    print(f"Testing search for: {query}")
    
    start = time.time()
    try:
        entries, playlist_title = await YTDLSource.get_info(query)
        elapsed = time.time() - start
        
        print(f"Time: {elapsed:.2f}s")
        if entries:
            entry = entries[0]
            print(f"Title: {entry.get('title')}")
            print(f"URL: {entry.get('url')}")
            print(f"Thumbnail: {entry.get('thumbnail')}")
            print(f"Is constructed URL? {'youtube.com/watch' in entry.get('url', '')}")
            print(f"Is constructed Thumb? {'i.ytimg.com' in entry.get('thumbnail', '')}")
        else:
            print("No entries found.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_search())
