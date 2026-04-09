import { RADIO_BROWSER_BASES } from "../config.js";

export const RADIO_PAGE_SIZE = 10;

export const RADIO_CATEGORY_PRESETS = {
  genre: {
    label: "Genre",
    description: "Pop, rock, jazz, lo-fi, EDM, dan lainnya.",
    queries: ["pop", "rock", "jazz", "lofi", "edm", "classical", "hip hop", "indie"].map((value) => ({ kind: "tag", value })),
  },
  mood: {
    label: "Mood",
    description: "Stasiun santai, fokus, chill, dan study.",
    queries: ["chill", "relax", "ambient", "study", "focus", "sleep", "feel good"].map((value) => ({ kind: "tag", value })),
  },
  news: {
    label: "News / Talk",
    description: "Berita, talk show, dan program obrolan.",
    queries: ["news", "talk", "sports", "business", "podcast"].map((value) => ({ kind: "tag", value })),
  },
  local: {
    label: "Local",
    description: "Radio dari Indonesia dan negara sekitar.",
    queries: ["ID", "MY", "SG", "PH"].map((value) => ({ kind: "country", value })),
  },
  lainnya: {
    label: "Lainnya",
    description: "Oldies, world, instrumental, dan opsi tambahan.",
    queries: ["oldies", "world", "instrumental", "kpop", "jpop", "latin"].map((value) => ({ kind: "tag", value })),
  },
};

export class RadioBrowserClient {
  constructor(bases = RADIO_BROWSER_BASES) {
    this.bases = bases;
  }

  async fetchCategory(categoryKey, limit = RADIO_PAGE_SIZE * 3) {
    const category = RADIO_CATEGORY_PRESETS[categoryKey];
    if (!category) return [];
    const stations = [];
    const seen = new Set();
    for (const query of category.queries) {
      const path = this.buildPath(query);
      let items = [];
      try {
        items = await this.requestJson(path);
      } catch {
        items = [];
      }
      if (!Array.isArray(items)) continue;
      for (const item of items) {
        const station = this.normalizeStation(item);
        if (!station) continue;
        const key = station.uuid || station.stream_url;
        if (seen.has(key)) continue;
        seen.add(key);
        stations.push(station);
        if (stations.length >= limit) return stations;
      }
    }
    return stations;
  }

  async requestJson(path) {
    let lastError = null;
    for (const base of this.bases) {
      try {
        const response = await fetch(`${base}${path}`, {
          headers: {
            "user-agent": "OmniaMusicBot/2.0 (+https://discord.com)",
            accept: "application/json",
          },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError) throw lastError;
    return [];
  }

  buildPath(query) {
    const value = encodeURIComponent(String(query.value || "").trim());
    if (query.kind === "country") {
      return `/json/stations/bycountrycodeexact/${value}?hidebroken=true&order=clickcount&reverse=true&limit=10`;
    }
    return `/json/stations/bytag/${value}?hidebroken=true&order=clickcount&reverse=true&limit=10`;
  }

  normalizeStation(item) {
    const streamUrl = String(item.url_resolved || item.url || "").trim();
    if (!streamUrl) return null;
    const tags = String(item.tags || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const country = String(item.country || "").trim();
    const countryCode = String(item.countrycode || "").trim();
    const language = String(item.language || "").trim();
    const codec = String(item.codec || "").trim().toUpperCase();
    const bitrate = item.bitrate || 0;
    const details = [];
    if (country || countryCode) details.push(country || countryCode);
    if (language) details.push(language);
    if (codec) details.push(codec);
    if (bitrate) details.push(`${bitrate} kbps`);
    if (tags.length) details.push(tags.slice(0, 3).join(", "));
    return {
      uuid: String(item.stationuuid || "").trim(),
      name: String(item.name || "Unknown Station").trim(),
      stream_url: streamUrl,
      homepage: String(item.homepage || "").trim(),
      favicon: String(item.favicon || "").trim(),
      tags,
      country,
      country_code: countryCode,
      language,
      codec,
      bitrate,
      description: (details.join(" • ") || "Radio stream").slice(0, 100),
    };
  }
}
