
import re

def _clean_title(title: str) -> str:
    """
    Clean a YouTube video title for better Genius search results.
    """
    # Remove common YouTube tags
    patterns = [
        r'\(Official\s*(Music\s*)?Video\)',
        r'\(Official\s*Audio\)',
        r'\(Lyric\s*Video\)',
        r'\(Lyrics?\)',
        r'\(Visualizer\)',
        r'\(Audio\)',
        r'\(Live\)',
        r'\[Official\s*(Music\s*)?Video\]',
        r'\[Official\s*Audio\]',
        r'\[Lyric\s*Video\]',
        r'\[Lyrics?\]',
        r'\[Visualizer\]',
        r'\[Audio\]',
        r'\[Live\]',
        r'\bMV\b',
        r'\bM/V\b',
        r'\bHD\b',
        r'\b4K\b',
        r'\bofficial\b',
        r'\blyrics?\b',
        r'\bvideo\b',
        r'\(Original\s*Soundtrack\s*(from)?.*?\)',
        r'\(OST.*?\)',
        r'\(Duet\s*Version\)',
        r'\(Acoustic\s*Version\)',
        r'\(Remix\)',
        r'\(Cover\)',
        r'with\s+Lyrics',
    ]
    cleaned = title
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    # Remove extra whitespace and trailing dashes/pipes
    cleaned = re.sub(r'\s*[-|]\s*$', '', cleaned)
    cleaned = re.sub(r'^\s*[-|]\s*', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    return cleaned if cleaned else title

def _extract_metadata(query: str) -> dict:
    """
    Attempt to extract artist and title from a query string.
    Returns dict with 'artist' and 'title' if successful, else content is just 'query'.
    """
    # Common separators: " - ", " : ", " | "
    separators = [r'\s-\s', r'\s:\s', r'\s\|\s']
    
    for sep in separators:
        parts = re.split(sep, query, maxsplit=1)
        if len(parts) == 2:
            return {'artist': parts[0].strip(), 'title': parts[1].strip()}
            
    return {'title': query.strip()}

test_cases = [
    "Bruno Mars - That’s What I Like [Official Music Video]",
    "Lady Gaga, Bruno Mars - Die With A Smile",
    "Coldplay - Yellow (Official Video)",
    "Linkin Park - Numb [Official Music Video]",
    "Ed Sheeran - Shape of You [Official Video]",
    "Luis Fonsi - Despacito ft. Daddy Yankee",
    "Mark Ronson - Uptown Funk (Official Video) ft. Bruno Mars",
    "Clean Bandit - Rockabye (feat. Sean Paul & Anne-Marie) [Official Video]",
    "Die With A Smile - Lady Gaga, Bruno Mars",
    "Selalu Ada di Nadimu (Original Soundtrack From “JUMBO\")",
    "Tak Ingin Usai (Duet Version)"
]

print(f"{'Original':<70} | {'Cleaned':<50} | {'Extracted':<50}")
print("-" * 180)
for title in test_cases:
    cleaned = _clean_title(title)
    extracted = _extract_metadata(cleaned)
    print(f"{title:<70} | {cleaned:<50} | {extracted}")
