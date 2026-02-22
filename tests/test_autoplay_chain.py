import asyncio
import logging
import random
import sys
import os

# Add parent directory to path to import core modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ytdl_source import YTDLSource

logging.basicConfig(level=logging.WARNING) # Reduce noise

class MockTrack:
    def __init__(self, title, uploader, url):
        self.title = title
        self.uploader = uploader
        self.url = url

async def test_chain(mode_name, seed_track, chain_length=5):
    print(f"\n{'='*10} CHAIN MODE: {mode_name} {'='*10}")
    
    current_track = seed_track
    history = [current_track.url]
    
    for step in range(1, chain_length + 1):
        print(f"\n--- Step {step} ---")
        print(f"Current: {current_track.title} ({current_track.uploader})")
        
        # Fetch related
        related = await YTDLSource.get_related(current_track.url, title=current_track.title)
        
        if not related:
            print("No related tracks found! Chain broken.")
            break
            
        # Filter history
        fresh = [r for r in related if r.get('url') not in history]
        if not fresh:
            print("All related tracks already played. Using full list.")
            fresh = related
            
        chosen = None
        
        if mode_name == "YOUTUBE":
            chosen = random.choice(fresh)
            
        elif mode_name == "CUSTOM 1":
            def score_custom1(video):
                score = random.uniform(0, 10)
                title = video.get('title', '').lower()
                current_uploader = current_track.uploader.lower()
                if current_uploader and len(current_uploader) > 2 and current_uploader in title:
                     score += 5
                current_words = [w for w in current_track.title.lower().split() if len(w) > 3]
                match_count = sum(1 for w in current_words if w in title)
                score += match_count * 2
                return score
                
            fresh.sort(key=score_custom1, reverse=True)
            candidates = fresh[:3]
            chosen = random.choice(candidates)
            
        elif mode_name == "CUSTOM 2":
            def score_custom2(video):
                score = random.uniform(0, 10)
                title = video.get('title', '').lower()
                current_uploader = current_track.uploader.lower()
                if current_uploader and len(current_uploader) > 2 and current_uploader in title:
                     score += 5
                current_words = [w for w in current_track.title.lower().split() if len(w) > 3]
                match_count = sum(1 for w in current_words if w in title)
                score -= match_count * 2  # Penalize similarities
                return score
                
            fresh.sort(key=score_custom2, reverse=True)
            candidates = fresh[:10]  # Wider pool
            if candidates:
                chosen = random.choice(candidates)
            else:
                 chosen = random.choice(fresh)

        if chosen:
             print(f"Next ⏭️ : {chosen.get('title')}")
             # Update for next iteration
             next_url = chosen.get('url')
             history.append(next_url)
             
             # Extract basic info for the next track's "uploader" approximation
             # We just use the title to emulate the next search since we don't full extract to save time
             current_track = MockTrack(chosen.get('title'), "", next_url)
        else:
             print("Failed to choose track.")
             break

async def main():
    seed_title = "Bohemian Rhapsody"
    seed_uploader = "Queen"
    seed_url = "https://www.youtube.com/watch?v=fJ9rUzIMcZQ"
    
    seed = MockTrack(seed_title, seed_uploader, seed_url)
    
    print(f"Seed Track: {seed.title} by {seed.uploader}")
    
    await test_chain("YOUTUBE", seed, chain_length=5)
    await test_chain("CUSTOM 1", seed, chain_length=5)
    await test_chain("CUSTOM 2", seed, chain_length=5)

if __name__ == "__main__":
    asyncio.run(main())
