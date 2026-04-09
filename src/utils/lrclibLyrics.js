import { cleanTitle, extractMetadata } from "./titleUtils.js";

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    return { ok: false, status: response.status, data: null };
  }
  return { ok: true, status: response.status, data: await response.json() };
}

export async function getLrclibLyrics(query, duration = null) {
  const cleaned = cleanTitle(query);
  const metadata = extractMetadata(cleaned);
  const params = new URLSearchParams({ track_name: metadata.title || cleaned });
  if (metadata.artist) params.set("artist_name", metadata.artist);
  if (duration) params.set("duration", String(duration));

  const exact = await fetchJson(`https://lrclib.net/api/get?${params.toString()}`);
  if (exact.ok && exact.data && (exact.data.plainLyrics || exact.data.syncedLyrics)) {
    return formatLrclib(exact.data);
  }

  const searchQuery = metadata.artist ? `${metadata.artist} ${metadata.title}` : metadata.title || cleaned;
  const search = await fetchJson(`https://lrclib.net/api/search?q=${encodeURIComponent(searchQuery)}`);
  if (!search.ok || !Array.isArray(search.data) || !search.data.length) {
    return null;
  }
  let best = search.data[0];
  if (duration) {
    const matched = search.data.find((item) => Math.abs((item.duration || 0) - duration) <= 5);
    if (matched) best = matched;
  }
  return formatLrclib(best);
}

function formatLrclib(data) {
  return {
    title: data.trackName,
    artist: data.artistName,
    lyrics: data.plainLyrics,
    syncedLyrics: null,
    url: null,
    thumbnail: null,
    source: "Lrclib",
  };
}
