"""
Radio Browser helper for browsing live internet radio stations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger("omnia.radio")

RADIO_BROWSER_BASES = [
    base.strip().rstrip("/")
    for base in os.getenv("RADIO_BROWSER_BASES", "https://de1.api.radio-browser.info").split(",")
    if base.strip()
]

RADIO_PAGE_SIZE = 10

RADIO_CATEGORY_PRESETS: dict[str, dict] = {
    "genre": {
        "label": "Genre",
        "description": "Pop, rock, jazz, lo-fi, EDM, dan lainnya.",
        "queries": [
            {"kind": "tag", "value": "pop"},
            {"kind": "tag", "value": "rock"},
            {"kind": "tag", "value": "jazz"},
            {"kind": "tag", "value": "lofi"},
            {"kind": "tag", "value": "edm"},
            {"kind": "tag", "value": "classical"},
            {"kind": "tag", "value": "hip hop"},
            {"kind": "tag", "value": "indie"},
        ],
    },
    "mood": {
        "label": "Mood",
        "description": "Stasiun santai, fokus, chill, dan study.",
        "queries": [
            {"kind": "tag", "value": "chill"},
            {"kind": "tag", "value": "relax"},
            {"kind": "tag", "value": "ambient"},
            {"kind": "tag", "value": "study"},
            {"kind": "tag", "value": "focus"},
            {"kind": "tag", "value": "sleep"},
            {"kind": "tag", "value": "feel good"},
        ],
    },
    "news": {
        "label": "News / Talk",
        "description": "Berita, talk show, dan program obrolan.",
        "queries": [
            {"kind": "tag", "value": "news"},
            {"kind": "tag", "value": "talk"},
            {"kind": "tag", "value": "sports"},
            {"kind": "tag", "value": "business"},
            {"kind": "tag", "value": "podcast"},
        ],
    },
    "local": {
        "label": "Local",
        "description": "Radio dari Indonesia dan negara sekitar.",
        "queries": [
            {"kind": "country", "value": "ID"},
            {"kind": "country", "value": "MY"},
            {"kind": "country", "value": "SG"},
            {"kind": "country", "value": "PH"},
        ],
    },
    "lainnya": {
        "label": "Lainnya",
        "description": "Oldies, world, instrumental, dan opsi tambahan.",
        "queries": [
            {"kind": "tag", "value": "oldies"},
            {"kind": "tag", "value": "world"},
            {"kind": "tag", "value": "instrumental"},
            {"kind": "tag", "value": "kpop"},
            {"kind": "tag", "value": "jpop"},
            {"kind": "tag", "value": "latin"},
        ],
    },
}


class RadioBrowserClient:
    """Minimal client for fetching radio stations from Radio Browser."""

    def __init__(self, bases: list[str] | None = None):
        self.bases = bases or RADIO_BROWSER_BASES

    async def fetch_category(self, category_key: str, *, limit: int = 30) -> list[dict]:
        """Fetch and normalize stations for a named category."""
        category = RADIO_CATEGORY_PRESETS.get(category_key)
        if not category:
            return []

        stations: list[dict] = []
        seen: set[str] = set()

        for query in category.get("queries", []):
            path = self._build_path(query)
            try:
                items = await self._request_json(path)
            except Exception as e:
                logger.warning("Radio Browser request failed for %s: %s", path, e)
                continue

            if not isinstance(items, list):
                continue

            for item in items:
                station = self.normalize_station(item)
                if not station:
                    continue

                key = station["uuid"] or station["stream_url"]
                if key in seen:
                    continue

                seen.add(key)
                stations.append(station)
                if len(stations) >= limit:
                    return stations

        return stations

    async def _request_json(self, path: str):
        """Fetch JSON data from one of the configured API bases."""
        last_error: Exception | None = None
        for base in self.bases:
            url = f"{base}{path}"
            try:
                return await asyncio.get_event_loop().run_in_executor(None, lambda: self._fetch(url))
            except Exception as e:
                last_error = e
                continue

        if last_error is not None:
            raise last_error
        return []

    def _fetch(self, url: str):
        """Blocking HTTP request used by the thread pool."""
        request = Request(
            url,
            headers={
                "User-Agent": "OmniaMusicBot/1.0 (+https://discord.com)",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
        return json.loads(payload)

    @staticmethod
    def _build_path(query: dict) -> str:
        kind = query.get("kind")
        value = quote(str(query.get("value", "")).strip(), safe="")

        if kind == "country":
            return f"/json/stations/bycountrycodeexact/{value}?hidebroken=true&order=clickcount&reverse=true&limit=10"

        return f"/json/stations/bytag/{value}?hidebroken=true&order=clickcount&reverse=true&limit=10"

    @staticmethod
    def normalize_station(item: dict) -> dict | None:
        """Convert raw Radio Browser payload into a compact station record."""
        stream_url = str(item.get("url_resolved") or item.get("url") or "").strip()
        if not stream_url:
            return None

        name = str(item.get("name") or "Unknown Station").strip()
        homepage = str(item.get("homepage") or "").strip()
        favicon = str(item.get("favicon") or "").strip()
        tags = [tag.strip() for tag in str(item.get("tags") or "").split(",") if tag.strip()]
        country = str(item.get("country") or "").strip()
        country_code = str(item.get("countrycode") or "").strip()
        language = str(item.get("language") or "").strip()
        codec = str(item.get("codec") or "").strip().upper()
        bitrate = item.get("bitrate") or 0
        uuid = str(item.get("stationuuid") or "").strip()

        desc_bits = []
        if country or country_code:
            desc_bits.append(country or country_code)
        if language:
            desc_bits.append(language)
        if codec:
            desc_bits.append(codec)
        if bitrate:
            desc_bits.append(f"{bitrate} kbps")
        if tags:
            desc_bits.append(", ".join(tags[:3]))

        description = " • ".join(desc_bits) if desc_bits else "Radio stream"
        if len(description) > 100:
            description = description[:97] + "..."

        return {
            "uuid": uuid,
            "name": name,
            "stream_url": stream_url,
            "homepage": homepage,
            "favicon": favicon,
            "tags": tags,
            "country": country,
            "country_code": country_code,
            "language": language,
            "codec": codec,
            "bitrate": bitrate,
            "description": description,
        }
