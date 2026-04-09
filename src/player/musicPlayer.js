import { spawn } from "node:child_process";
import {
  AudioPlayerStatus,
  NoSubscriberBehavior,
  StreamType,
  VoiceConnectionStatus,
  createAudioPlayer,
  createAudioResource,
  entersState,
  getVoiceConnection,
  joinVoiceChannel,
} from "@discordjs/voice";
import { CHAT_CLEANUP_DELAY_MS, IDLE_TIMEOUT_MS } from "../config.js";
import { createLogger } from "../logger.js";
import { EmbedFactory } from "../utils/embedBuilder.js";
import { QueueManager } from "./queueManager.js";
import { Track } from "./track.js";
import { YtdlService } from "./ytdlService.js";
import { ActionRowBuilder, ButtonBuilder, ButtonStyle } from "discord.js";

const logger = createLogger("omnia.player");

export const LoopMode = { OFF: "off", SINGLE: "single", QUEUE: "queue" };
export const ShuffleMode = { OFF: 0, STANDARD: 1, ALTERNATIVE: 2 };
export const AutoplayMode = { OFF: 0, YOUTUBE: 1, CUSTOM: 2, CUSTOM2: 3 };

export class MusicPlayer {
  constructor(client, guild, manager) {
    this.client = client;
    this.guild = guild;
    this.manager = manager;
    this.queue = new QueueManager();
    this.current = null;
    this.loopMode = LoopMode.OFF;
    this.shuffleMode = ShuffleMode.OFF;
    this.autoplayMode = AutoplayMode.OFF;
    this.textChannel = null;
    this.nowPlayingMessage = null;
    this.lyricsMessages = [];
    this.playHistory = [];
    this.nextAutoplay = null;
    this.activeProcess = null;
    this.idleTimer = null;
    this.progressTimer = null;
    this.preloadTimer = null;
    this.sleepTimer = null;
    this.sleepUntil = null;
    this.sleepLabel = null;
    this.seeking = false;
    this.stopping = false;
    this.playlistEnqueueToken = 0;
    this.playbackAttempts = new Map();
    this.trackStartedAt = null;
    this.trackPausedElapsed = null;
    this.player = createAudioPlayer({ behaviors: { noSubscriber: NoSubscriberBehavior.Pause } });
    this.player.on(AudioPlayerStatus.Idle, () => {
      void this.onTrackFinished();
    });
    this.player.on("error", (error) => {
      void this.handlePlaybackError(error);
    });
  }

  get voiceConnection() {
    return getVoiceConnection(this.guild.id);
  }

  get isPlaying() {
    return this.player.state.status === AudioPlayerStatus.Playing || this.player.state.status === AudioPlayerStatus.Paused;
  }

  get isPaused() {
    return this.player.state.status === AudioPlayerStatus.Paused;
  }

  get sleepTimerRemaining() {
    if (!this.sleepUntil) return null;
    return Math.max(0, this.sleepUntil - Date.now());
  }

  get currentElapsedSeconds() {
    if (this.trackPausedElapsed != null) return this.trackPausedElapsed;
    if (!this.trackStartedAt) return 0;
    return Math.max(0, (Date.now() - this.trackStartedAt) / 1000);
  }

  currentProgressBar(width = 14) {
    if (!this.current) return null;
    if (!this.current.duration) return "● Live stream";
    const ratio = Math.min(1, this.currentElapsedSeconds / Math.max(this.current.duration, 1));
    const filled = Math.max(0, Math.min(width, Math.round(width * ratio)));
    return `\`${"█".repeat(filled)}${"░".repeat(width - filled)}\` ${this.currentProgressText()}`;
  }

  currentProgressText() {
    if (!this.current) return null;
    const elapsed = formatTimestamp(this.currentElapsedSeconds);
    if (!this.current.duration) return `Live • ${elapsed}`;
    return `${elapsed} / ${formatTimestamp(this.current.duration)}`;
  }

