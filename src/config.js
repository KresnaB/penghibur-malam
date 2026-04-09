import path from "node:path";

export const ROOT_DIR = process.cwd();
export const DATA_DIR = path.join(ROOT_DIR, "data");
export const PLAYLISTS_PATH = path.join(DATA_DIR, "playlists.json");
export const COOKIE_FILE = process.env.YTDLP_COOKIEFILE || path.join(ROOT_DIR, "cookies.txt");
export const POT_PROVIDER_URL = (process.env.POT_PROVIDER_URL || "http://pot-provider:4416").replace(/\/+$/, "");
export const RADIO_BROWSER_BASES = (process.env.RADIO_BROWSER_BASES || "https://de1.api.radio-browser.info")
  .split(",")
  .map((value) => value.trim().replace(/\/+$/, ""))
  .filter(Boolean);
export const CHAT_CLEANUP_DELAY_MS = 20_000;
export const IDLE_TIMEOUT_MS = 180_000;
export const DEBUG_MEMORY = ["1", "true", "yes", "on"].includes((process.env.DEBUG_MEMORY || "").trim().toLowerCase());
export const DEBUG_MEMORY_INTERVAL_MS = Number.parseInt(process.env.DEBUG_MEMORY_INTERVAL || "600", 10) * 1000;

export const YTDLP_USE_COOKIES = ["1", "true", "yes", "on"].includes(
  (process.env.YTDLP_USE_COOKIES || "").trim().toLowerCase(),
);
export const YTDLP_VISITOR_DATA = (process.env.YTDLP_VISITOR_DATA || "").trim();
