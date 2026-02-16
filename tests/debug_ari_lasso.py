import asyncio
import time
import os
import sys
import re
from dotenv import load_dotenv

# Load .env
load_dotenv(override=True)

# Adjust path to import utils
sys.path.append(os.getcwd())

from utils.genius_lyrics import search_lyrics, _clean_title, _extract_metadata, NOISE_KEYWORDS

def debug_cleaning(title):
    print(f"\n--- Debugging: '{title}' ---")
    
    real_cleaned = _clean_title(title)
    print(f"Real _clean_title output: '{real_cleaned}'")
    
    # 1. Cleaning steps simulation (manual trace) - keeping for reference if needed
    cleaned = title.lower()
    print(f"Lower: '{cleaned}'")
    
    # regex from utils
    cleaned = re.sub(r'\([^)]*\)', '', cleaned)
    cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)
    print(f"After () []: '{cleaned}'")
    
    # Use imported NOISE_KEYWORDS
    for word in NOISE_KEYWORDS:
        old = cleaned
        cleaned = re.sub(rf'\b{re.escape(word)}\b', '', cleaned)
        if old != cleaned:
            print(f"Removed '{word}': '{cleaned}'")
            
    cleaned = cleaned.replace('|', '-')
    # Missing handling for // in current code?
    # cleaned = cleaned.replace('//', '-') 
    
    print(f"After separators: '{cleaned}'")
    
    cleaned = re.sub(r'\b(feat|ft|featuring)\b.*', '', cleaned)
    
    cleaned = re.sub(r'\s*[-|]\s*$', '', cleaned)
    cleaned = re.sub(r'^\s*[-|]\s*', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    print(f"Final Cleaned: '{cleaned}'")
    
    metadata = _extract_metadata(cleaned)
    print(f"Metadata: {metadata}")
    
    return cleaned

async def run_search_debug():
    test_cases = [
        "Ari Lasso - Hampa // Lirik HQ"
    ]
    
    for query in test_cases:
        debug_cleaning(query)
        print("Searching Genius...")
        start = time.time()
        try:
            result = await search_lyrics(query)
            elapsed = time.time() - start
            if result:
                print(f"FOUND: {result['title']} by {result['artist']} ({elapsed:.2f}s)")
            else:
                print(f"NOT FOUND ({elapsed:.2f}s)")
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    with open("debug_ari_lasso.txt", "w", encoding="utf-8") as f:
        sys.stdout = f
        asyncio.run(run_search_debug())
        sys.stdout = sys.__stdout__
        
    print("Debug output written to debug_ari_lasso.txt")