  async connect(channel) {
    let connection = this.voiceConnection;
    if (!connection) {
      connection = joinVoiceChannel({
        guildId: this.guild.id,
        channelId: channel.id,
        adapterCreator: this.guild.voiceAdapterCreator,
        selfDeaf: true,
      });
      connection.subscribe(this.player);
    } else if (connection.joinConfig.channelId !== channel.id) {
      connection.destroy();
      connection = joinVoiceChannel({
        guildId: this.guild.id,
        channelId: channel.id,
        adapterCreator: this.guild.voiceAdapterCreator,
        selfDeaf: true,
      });
      connection.subscribe(this.player);
    }
    await entersState(connection, VoiceConnectionStatus.Ready, 20_000);
    return connection;
  }

  async disconnect() {
    this.cancelPlaylistEnqueue();
    this.cancelIdleTimer();
    this.cancelProgressUpdater();
    this.cancelPreload();
    await this.cancelSleepTimer();
    await this.disableNowPlayingMessage();
    this.cleanupActiveProcess();
    this.queue.clear();
    this.current = null;
    this.playHistory = [];
    this.playbackAttempts.clear();
    this.nextAutoplay = null;
    this.resetTrackProgress();
    this.voiceConnection?.destroy();
    this.manager.removePlayer(this.guild.id);
  }

  addTrack(track) {
    return this.queue.add(track);
  }

  async ensurePlaying() {
    if (this.isPlaying || this.current) return;
    if (!this.queue.size && !this.nextAutoplay) return;
    await this.playNext();
  }

  beginPlaylistEnqueue() {
    this.playlistEnqueueToken += 1;
    return this.playlistEnqueueToken;
  }

  cancelPlaylistEnqueue() {
    this.playlistEnqueueToken += 1;
  }

  isPlaylistEnqueueActive(token) {
    return token === this.playlistEnqueueToken;
  }

  async pruneQueue() {
    const removed = this.queue.prune((track) => Boolean(track?.title?.trim() && (track.url?.trim() || track.sourceUrl?.trim())));
    if (removed.length && this.textChannel) {
      const names = removed.slice(0, 3).map((track) => `**${track.title}**`).join(", ");
      await safeSend(this.textChannel, { embeds: [EmbedFactory.info("Queue Pruned", `Track invalid dihapus otomatis: ${names}`)] }, CHAT_CLEANUP_DELAY_MS);
    }
    return removed;
  }

  setTrackStart(offsetSeconds = 0) {
    this.trackStartedAt = Date.now() - offsetSeconds * 1000;
    this.trackPausedElapsed = null;
  }

  resetTrackProgress() {
    this.trackStartedAt = null;
    this.trackPausedElapsed = null;
  }

  async pause() {
    if (this.player.state.status === AudioPlayerStatus.Playing) {
      this.trackPausedElapsed = this.currentElapsedSeconds;
      this.player.pause();
    }
  }

  async resume() {
    if (this.player.state.status === AudioPlayerStatus.Paused) {
      if (this.trackPausedElapsed != null) {
        this.trackStartedAt = Date.now() - this.trackPausedElapsed * 1000;
        this.trackPausedElapsed = null;
      }
      this.player.unpause();
    }
  }

  async seek(position) {
    if (!this.current) return false;
    const clamped = Math.max(0, Math.min(position, this.current.duration ? Math.max(this.current.duration - 3, 0) : position));
    const sourceUrl = this.current.sourceUrl || (await YtdlService.getStreamData(this.current.url)).url;
    this.current.sourceUrl = sourceUrl;
    this.seeking = true;
    await this.startTrack(this.current, { seekSeconds: clamped, isSeek: true });
    return true;
  }

  async skip() {
    if (this.loopMode === LoopMode.SINGLE) {
      const previous = this.loopMode;
      this.loopMode = LoopMode.OFF;
      this.player.stop(true);
      setTimeout(() => {
        this.loopMode = previous;
      }, 500);
      return;
    }
    this.player.stop(true);
  }

  async stop() {
    this.cancelPlaylistEnqueue();
    this.queue.clear();
    this.current = null;
    this.loopMode = LoopMode.OFF;
    this.shuffleMode = ShuffleMode.OFF;
    this.playHistory = [];
    this.playbackAttempts.clear();
    this.nextAutoplay = null;
    this.resetTrackProgress();
    await this.cancelSleepTimer();
    this.cancelProgressUpdater();
    await this.disableNowPlayingMessage();
    this.stopping = true;
    this.cleanupActiveProcess();
    this.player.stop(true);
  }

