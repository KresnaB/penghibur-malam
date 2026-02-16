
import yt_dlp
import time
import json

URL = "https://www.youtube.com/watch?v=PMivT7MJ41M"
QUERY = "ytsearch1:That's what i like bruno mars"

def test_extraction(name, opts, query):
    print(f"--- Testing {name} ---")
    start = time.time()
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            data = ydl.extract_info(query, download=False)
            elapsed = time.time() - start
            
            if 'entries' in data:
                print(f"Got playlist/search results: {len(data['entries'])}")
                entry = data['entries'][0]
            else:
                entry = data
                
            print(f"Time: {elapsed:.2f}s")
            print(f"Title: {entry.get('title')}")
            print(f"ID: {entry.get('id')}")
            print(f"URL: {entry.get('url')}")
            print(f"Duration: {entry.get('duration')}")
            print(f"Thumbnail: {entry.get('thumbnail')}")
            print(f"Uploader: {entry.get('uploader')}")
            print(f"Formats present: {'formats' in entry}")
        except Exception as e:
            print(f"Error: {e}")

# Base options
base_opts = {
    'quiet': True, 
    'no_warnings': True,
    'extract_flat': False
}

# Test 1: Full extraction (Current behavior)
print("1. Full Extraction (URL)")
test_extraction("Full URL", base_opts, URL)

print("\n2. Full Extraction (Search)")
test_extraction("Full Search", base_opts, QUERY)

# Test 2: Flat extraction
flat_opts = base_opts.copy()
flat_opts['extract_flat'] = True

print("\n3. Flat Extraction (URL)")
test_extraction("Flat URL", flat_opts, URL)

print("\n4. Flat Extraction (Search)")
test_extraction("Flat Search", flat_opts, QUERY)
