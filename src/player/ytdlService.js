import { access } from "node:fs/promises";
import { spawn } from "node:child_process";
import { COOKIE_FILE, POT_PROVIDER_URL, YTDLP_USE_COOKIES, YTDLP_VISITOR_DATA } from "../config.js";
import { createLogger } from "../logger.js";

const logger = createLogger("omnia.ytdl");

function parseJsonLines(stdout) {
  return stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

async function cookieArgs() {
  if (!YTDLP_USE_COOKIES) return [];
  try {
    await access(COOKIE_FILE);
    return ["--cookies", COOKIE_FILE];
  } catch {
    return [];
  }
}

function baseArgs() {
  const args = [
    "--no-warnings",
    "--no-call-home",
    "--socket-timeout",
    "20",
    "--retries",
    "3",
    "--extractor-retries",
    "3",
    "--format",
    "bestaudio/best",
    "--default-search",
    "auto",
    "--geo-bypass",
    "--ignore-config",
    "--extractor-args",
    `youtube:player_client=ios,android,tv;pot:bgutil:http:base_url=${POT_PROVIDER_URL}`,
    "--compat-options",
    "no-youtube-unavailable-videos",
  ];
  if (YTDLP_VISITOR_DATA) {
    args.push("--extractor-args", `youtube:visitor_data=${YTDLP_VISITOR_DATA}`);
  }
  return args;
}

async function runYtdlp(args, { allowFailure = false } = {}) {
  const fullArgs = [...baseArgs(), ...(await cookieArgs()), ...args];
  return new Promise((resolve, reject) => {
    const child = spawn("yt-dlp", fullArgs, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0 && !allowFailure) {
        reject(new Error(stderr.trim() || `yt-dlp exited with code ${code}`));
        return;
      }
      resolve({ stdout, stderr, code });
    });
  });
}

function normalizeWebUrl(entry) {
  if (entry.webpage_url) return entry.webpage_url;
  if (entry.url && /^https?:\/\//.test(entry.url)) return entry.url;
  if (entry.id) return `https://www.youtube.com/watch?v=${entry.id}`;
  return "";
}

function extractVideoId(value) {
  const match = String(value || "").match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
  return match ? match[1] : null;
}

export class YtdlService {
  static async warmup() {
    try {
      await runYtdlp(["--dump-single-json", "--no-playlist", "https://www.youtube.com/watch?v=jNQXAC9IVRw"], { allowFailure: true });
      logger.info("yt-dlp warmup complete");
    } catch (error) {
      logger.warn("yt-dlp warmup failed", { error: String(error) });
    }
  }

  static async getInfo(query, { playlistItems = null } = {}) {
    let input = query;
    const isSearch = !/^https?:\/\//.test(query);
    const args = ["--dump-single-json"];

    if (isSearch) {
      input = `ytsearch1:${query}`;
      args.push("--flat-playlist");
    } else if (query.includes("list=RD")) {
      const videoId = extractVideoId(query);
      if (videoId) {
        input = `https://www.youtube.com/watch?v=${videoId}`;
      }
      args.push("--no-playlist");
    } else if (query.includes("list=")) {
      args.push("--yes-playlist", "--flat-playlist");
      if (playlistItems) {
        args.push("--playlist-items", playlistItems);
      } else {
        args.push("--playlist-end", "50");
      }
    } else {
      args.push("--no-playlist");
    }

    const { stdout } = await runYtdlp([...args, input]);
    const payload = JSON.parse(stdout);
    if (payload.entries) {
      const entries = payload.entries.filter(Boolean).slice(0, 50).map((entry) => ({
        ...entry,
        webpage_url: normalizeWebUrl(entry),
        thumbnail: entry.thumbnail || (entry.id ? `https://i.ytimg.com/vi/${entry.id}/hqdefault.jpg` : ""),
      }));
      if (!entries.length) throw new Error("Tidak ditemukan hasil.");
      return { entries, playlistTitle: isSearch ? null : payload.title || "Playlist" };
    }
    return {
      entries: [{ ...payload, webpage_url: normalizeWebUrl(payload) }],
      playlistTitle: null,
    };
  }

  static async getStreamData(query) {
    const { stdout } = await runYtdlp(["--dump-single-json", "--no-playlist", query]);
    const payload = JSON.parse(stdout);
    const data = payload.entries ? payload.entries[0] : payload;
    if (!data?.url) {
      throw new Error("Gagal mendapatkan URL audio.");
    }
    return {
      ...data,
      webpage_url: normalizeWebUrl(data),
    };
  }

  static async getRelated(videoUrl, title = "") {
    const related = [];
    const videoId = extractVideoId(videoUrl);
    if (videoId) {
      try {
        const mixUrl = `https://www.youtube.com/watch?v=${videoId}&list=RD${videoId}`;
        const { stdout } = await runYtdlp([
          "--dump-single-json",
          "--yes-playlist",
          "--flat-playlist",
          "--playlist-items",
          "2-6",
          mixUrl,
        ]);
        const payload = JSON.parse(stdout);
        for (const entry of payload.entries || []) {
          if (!entry) continue;
          related.push({
            url: normalizeWebUrl(entry),
            title: entry.title || "Unknown",
          });
        }
        if (related.length) return related;
      } catch (error) {
        logger.warn("Autoplay mix lookup failed", { error: String(error) });
      }
    }

    const search = title.replace(/\(.*?\)|\[.*?]/g, "").trim() || videoUrl;
    const { stdout } = await runYtdlp(["--dump-single-json", "--flat-playlist", `ytsearch5:${search} music`], { allowFailure: true });
    if (!stdout.trim()) return [];
    const payload = JSON.parse(stdout);
    for (const entry of payload.entries || []) {
      if (!entry) continue;
      const url = normalizeWebUrl(entry);
      if (videoId && url.includes(videoId)) continue;
      related.push({ url, title: entry.title || "Unknown" });
    }
    return related;
  }
}
