import { getLyrics, getSong } from "genius-lyrics-api";
import { cleanTitle, extractMetadata } from "./titleUtils.js";

export async function searchGeniusLyrics(query) {
  const apiKey = process.env.GENIUS_ACCESS_TOKEN;
  if (!apiKey) {
    return null;
  }
  const cleaned = cleanTitle(query);
  const metadata = extractMetadata(cleaned);
  const options = {
    apiKey,
    title: metadata.title || cleaned,
    artist: metadata.artist || "",
    optimizeQuery: true,
  };

  let lyrics = null;
  try {
    lyrics = await getLyrics(options);
  } catch {
    lyrics = null;
  }
  if (!lyrics) {
    return null;
  }

  let song = null;
  try {
    song = await getSong(options);
  } catch {
    song = null;
  }

  return {
    title: song?.title || metadata.title || cleaned,
    artist: song?.artist || metadata.artist || "",
    lyrics,
    syncedLyrics: null,
    url: song?.url || null,
    thumbnail: song?.albumArt || null,
    source: "Genius",
  };
}

export function splitLyrics(lyrics, maxLength = 4096) {
  if (!lyrics || lyrics.length <= maxLength) return [lyrics];
  const lines = lyrics.split("\n");
  const chunks = [];
  let current = "";
  for (const line of lines) {
    if ((current + line + "\n").length > maxLength) {
      chunks.push(current.trim());
      current = `${line}\n`;
    } else {
      current += `${line}\n`;
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}
