import fs from "node:fs/promises";
import path from "node:path";

export class PlaylistStore {
  static MAX_PLAYLISTS = 100;
  static MAX_TRACKS = 50;

  constructor(filePath) {
    this.filePath = filePath;
    this.data = null;
  }

  async load() {
    if (this.data) return;
    try {
      const raw = await fs.readFile(this.filePath, "utf8");
      const parsed = raw.trim() ? JSON.parse(raw) : { guilds: {} };
      this.data = parsed && typeof parsed.guilds === "object" ? parsed : { guilds: {} };
    } catch {
      this.data = { guilds: {} };
    }
  }

  async save() {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });
    const tempPath = `${this.filePath}.tmp`;
    await fs.writeFile(tempPath, JSON.stringify(this.data, null, 2), "utf8");
    await fs.rename(tempPath, this.filePath);
  }

  async getPlaylists(guildId) {
    await this.load();
    return [...(this.data.guilds[String(guildId)] || [])];
  }

  async addPlaylist(guildId, playlist) {
    await this.load();
    const key = String(guildId);
    this.data.guilds[key] ||= [];
    if (this.data.guilds[key].length >= PlaylistStore.MAX_PLAYLISTS) {
      return [false, "FULL"];
    }
    const normalized = {
      ...playlist,
      tracks: (playlist.tracks || []).slice(0, PlaylistStore.MAX_TRACKS),
    };
    this.data.guilds[key].push(normalized);
    await this.save();
    return [true, null];
  }

  async deletePlaylist(guildId, name) {
    await this.load();
    const key = String(guildId);
    const list = this.data.guilds[key] || [];
    const index = list.findIndex((item) => String(item.name || "").trim().toLowerCase() === String(name || "").trim().toLowerCase());
    if (index === -1) return false;
    list.splice(index, 1);
    if (!list.length) delete this.data.guilds[key];
    await this.save();
    return true;
  }
}
