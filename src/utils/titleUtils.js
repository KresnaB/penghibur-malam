const NOISE_KEYWORDS = [
  "official music video",
  "music video",
  "official video",
  "lyric video",
  "official audio",
  "audio video",
  "video clip",
  "official",
  "video",
  "audio",
  "lyrics",
  "lyric",
  "lirik",
  "hd",
  "4k",
  "mv",
  "hq",
  "visualizer",
  "remastered",
  "live",
  "version",
  "edit",
  "explicit",
  "clean",
];

export function cleanTitle(title) {
  if (!title) return "";
  const original = title;
  let cleaned = title.toLowerCase();
  cleaned = cleaned.replace(/\([^)]*\)/g, "").replace(/\[[^\]]*]/g, "");
  if (cleaned.includes("|")) {
    cleaned = cleaned.split("|")[0];
  }
  cleaned = cleaned.replace(/\s+&\s+/g, " and ");
  for (const word of NOISE_KEYWORDS) {
    cleaned = cleaned.replace(new RegExp(`\\b${escapeRegExp(word)}\\b`, "g"), "");
  }
  cleaned = cleaned.replace(/\b(feat|ft|featuring)\b.*/g, "");
  cleaned = cleaned.replace(/\b(v?\d+(\.\d+)?)\s*$/g, "");
  cleaned = cleaned.replace(/\/\//g, "-");
  cleaned = cleaned.replace(/\s*[-|]\s*$/g, "").replace(/^\s*[-|]\s*/g, "");
  cleaned = cleaned.replace(/\s+/g, " ").trim();
  return cleaned || original;
}

export function extractMetadata(query) {
  const separators = [/\s-\s/, /\s*:\s*/, /\s*\|\s*/];
  for (const separator of separators) {
    const parts = query.split(separator);
    if (parts.length >= 2) {
      return { artist: parts[0].trim(), title: parts.slice(1).join(" ").trim() };
    }
  }
  return { title: query.trim() };
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
