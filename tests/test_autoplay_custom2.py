import asyncio
import logging
import random
import sys
import os

# Add parent directory to path to import core modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ytdl_source import YTDLSource

logging.basicConfig(level=logging.INFO)

class MockTrack:
    def __init__(self, title, uploader):
        self.title = title
        self.uploader = uploader

async def main():
    seed_title = "Bohemian Rhapsody"
    seed_uploader = "Queen"
    seed_url = "https://www.youtube.com/watch?v=fJ9rUzIMcZQ"
    
    current_track = MockTrack(seed_title, seed_uploader)
    
    print(f"=== SEED TRACK ===")
    print(f"Title: {current_track.title}")
    print(f"Artist/Uploader: {current_track.uploader}")
    print(f"URL: {seed_url}\n")
    
    # 1. Fetch related tracks (YouTube Baseline)
    print("Fetching related tracks from YouTube...")
    loop = asyncio.get_event_loop()
    related = await YTDLSource.get_related(seed_url, title=seed_title, loop=loop)
    
    if not related:
        print("No related tracks found!")
        return
        
    print(f"Found {len(related)} related tracks.\n")
    
    # Mode 1: YouTube (Random from related)
    print("=== MODE: YOUTUBE (Base) ===")
    print("Just picks a random track from the raw related list.")
    yt_sample = random.sample(related, min(3, len(related)))
    for i, t in enumerate(yt_sample):
        print(f"{i+1}. {t.get('title')}")
    print()
    
    # Mode 2: Custom 1 (Relevant)
    print("=== MODE: CUSTOM 1 (Relevant) ===")
    def score_video_custom1(video):
        score = random.uniform(0, 10)
        title = video.get('title', '').lower()
        
        current_uploader = current_track.uploader.lower()
        if current_uploader and len(current_uploader) > 2 and current_uploader in title:
             score += 5
             
        current_words = [w for w in current_track.title.lower().split() if len(w) > 3]
        match_count = sum(1 for w in current_words if w in title)
        score += match_count * 2
        return score
        
    custom1_list = list(related)
    custom1_list.sort(key=score_video_custom1, reverse=True)
    custom1_candidates = custom1_list[:3]
    for i, t in enumerate(custom1_candidates):
        print(f"{i+1}. {t.get('title')} (Top Candidate)")
    print(f"-> Chosen: {random.choice(custom1_candidates).get('title')}\n")
    
    # Mode 3: Custom 2 (Explorative)
    print("=== MODE: CUSTOM 2 (Explorative) ===")
    def score_video_custom2(video):
        score = random.uniform(0, 10)
        title = video.get('title', '').lower()
        
        current_uploader = current_track.uploader.lower()
        if current_uploader and len(current_uploader) > 2 and current_uploader in title:
             score += 5
             
        current_words = [w for w in current_track.title.lower().split() if len(w) > 3]
        match_count = sum(1 for w in current_words if w in title)
        score -= match_count * 2  # PENALIZE exact matches
        return score
        
    custom2_list = list(related)
    custom2_list.sort(key=score_video_custom2, reverse=True)
    custom2_candidates = custom2_list[:10]
    
    for i, t in enumerate(custom2_candidates[:5]): # show top 5 of 10
        print(f"{i+1}. {t.get('title')} (Top Candidate pool)")
    print(f"-> Chosen: {random.choice(custom2_candidates).get('title')}\n")

if __name__ == "__main__":
    asyncio.run(main())