  async playNext() {
    if (this.seeking) {
      this.seeking = false;
      return;
    }
    if (this.stopping) {
      this.stopping = false;
      return;
    }
    this.cancelIdleTimer();
    await this.pruneQueue();

    if (this.current) {
      if (this.loopMode === LoopMode.SINGLE) {
        this.queue.putFront(this.current);
      } else if (this.loopMode === LoopMode.QUEUE) {
        this.queue.putBack(this.current);
      }
    }

    let nextTrack = this.queue.getNext();
    if (!nextTrack && this.autoplayMode !== AutoplayMode.OFF) {
      nextTrack = this.nextAutoplay || (await this.getAutoplayTrack());
      this.nextAutoplay = null;
      if (nextTrack && this.textChannel) {
        await safeSend(this.textChannel, { embeds: [EmbedFactory.autoplayNext(nextTrack)] }, CHAT_CLEANUP_DELAY_MS);
      }
    }

    if (!nextTrack) {
      this.current = null;
      this.resetTrackProgress();
      await this.disableNowPlayingMessage();
      this.startIdleTimer();
      if (this.textChannel) {
        await safeSend(
          this.textChannel,
          { embeds: [EmbedFactory.info("Pemutaran Selesai", "Queue kosong, tidak ada lagu selanjutnya.\nGunakan `/play` untuk memutar lagu baru.")] },
          CHAT_CLEANUP_DELAY_MS,
        );
      }
      return;
    }

    this.current = nextTrack;
    if (nextTrack.url) {
      this.playHistory.push(nextTrack.url);
      if (this.playHistory.length > 50) this.playHistory = this.playHistory.slice(-50);
    }

    await this.startTrack(nextTrack);
    this.schedulePreload();
    await this.publishNowPlaying();
  }

  async startTrack(track, { seekSeconds = 0, isSeek = false } = {}) {
    const streamData = track.sourceUrl ? { url: track.sourceUrl } : await YtdlService.getStreamData(track.url);
    track.sourceUrl = streamData.url;
    const ffmpegArgs = buildFfmpegArgs(track, seekSeconds);
    const process = spawn("ffmpeg", ffmpegArgs, { stdio: ["ignore", "pipe", "pipe"] });
    this.cleanupActiveProcess();
    this.activeProcess = process;

    const resource = createAudioResource(process.stdout, { inputType: StreamType.Raw });
    this.player.play(resource);
    this.setTrackStart(seekSeconds);

    process.stderr.on("data", () => {});
    process.on("close", (code) => {
      if (code && code !== 0 && !isSeek && this.current) {
        void this.handlePlaybackError(new Error(`ffmpeg exited with code ${code}`));
      }
    });
  }

  async handlePlaybackError(error) {
    const track = this.current;
    if (!track) return;
    const key = track.url || track.sourceUrl || track.title;
    const attempts = this.playbackAttempts.get(key) || 0;
    if (attempts >= 2) {
      this.playbackAttempts.delete(key);
      this.current = null;
      await this.playNext();
      return;
    }
    this.playbackAttempts.set(key, attempts + 1);
    if (this.textChannel) {
      await safeSend(this.textChannel, { embeds: [EmbedFactory.info("Playback Recovery", `${track.title}\nStream error terdeteksi. Mencoba ulang...`)] }, CHAT_CLEANUP_DELAY_MS);
    }
    await sleep(2 ** attempts * 1000);
    this.queue.putFront(track);
    this.current = null;
    await this.playNext();
  }

  async onTrackFinished() {
    this.cleanupActiveProcess();
    await this.playNext();
  }

  async publishNowPlaying() {
    await this.disableNowPlayingMessage();
    if (!this.textChannel || !this.current) return;
    this.nowPlayingMessage = await this.textChannel.send({
      embeds: [EmbedFactory.nowPlaying(this.current, this.currentProgressBar())],
      components: this.buildNowPlayingComponents(),
    });
    this.startProgressUpdater();
  }

