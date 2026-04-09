import { PlaylistStore } from "./utils/playlistStore.js";
import { PLAYLISTS_PATH } from "./config.js";
import { MusicPlayer } from "./player/musicPlayer.js";
import { RadioBrowserClient } from "./utils/radioBrowser.js";

export class MusicManager {
  constructor(client) {
    this.client = client;
    this.players = new Map();
    this.playlists = new PlaylistStore(PLAYLISTS_PATH);
    this.radioBrowser = new RadioBrowserClient();
    this.playlistViews = new Map();
    this.radioViews = new Map();
  }

  getPlayer(guild) {
    if (!this.players.has(guild.id)) {
      this.players.set(guild.id, new MusicPlayer(this.client, guild, this));
    }
    return this.players.get(guild.id);
  }

  removePlayer(guildId) {
    this.players.delete(guildId);
  }
}
