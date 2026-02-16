import asyncio
import sys
import os
from dotenv import load_dotenv

sys.path.append(os.getcwd())
load_dotenv(override=True)

from utils.genius_lyrics import _clean_title, search_lyrics

TEST_CASES = [
    "Luka Disini - UNGU | Waktu Yang Dinanti 2.0",
    "UNGU - Aku Bukan Pilihan Hatimu | UNGUofficial",
    "ACHA SEPTRIASA & IRWANSYAH - My Heart (Official Music Video)"
]

async def debug():
    print("--- Debugging New Cases ---")
    for title in TEST_CASES:
        print(f"\nOriginal: '{title}'")
        cleaned = _clean_title(title)
        print(f"Cleaned : '{cleaned}'")
        
        print("Searching...")
        res = await search_lyrics(title)
        if res:
            print(f"FOUND: {res['title']} by {res['artist']}")
        else:
            print("NOT FOUND")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(debug())