  buildNowPlayingComponents() {
    const autoplayEmoji =
      this.autoplayMode === AutoplayMode.YOUTUBE ? "▶️" : this.autoplayMode === AutoplayMode.CUSTOM ? "1️⃣" : this.autoplayMode === AutoplayMode.CUSTOM2 ? "2️⃣" : "🔄";
    const loopEmoji = this.loopMode === LoopMode.SINGLE ? "🔂" : "🔁";
    const row1 = new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId("player:pause").setEmoji(this.isPaused ? "▶️" : "⏸️").setStyle(this.isPaused ? ButtonStyle.Success : ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId("player:skip").setEmoji("⏭️").setStyle(ButtonStyle.Primary),
      new ButtonBuilder().setCustomId("player:stop").setEmoji("⏹️").setStyle(ButtonStyle.Danger),
      new ButtonBuilder().setCustomId("player:shuffle").setEmoji("🔀").setStyle(this.shuffleMode === ShuffleMode.OFF ? ButtonStyle.Secondary : this.shuffleMode === ShuffleMode.STANDARD ? ButtonStyle.Success : ButtonStyle.Primary).setDisabled(!this.queue.size),
    );
    const row2 = new ActionRowBuilder().addComponents(
      new ButtonBuilder().setCustomId("player:loop").setEmoji(loopEmoji).setStyle(this.loopMode === LoopMode.OFF ? ButtonStyle.Secondary : ButtonStyle.Primary),
      new ButtonBuilder().setCustomId("player:autoplay").setEmoji(autoplayEmoji).setStyle(this.autoplayMode === AutoplayMode.OFF ? ButtonStyle.Secondary : this.autoplayMode === AutoplayMode.CUSTOM2 ? ButtonStyle.Danger : this.autoplayMode === AutoplayMode.CUSTOM ? ButtonStyle.Primary : ButtonStyle.Success),
      new ButtonBuilder().setCustomId("player:queue").setEmoji("📜").setStyle(ButtonStyle.Secondary),
      new ButtonBuilder().setCustomId("player:lyrics").setEmoji("🎤").setStyle(ButtonStyle.Secondary),
    );
    return [row1, row2];
  }

  async disableNowPlayingMessage() {
    this.cancelProgressUpdater();
    await this.deleteLyricsMessages();
    if (this.nowPlayingMessage) {
      try {
        await this.nowPlayingMessage.delete();
      } catch {}
      this.nowPlayingMessage = null;
    }
  }

  async deleteLyricsMessages() {
    for (const message of this.lyricsMessages) {
      try {
        await message.delete();
      } catch {}
    }
    this.lyricsMessages = [];
  }

  startProgressUpdater() {
    this.cancelProgressUpdater();
    this.progressTimer = setInterval(async () => {
      if (!this.nowPlayingMessage || !this.current) return;
      try {
        await this.nowPlayingMessage.edit({
          embeds: [EmbedFactory.nowPlaying(this.current, this.currentProgressBar())],
          components: this.buildNowPlayingComponents(),
        });
      } catch {
        this.cancelProgressUpdater();
      }
    }, 15_000);
  }

  cancelProgressUpdater() {
    if (this.progressTimer) clearInterval(this.progressTimer);
    this.progressTimer = null;
  }

  async setSleepTimer(delaySeconds, label = null) {
    await this.cancelSleepTimer();
    this.sleepUntil = Date.now() + delaySeconds * 1000;
    this.sleepLabel = label;
    this.sleepTimer = setTimeout(async () => {
      if (this.textChannel) {
        const message = this.sleepLabel ? `${this.sleepLabel}. Timer tidur selesai.` : "Timer tidur selesai.";
        await safeSend(this.textChannel, { embeds: [EmbedFactory.info("Sleep Timer", message)] }, CHAT_CLEANUP_DELAY_MS);
      }
      await this.stop();
      await this.disconnect();
    }, delaySeconds * 1000);
  }

  async cancelSleepTimer() {
    if (this.sleepTimer) clearTimeout(this.sleepTimer);
    this.sleepTimer = null;
    this.sleepUntil = null;
    this.sleepLabel = null;
  }

  startIdleTimer() {
    this.cancelIdleTimer();
    this.idleTimer = setTimeout(async () => {
      if (this.isPlaying) return;
      if (this.textChannel) {
        await safeSend(this.textChannel, { embeds: [EmbedFactory.info("Auto Disconnect", "Bot keluar karena idle selama 3 menit.")] }, CHAT_CLEANUP_DELAY_MS);
      }
      await this.disconnect();
    }, IDLE_TIMEOUT_MS);
  }

