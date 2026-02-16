import asyncio
import time
import yt_dlp
import sys

# Standard Options
YTDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'cookiefile': 'cookies.txt',
}

QUERY = "ytsearch1:Never Gonna Give You Up"

async def benchmark_current_strategy():
    """
    Current: 
    1. Search with extract_flat=True
    2. Resolve specific URL (from_url)
    """
    start = time.time()
    
    # Step 1: Search Flat
    opts_search = YTDL_OPTS.copy()
    opts_search['extract_flat'] = True
    
    with yt_dlp.YoutubeDL(opts_search) as ydl:
        info = await asyncio.to_thread(ydl.extract_info, QUERY, download=False)
        entry = info['entries'][0]
        video_url = entry.get('url') # likely just ID or partial
        if not video_url: # Handle different versions
             video_url = f"https://www.youtube.com/watch?v={entry['id']}"

    mid = time.time()
    print(f"  [Current] Search (Flat) took: {mid - start:.2f}s")
    
    # Step 2: Resolve Full
    opts_resolve = YTDL_OPTS.copy()
    
    with yt_dlp.YoutubeDL(opts_resolve) as ydl:
        # Resolving the specific URL found
        await asyncio.to_thread(ydl.extract_info, video_url, download=False)
        
    end = time.time()
    print(f"  [Current] Resolve took: {end - mid:.2f}s")
    print(f"  [Current] Total: {end - start:.2f}s")

async def benchmark_proposed_strategy():
    """
    Proposed:
    1. Search with extract_flat=False (Full extraction immediately)
    """
    start = time.time()
    
    opts_full = YTDL_OPTS.copy()
    opts_full['extract_flat'] = False # Default regarding setting
    
    with yt_dlp.YoutubeDL(opts_full) as ydl:
        await asyncio.to_thread(ydl.extract_info, QUERY, download=False)
        
    end = time.time()
    print(f"  [Proposed] Total (Full Search): {end - start:.2f}s")

async def main():
    print("Benchmarking Pipelines...\n")
    
    print("Running Current Strategy...")
    try:
        await benchmark_current_strategy()
    except Exception as e:
        print(f"Current failed: {e}")

    print("\nRunning Proposed Strategy...")
    try:
        await benchmark_proposed_strategy()
    except Exception as e:
        print(f"Proposed failed: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