  cancelIdleTimer() {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
  }

  schedulePreload() {
    this.cancelPreload();
    this.preloadTimer = setTimeout(async () => {
      const nextTrack = this.queue.peekNext();
      if (!nextTrack) {
        if (this.autoplayMode !== AutoplayMode.OFF && this.current && !this.nextAutoplay) {
          this.nextAutoplay = await this.getAutoplayTrack();
        }
        return;
      }
      if (!nextTrack.sourceUrl) {
        try {
          const streamData = await YtdlService.getStreamData(nextTrack.url);
          nextTrack.sourceUrl = streamData.url;
        } catch {}
      }
    }, 1000);
  }

  cancelPreload() {
    if (this.preloadTimer) clearTimeout(this.preloadTimer);
    this.preloadTimer = null;
  }

  cleanupActiveProcess() {
    if (this.activeProcess && !this.activeProcess.killed) {
      this.activeProcess.kill("SIGKILL");
    }
    this.activeProcess = null;
  }

  async setShuffle(mode) {
    this.shuffleMode = mode;
    this.queue.shuffle(mode);
  }

  async getAutoplayTrack() {
    if (!this.current?.url) return null;
    const related = await YtdlService.getRelated(this.current.url, this.current.title);
    if (!related.length) return null;
    let fresh = related.filter((item) => !this.playHistory.includes(item.url));
    if (!fresh.length) fresh = related;
    let chosen = fresh[Math.floor(Math.random() * fresh.length)];
    if (this.autoplayMode === AutoplayMode.CUSTOM || this.autoplayMode === AutoplayMode.CUSTOM2) {
      const currentUploader = (this.current.uploader || "").toLowerCase();
      const currentWords = (this.current.title || "")
        .toLowerCase()
        .split(/\s+/)
        .filter((word) => word.length > 3);
      fresh.sort((a, b) => scoreTrack(b, currentUploader, currentWords, this.autoplayMode) - scoreTrack(a, currentUploader, currentWords, this.autoplayMode));
      const candidates = fresh.slice(0, this.autoplayMode === AutoplayMode.CUSTOM2 ? 10 : 3);
      chosen = candidates[Math.floor(Math.random() * candidates.length)];
    }
    const data = await YtdlService.getStreamData(chosen.url);
    return new Track({
      sourceUrl: data.url,
      title: data.title || "Unknown",
      url: data.webpage_url || chosen.url,
      duration: data.duration || 0,
      thumbnail: data.thumbnail || "",
      uploader: data.uploader || "Unknown",
      requester: this.client.user,
    });
  }
}

function scoreTrack(candidate, currentUploader, currentWords, mode) {
  let score = Math.random() * 10;
  const title = String(candidate.title || "").toLowerCase();
  if (currentUploader && title.includes(currentUploader)) score += 5;
  const matches = currentWords.reduce((count, word) => count + (title.includes(word) ? 1 : 0), 0);
  score += mode === AutoplayMode.CUSTOM2 ? -matches * 2 : matches * 2;
  return score;
}

function buildFfmpegArgs(track, seekSeconds = 0) {
  const args = [
    "-hide_banner",
    "-loglevel",
    "error",
    "-reconnect",
    "1",
    "-reconnect_streamed",
    "1",
    "-reconnect_delay_max",
    "5",
  ];
  if (seekSeconds > 0) {
    args.push("-ss", String(Math.floor(seekSeconds)));
  }
  args.push("-i", track.sourceUrl);
  const filters = ["afade=t=in:st=0:d=0.35"];
  if (track.duration && track.duration > 2) {
    filters.push(`afade=t=out:st=${Math.max(track.duration - 0.8, 0)}:d=0.8`);
  }
  args.push("-vn", "-af", filters.join(","), "-f", "s16le", "-ar", "48000", "-ac", "2", "pipe:1");
  return args;
}

function formatTimestamp(totalSeconds) {
  const total = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function safeSend(channel, payload, deleteAfterMs = 0) {
  const message = await channel.send(payload);
  if (deleteAfterMs > 0) {
    setTimeout(() => {
      void message.delete().catch(() => {});
    }, deleteAfterMs);
  }
  return message;
}
