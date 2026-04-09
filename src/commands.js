import {
  ActionRowBuilder,
  ApplicationCommandOptionType,
  ButtonBuilder,
  ButtonStyle,
  EmbedBuilder,
  StringSelectMenuBuilder,
} from "discord.js";
import { CHAT_CLEANUP_DELAY_MS } from "./config.js";
import { AutoplayMode, LoopMode, ShuffleMode } from "./player/musicPlayer.js";
import { Track } from "./player/track.js";
import { YtdlService } from "./player/ytdlService.js";
import { EmbedFactory } from "./utils/embedBuilder.js";
import { splitLyrics } from "./utils/geniusLyrics.js";
import { getLyricsConcurrently } from "./utils/lyricsService.js";
import { PlaylistStore } from "./utils/playlistStore.js";
import { RADIO_CATEGORY_PRESETS, RADIO_PAGE_SIZE } from "./utils/radioBrowser.js";

const PAGE_SIZE = 25;

export const commandDefinitions = [
  { name: "play", description: "Putar lagu dari YouTube (URL, Playlist, atau pencarian)", options: [{ name: "query", description: "YouTube URL, Playlist URL, atau kata kunci pencarian", type: ApplicationCommandOptionType.String, required: true }] },
  { name: "skip", description: "Skip lagu yang sedang diputar" },
  { name: "seek", description: "Loncat ke timestamp tertentu di lagu yang sedang diputar", options: [{ name: "timestamp", description: "Timestamp tujuan (detik, mm:ss, atau hh:mm:ss)", type: ApplicationCommandOptionType.String, required: true }] },
  { name: "stop", description: "Stop pemutaran dan kosongkan queue" },
  { name: "sleep", description: "Atur timer untuk stop dan disconnect otomatis", options: [{ name: "duration", description: "Contoh: 30m, 1h30m, 90s, atau off", type: ApplicationCommandOptionType.String, required: true }] },
  { name: "reconnect", description: "Reset bot dan connect ulang ke voice" },
  { name: "queue", description: "Tampilkan antrian lagu" },
  { name: "nowplaying", description: "Tampilkan lagu yang sedang diputar" },
  { name: "playlistplay", description: "Pilih playlist server untuk diputar" },
  { name: "playlist", description: "Tampilkan daftar playlist server" },
  { name: "playlistdelete", description: "Hapus playlist yang tersimpan di server" },
  { name: "move", description: "Pindahkan lagu di queue ke posisi lain", options: [{ name: "from", description: "Posisi lagu sekarang", type: ApplicationCommandOptionType.Integer, required: true }, { name: "to", description: "Posisi tujuan", type: ApplicationCommandOptionType.Integer, required: true }] },
  { name: "lyrics", description: "Cari lirik lagu dari Genius", options: [{ name: "query", description: "Judul lagu", type: ApplicationCommandOptionType.String, required: false }] },
  { name: "playlistcopy", description: "Copy playlist YouTube dan simpan sebagai playlist server", options: [{ name: "url", description: "URL playlist YouTube", type: ApplicationCommandOptionType.String, required: true }, { name: "name", description: "Nama playlist", type: ApplicationCommandOptionType.String, required: false }] },
  { name: "loop", description: "Atur mode loop", options: [{ name: "mode", description: "Mode loop", type: ApplicationCommandOptionType.String, required: true, choices: [{ name: "Off", value: "off" }, { name: "Single", value: "single" }, { name: "Queue", value: "queue" }] }] },
  { name: "autoplay", description: "Atur mode autoplay", options: [{ name: "mode", description: "Mode autoplay", type: ApplicationCommandOptionType.String, required: true, choices: [{ name: "Off", value: "off" }, { name: "YouTube", value: "youtube" }, { name: "Custom 1", value: "custom1" }, { name: "Custom 2", value: "custom2" }] }] },
  { name: "status", description: "Tampilkan status bot musik" },
  { name: "radio", description: "Pilih radio live berdasarkan kategori" },
  { name: "help", description: "Tampilkan daftar command bot musik" },
];

export async function handleInteraction(interaction, manager) {
  if (interaction.isChatInputCommand()) return handleCommand(interaction, manager);
  if (interaction.isButton()) {
    if (interaction.customId.startsWith("player:")) return handlePlayerButton(interaction, manager);
    if (interaction.customId.startsWith("playlist:")) return handlePlaylistButton(interaction, manager);
    if (interaction.customId.startsWith("radio:")) return handleRadioButton(interaction, manager);
  }
  if (interaction.isStringSelectMenu()) {
    if (interaction.customId.startsWith("playlist:")) return handlePlaylistSelect(interaction, manager);
    if (interaction.customId.startsWith("radio:")) return handleRadioSelect(interaction, manager);
  }
}

async function handleCommand(interaction, manager) {
  const handlers = {
    play: handlePlay,
    skip: handleSkip,
    seek: handleSeek,
    stop: handleStop,
    sleep: handleSleep,
    reconnect: handleReconnect,
    queue: handleQueue,
    nowplaying: handleNowPlaying,
    playlistplay: handlePlaylistPlay,
    playlist: handlePlaylistList,
    playlistdelete: handlePlaylistDelete,
    move: handleMove,
    lyrics: handleLyrics,
    playlistcopy: handlePlaylistCopy,
    loop: handleLoop,
    autoplay: handleAutoplay,
    status: handleStatus,
    radio: handleRadio,
    help: handleHelp,
  };
  return handlers[interaction.commandName]?.(interaction, manager);
}

async function handlePlay(interaction, manager) {
  if (!(await ensureVoice(interaction))) return;
  await interaction.deferReply();
  const query = interaction.options.getString("query", true);
  const player = manager.getPlayer(interaction.guild);
  player.textChannel = interaction.channel;
  await player.connect(interaction.member.voice.channel);

  const firstPlaylistItems = query.includes("list=") && !query.includes("list=RD") ? "1" : null;
  const { entries, playlistTitle } = await YtdlService.getInfo(query, { playlistItems: firstPlaylistItems });
  if (!entries.length) {
    return interaction.editReply({ embeds: [EmbedFactory.error("Tidak ditemukan lagu.")] });
  }

  const firstTrack = buildTrackFromEntry(entries.find(Boolean), interaction.user, playlistTitle);
  if (!firstTrack) {
    return interaction.editReply({ embeds: [EmbedFactory.error("Gagal memproses lagu dari playlist.")] });
  }

  if (player.current && player.current.duration === 0 && player.current.sourceUrl && !/youtube\.com\/watch|youtu\.be\//.test(player.current.url || "")) {
    await player.stop();
  }

  player.cancelPlaylistEnqueue();
  const isPlaylistQuery = Boolean(playlistTitle);
  const wasPlaying = player.isPlaying || player.current !== null;
  const position = player.addTrack(firstTrack);

  if (!player.isPlaying && !player.current) {
    void player.ensurePlaying();
  }

  if (isPlaylistQuery) {
    const token = player.beginPlaylistEnqueue();
    void enqueuePlaylistInBackground(player, query, interaction.user, playlistTitle, token);
  }

  if (!isPlaylistQuery) {
    if (wasPlaying) return interaction.editReply({ embeds: [EmbedFactory.addedToQueue(firstTrack, position)] });
    return interaction.editReply({ embeds: [EmbedFactory.success("Memulai Pemutaran", `**[${firstTrack.title}](${firstTrack.url})**`)] });
  }

  return interaction.editReply({
    embeds: [
      EmbedFactory.success(
        "Playlist Ditambahkan",
        `Lagu pertama dari **${playlistTitle || "Playlist"}** sudah dimulai, dan sisa playlist diproses di background.`,
      ),
    ],
  });
}

async function enqueuePlaylistInBackground(player, query, requester, playlistTitle, token) {
  try {
    const { entries } = await YtdlService.getInfo(query, { playlistItems: "2:" });
    for (const entry of entries) {
      if (!player.isPlaylistEnqueueActive(token)) return;
      const track = buildTrackFromEntry(entry, requester, playlistTitle);
      if (!track) continue;
      player.addTrack(track);
    }
    await player.ensurePlaying();
  } catch {}
}

async function handleSkip(interaction, manager) {
  if (!(await ensureVoice(interaction)) || !(await ensureSameChannel(interaction))) return;
  const player = manager.getPlayer(interaction.guild);
  if (!player.isPlaying) return reply(interaction, EmbedFactory.error("Tidak ada lagu yang sedang diputar!"), true);
  const title = player.current?.title || "Unknown";
  await player.skip();
  return reply(interaction, EmbedFactory.success("Skipped", `**${title}**`));
}

async function handleSeek(interaction, manager) {
  if (!(await ensureVoice(interaction)) || !(await ensureSameChannel(interaction))) return;
  const player = manager.getPlayer(interaction.guild);
  if (!player.current || !player.isPlaying) return reply(interaction, EmbedFactory.error("Tidak ada lagu yang sedang diputar!"), true);
  const seconds = parseTimestamp(interaction.options.getString("timestamp", true));
  if (seconds == null) {
    return reply(interaction, EmbedFactory.error("Format timestamp tidak valid.\nGunakan `120`, `2:30`, atau `1:02:30`."), true);
  }
  await interaction.deferReply();
  const success = await player.seek(seconds);
  if (!success) return interaction.editReply({ embeds: [EmbedFactory.error("Gagal melakukan seek ke posisi tersebut.")] });
  return interaction.editReply({ embeds: [EmbedFactory.success("Seek", `Lompat ke posisi **${formatClock(seconds)}** pada lagu saat ini.`)] });
}

async function handleStop(interaction, manager) {
  if (!(await ensureVoice(interaction)) || !(await ensureSameChannel(interaction))) return;
  const player = manager.getPlayer(interaction.guild);
  await player.stop();
  return reply(interaction, EmbedFactory.success("Stopped", "Pemutaran dihentikan dan queue dikosongkan. Bot tetap di voice channel."));
}

async function handleSleep(interaction, manager) {
  if (!(await ensureVoice(interaction)) || !(await ensureSameChannel(interaction))) return;
  const player = manager.getPlayer(interaction.guild);
  const durationInput = interaction.options.getString("duration", true);
  const seconds = parseDuration(durationInput);
  if (seconds == null) {
    return reply(interaction, EmbedFactory.error("Format timer tidak valid.\nGunakan `30m`, `1h30m`, `90s`, atau `off`."), true);
  }
  if (seconds === 0) {
    await player.cancelSleepTimer();
    return reply(interaction, EmbedFactory.success("Sleep Timer", "Timer tidur dibatalkan."));
  }
  await player.setSleepTimer(seconds, `Timer tidur ${durationInput}`);
  return reply(interaction, EmbedFactory.success("Sleep Timer", `Bot akan stop dan disconnect dalam **${durationInput}**.`));
}

async function handleReconnect(interaction, manager) {
  if (!(await ensureVoice(interaction))) return;
  await interaction.deferReply();
  const player = manager.getPlayer(interaction.guild);
  try {
    await player.stop();
    await player.disconnect();
  } catch {}
  const nextPlayer = manager.getPlayer(interaction.guild);
  nextPlayer.textChannel = interaction.channel;
  await nextPlayer.connect(interaction.member.voice.channel);
  return interaction.editReply({ embeds: [EmbedFactory.success("Reconnected", `Bot berhasil di-reset dan terhubung kembali ke **${interaction.member.voice.channel.name}**.`)] });
}

async function handleQueue(interaction, manager) {
  const player = manager.getPlayer(interaction.guild);
  const embed = EmbedFactory.queueList(player.queue.asList(20), player.current, player.queue.size);
  const status = [];
  if (player.loopMode !== LoopMode.OFF) status.push(`Loop: **${player.loopMode}**`);
  if (player.autoplayMode === AutoplayMode.YOUTUBE) status.push("Autoplay: **YouTube**");
  if (player.autoplayMode === AutoplayMode.CUSTOM) status.push("Autoplay: **Custom 1**");
  if (player.autoplayMode === AutoplayMode.CUSTOM2) status.push("Autoplay: **Custom 2**");
  if (status.length) embed.addFields({ name: "Status", value: status.join(" • "), inline: false });
  return reply(interaction, embed);
}

async function handleNowPlaying(interaction, manager) {
  const player = manager.getPlayer(interaction.guild);
  if (!player.current) return reply(interaction, EmbedFactory.error("Tidak ada lagu yang sedang diputar!"), true);
  const embed = EmbedFactory.nowPlaying(player.current, player.currentProgressBar());
  const info = [];
  if (player.loopMode !== LoopMode.OFF) info.push(`Loop: ${player.loopMode}`);
  if (player.autoplayMode === AutoplayMode.YOUTUBE) info.push("Autoplay: YouTube");
  if (player.autoplayMode === AutoplayMode.CUSTOM) info.push("Autoplay: Custom 1");
  if (player.autoplayMode === AutoplayMode.CUSTOM2) info.push("Autoplay: Custom 2");
  info.push(`Queue: ${player.queue.size} lagu`);
  embed.addFields({ name: "Info", value: info.join(" • "), inline: false });
  return reply(interaction, embed);
}

async function handlePlaylistPlay(interaction, manager) {
  const playlists = await manager.playlists.getPlaylists(interaction.guild.id);
  if (!playlists.length) return reply(interaction, EmbedFactory.info("Playlist Kosong", "Belum ada playlist yang disimpan untuk server ini.\nGunakan `/playlistcopy` untuk menyalin playlist YouTube."), true);
  const state = { type: "play", guildId: interaction.guild.id, page: 0, playlists };
  const payload = buildPlaylistView(state);
  const message = await interaction.reply({ ...payload, fetchReply: true });
  manager.playlistViews.set(message.id, state);
}

async function handlePlaylistList(interaction, manager) {
  const playlists = await manager.playlists.getPlaylists(interaction.guild.id);
  if (!playlists.length) return reply(interaction, EmbedFactory.info("Playlist Kosong", "Belum ada playlist yang disimpan untuk server ini.\nGunakan `/playlistcopy` untuk menyalin playlist YouTube."), true);
  const lines = playlists.map((playlist, index) => `\`${index + 1}.\` **${playlist.name || "Untitled"}** — ${(playlist.tracks || []).length} lagu`);
  return reply(interaction, new EmbedBuilder().setTitle("Daftar Playlist Server").setDescription(lines.join("\n").slice(0, 4096)).setColor(0x8a2be2));
}

async function handlePlaylistDelete(interaction, manager) {
  const playlists = await manager.playlists.getPlaylists(interaction.guild.id);
  if (!playlists.length) return reply(interaction, EmbedFactory.info("Playlist Kosong", "Belum ada playlist yang disimpan untuk server ini.\nGunakan `/playlistcopy` untuk menyalin playlist YouTube."), true);
  const state = { type: "delete", guildId: interaction.guild.id, page: 0, playlists };
  const payload = buildPlaylistView(state);
  const message = await interaction.reply({ ...payload, fetchReply: true, ephemeral: true });
  manager.playlistViews.set(message.id, state);
}

async function handleMove(interaction, manager) {
  if (!(await ensureVoice(interaction)) || !(await ensureSameChannel(interaction))) return;
  const player = manager.getPlayer(interaction.guild);
  const from = interaction.options.getInteger("from", true);
  const to = interaction.options.getInteger("to", true);
  const moved = player.queue.move(from - 1, to - 1);
  if (!moved) return reply(interaction, EmbedFactory.error(`Posisi asal tidak valid! (1 - ${player.queue.size})`), true);
  return reply(interaction, EmbedFactory.success("Moved", `**${moved.title}** dipindahkan dari posisi **${from}** ke **${Math.max(1, Math.min(to, player.queue.size))}**.`));
}

async function handleLyrics(interaction, manager) {
  await interaction.deferReply();
  let query = interaction.options.getString("query");
  let duration = null;
  if (!query) {
    const player = manager.getPlayer(interaction.guild);
    if (!player.current) {
      return interaction.editReply({ embeds: [EmbedFactory.error("Tidak ada lagu yang sedang diputar!\nGunakan `/lyrics query:<judul lagu>` untuk mencari lirik.")] });
    }
    query = player.current.title;
    duration = player.current.duration;
  }
  const result = await getLyricsConcurrently(query, duration);
  if (!result) return interaction.editReply({ embeds: [EmbedFactory.error(`Lirik tidak ditemukan untuk: **${query}**`)] });
  const chunks = splitLyrics(result.lyrics || result.syncedLyrics || "", 4096);
  if (!chunks.length) return interaction.editReply({ embeds: [EmbedFactory.error("Konten lirik kosong.")] });
  await interaction.editReply({ embeds: [buildLyricsEmbed(result, chunks[0], 0)] });
  const player = manager.getPlayer(interaction.guild);
  for (let index = 1; index < chunks.length; index += 1) {
    const message = await interaction.followUp({ embeds: [buildLyricsEmbed(result, chunks[index], index)] });
    player.lyricsMessages.push(message);
  }
}

async function handlePlaylistCopy(interaction, manager) {
  await interaction.deferReply();
  const url = interaction.options.getString("url", true);
  const name = interaction.options.getString("name");
  const { entries, playlistTitle } = await YtdlService.getInfo(url);
  if (!entries.length) return interaction.editReply({ embeds: [EmbedFactory.error("Playlist kosong atau tidak ditemukan.")] });
  const baseName = name || playlistTitle || "Playlist";
  const storedName = `${baseName} - ${interaction.user.displayName || interaction.user.username}`;
  const tracks = entries.slice(0, PlaylistStore.MAX_TRACKS).map((entry) => ({
    title: entry.title || "Unknown",
    url: entry.webpage_url || entry.url,
    duration: entry.duration || 0,
    thumbnail: entry.thumbnail || "",
    uploader: entry.uploader || "Unknown",
  }));
  const [ok, error] = await manager.playlists.addPlaylist(interaction.guild.id, {
    name: storedName,
    base_name: baseName,
    owner_id: interaction.user.id,
    owner_name: interaction.user.displayName || interaction.user.username,
    source_url: url,
    track_count: tracks.length,
    tracks,
  });
  if (!ok && error === "FULL") return interaction.editReply({ embeds: [EmbedFactory.error("Daftar playlist untuk server ini sudah penuh (maksimal 100 playlist).")] });
  return interaction.editReply({ embeds: [EmbedFactory.success("Playlist Disalin", `Playlist **${storedName}** berhasil disimpan untuk server ini.\nTotal lagu tersimpan: **${tracks.length}**.`)] });
}

async function handleLoop(interaction, manager) {
  if (!(await ensureVoice(interaction)) || !(await ensureSameChannel(interaction))) return;
  const mode = interaction.options.getString("mode", true);
  manager.getPlayer(interaction.guild).loopMode = mode;
  return reply(interaction, EmbedFactory.success("Loop Mode", `Loop diatur ke: **${mode}**`));
}

async function handleAutoplay(interaction, manager) {
  if (!(await ensureVoice(interaction)) || !(await ensureSameChannel(interaction))) return;
  const mode = interaction.options.getString("mode", true);
  const player = manager.getPlayer(interaction.guild);
  if (mode === "youtube") player.autoplayMode = AutoplayMode.YOUTUBE;
  else if (mode === "custom1") player.autoplayMode = AutoplayMode.CUSTOM;
  else if (mode === "custom2") player.autoplayMode = AutoplayMode.CUSTOM2;
  else player.autoplayMode = AutoplayMode.OFF;
  player.schedulePreload();
  return reply(interaction, EmbedFactory.success("Autoplay", `Autoplay diatur ke **${mode}**.`));
}

async function handleStatus(interaction, manager) {
  const player = manager.getPlayer(interaction.guild);
  const embed = new EmbedBuilder().setTitle("Status Bot Musik").setColor(0x8a2be2);
  const voiceChannel = interaction.guild.members.me?.voice?.channel;
  embed.addFields({ name: "Voice Channel", value: voiceChannel?.name || "Tidak terhubung", inline: true });
  if (voiceChannel) {
    const listeners = voiceChannel.members.filter((member) => !member.user.bot).map((member) => member.displayName);
    embed.addFields({ name: "Pendengar", value: listeners.join(", ") || "Tidak ada", inline: true });
  }
  embed.addFields({ name: "Sedang Diputar", value: player.current ? `**[${player.current.title}](${player.current.url})** [${player.current.durationText}]` : "Tidak ada", inline: false });
  if (player.current) embed.addFields({ name: "Progress", value: player.currentProgressBar() || "-", inline: false });
  embed.addFields(
    { name: "Queue", value: `${player.queue.size} lagu`, inline: true },
    { name: "Loop", value: player.loopMode, inline: true },
    { name: "Autoplay", value: autoplayLabel(player.autoplayMode), inline: true },
    { name: "Sleep Timer", value: formatSleep(player.sleepTimerRemaining), inline: true },
  );
  return reply(interaction, embed);
}

async function handleRadio(interaction, manager) {
  if (!(await ensureVoice(interaction))) return;
  const payload = buildRadioCategoryView();
  const message = await interaction.reply({ ...payload, fetchReply: true, ephemeral: true });
  manager.radioViews.set(message.id, { guildId: interaction.guild.id, page: 0, categoryKey: null, stations: [] });
}

async function handleHelp(interaction) {
  const embed = new EmbedBuilder().setTitle("Daftar Command Omnia Music").setDescription("Berikut adalah command yang tersedia:").setColor(0x8a2be2);
  for (const command of commandDefinitions) {
    const optionText = command.options?.map((option) => (option.required ? `<${option.name}>` : `[${option.name}]`)).join(" ") || "";
    embed.addFields({ name: `/${command.name} ${optionText}`.trim(), value: command.description, inline: false });
  }
  return reply(interaction, embed);
}

async function handlePlayerButton(interaction, manager) {
  const player = manager.getPlayer(interaction.guild);
  const action = interaction.customId.split(":")[1];
  if (action === "pause") {
    if (player.isPaused) await player.resume();
    else await player.pause();
    return interaction.update({ embeds: player.current ? [EmbedFactory.nowPlaying(player.current, player.currentProgressBar())] : interaction.message.embeds, components: player.buildNowPlayingComponents() });
  }
  if (action === "skip") {
    await interaction.deferReply({ ephemeral: true });
    const currentTitle = player.current?.title || "Unknown";
    await player.skip();
    return interaction.editReply({ embeds: [EmbedFactory.success("Skipped", `**${currentTitle}**`)] });
  }
  if (action === "stop") {
    await interaction.deferUpdate();
    await player.stop();
    return safeFollowup(interaction, { embeds: [EmbedFactory.info("Pemutaran Selesai", "Queue dikosongkan dan pemutaran dihentikan. Bot tetap di voice channel.")] });
  }
  if (action === "shuffle") {
    const next = player.shuffleMode === ShuffleMode.OFF ? ShuffleMode.STANDARD : player.shuffleMode === ShuffleMode.STANDARD ? ShuffleMode.ALTERNATIVE : ShuffleMode.OFF;
    await player.setShuffle(next);
    return interaction.update({ embeds: player.current ? [EmbedFactory.nowPlaying(player.current, player.currentProgressBar())] : interaction.message.embeds, components: player.buildNowPlayingComponents() });
  }
  if (action === "loop") {
    player.loopMode = player.loopMode === LoopMode.OFF ? LoopMode.SINGLE : player.loopMode === LoopMode.SINGLE ? LoopMode.QUEUE : LoopMode.OFF;
    return interaction.update({ embeds: player.current ? [EmbedFactory.nowPlaying(player.current, player.currentProgressBar())] : interaction.message.embeds, components: player.buildNowPlayingComponents() });
  }
  if (action === "autoplay") {
    player.autoplayMode =
      player.autoplayMode === AutoplayMode.OFF ? AutoplayMode.YOUTUBE : player.autoplayMode === AutoplayMode.YOUTUBE ? AutoplayMode.CUSTOM : player.autoplayMode === AutoplayMode.CUSTOM ? AutoplayMode.CUSTOM2 : AutoplayMode.OFF;
    player.schedulePreload();
    return interaction.update({ embeds: player.current ? [EmbedFactory.nowPlaying(player.current, player.currentProgressBar())] : interaction.message.embeds, components: player.buildNowPlayingComponents() });
  }
  if (action === "queue") {
    return interaction.reply({ embeds: [EmbedFactory.queueList(player.queue.asList(10), player.current, player.queue.size)], ephemeral: true });
  }
  if (action === "lyrics") {
    await interaction.deferReply();
    if (!player.current) return interaction.editReply({ embeds: [EmbedFactory.error("Tidak ada lagu yang sedang diputar!")] });
    const result = await getLyricsConcurrently(player.current.title, player.current.duration);
    if (!result) return interaction.editReply({ embeds: [EmbedFactory.error(`Lirik tidak ditemukan untuk: **${player.current.title}**`)] });
    const chunks = splitLyrics(result.lyrics || "", 4096);
    await interaction.editReply({ embeds: [buildLyricsEmbed(result, chunks[0], 0)] });
    for (let index = 1; index < chunks.length; index += 1) {
      const message = await interaction.followUp({ embeds: [buildLyricsEmbed(result, chunks[index], index)] });
      player.lyricsMessages.push(message);
    }
  }
}

async function handlePlaylistButton(interaction, manager) {
  const state = manager.playlistViews.get(interaction.message.id);
  if (!state || state.guildId !== interaction.guild.id) return;
  if (interaction.customId === "playlist:prev") state.page = Math.max(0, state.page - 1);
  if (interaction.customId === "playlist:next") state.page = Math.min(Math.ceil(state.playlists.length / PAGE_SIZE) - 1, state.page + 1);
  return interaction.update(buildPlaylistView(state));
}

async function handlePlaylistSelect(interaction, manager) {
  const state = manager.playlistViews.get(interaction.message.id);
  if (!state || state.guildId !== interaction.guild.id) return;
  const selected = state.playlists[Number(interaction.values[0])];
  if (!selected) return interaction.reply({ embeds: [EmbedFactory.error("Playlist yang dipilih tidak valid.")], ephemeral: true });
  if (state.type === "delete") {
    const deleted = await manager.playlists.deletePlaylist(interaction.guild.id, selected.name);
    if (!deleted) return interaction.reply({ embeds: [EmbedFactory.error("Playlist tidak ditemukan atau sudah dihapus.")], ephemeral: true });
    return interaction.reply({ embeds: [EmbedFactory.success("Playlist Dihapus", `Playlist **${selected.name}** telah dihapus dari server ini.`)], ephemeral: true });
  }
  if (!(await ensureVoice(interaction))) return;
  const player = manager.getPlayer(interaction.guild);
  player.textChannel = interaction.channel;
  await player.connect(interaction.member.voice.channel);
  for (const track of selected.tracks || []) {
    player.addTrack(new Track({ sourceUrl: "", title: track.title, url: track.url, duration: track.duration, thumbnail: track.thumbnail, uploader: track.uploader, requester: interaction.user }));
  }
  if (!player.current && !player.isPlaying) await player.ensurePlaying();
  return interaction.reply({ embeds: [EmbedFactory.success("Playlist Diputar", `Menambahkan playlist **${selected.name}** (${(selected.tracks || []).length} lagu) ke queue.`)], ephemeral: true });
}

async function handleRadioButton(interaction, manager) {
  const state = manager.radioViews.get(interaction.message.id);
  if (!state || state.guildId !== interaction.guild.id) return;
  if (interaction.customId === "radio:prev") state.page = Math.max(0, state.page - 1);
  if (interaction.customId === "radio:next") state.page = Math.min(Math.ceil(state.stations.length / RADIO_PAGE_SIZE) - 1, state.page + 1);
  if (interaction.customId === "radio:back") {
    state.categoryKey = null;
    state.stations = [];
    return interaction.update(buildRadioCategoryView());
  }
  return interaction.update(buildRadioStationView(state));
}

async function handleRadioSelect(interaction, manager) {
  const state = manager.radioViews.get(interaction.message.id);
  if (!state || state.guildId !== interaction.guild.id) return;
  if (interaction.customId === "radio:category") {
    await interaction.deferUpdate();
    state.categoryKey = interaction.values[0];
    state.page = 0;
    state.stations = await manager.radioBrowser.fetchCategory(state.categoryKey);
    if (!state.stations.length) {
      return interaction.editReply({ embeds: [EmbedFactory.error("Tidak ada stasiun radio yang berhasil dimuat untuk kategori ini.")], components: buildRadioCategoryView().components });
    }
    return interaction.editReply(buildRadioStationView(state));
  }
  if (!(await ensureVoice(interaction)) || !(await ensureSameChannel(interaction))) return;
  const station = state.stations[Number(interaction.values[0])];
  if (!station?.stream_url) return interaction.reply({ embeds: [EmbedFactory.error("Stream URL stasiun ini tidak tersedia.")], ephemeral: true });
  await interaction.deferUpdate();
  const player = manager.getPlayer(interaction.guild);
  player.textChannel = interaction.channel;
  await player.stop();
  await player.connect(interaction.member.voice.channel);
  player.addTrack(new Track({ sourceUrl: station.stream_url, title: station.name, url: station.homepage || station.stream_url, duration: 0, thumbnail: station.favicon || "", uploader: station.country || station.country_code || station.language || "Radio Browser", requester: interaction.user }));
  player.current = null;
  await player.ensurePlaying();
  return interaction.editReply({ embeds: [EmbedFactory.success("Radio Diputar", `Sedang memutar **[${station.name}](${station.homepage || station.stream_url})**.`)], components: [] });
}

export async function handleVoiceStateUpdate(oldState, newState, manager) {
  if (newState.member?.user.bot && newState.member.id === newState.client.user.id) return;
  if (oldState.member?.user.bot) return;
  const voiceChannel = oldState.guild.members.me?.voice?.channel;
  if (!voiceChannel || oldState.channelId !== voiceChannel.id) return;
  const humans = voiceChannel.members.filter((member) => !member.user.bot);
  if (humans.size > 0) return;
  await delay(10_000);
  const refreshed = oldState.guild.members.me?.voice?.channel;
  if (!refreshed) return;
  const remainingHumans = refreshed.members.filter((member) => !member.user.bot);
  if (remainingHumans.size === 0) {
    const player = manager.getPlayer(oldState.guild);
    if (player.textChannel) {
      await player.textChannel
        .send({ embeds: [EmbedFactory.info("Auto Disconnect", "Bot keluar karena sendirian di voice channel.")] })
        .then((message) => setTimeout(() => void message.delete().catch(() => {}), CHAT_CLEANUP_DELAY_MS))
        .catch(() => {});
    }
    await player.disconnect();
  }
}

function buildTrackFromEntry(entry, requester, playlistTitle = null) {
  if (!entry) return null;
  const webUrl =
    entry.webpage_url ||
    (/^[a-zA-Z0-9_-]{11}$/.test(entry.url || "") ? `https://www.youtube.com/watch?v=${entry.url}` : entry.url || (entry.id ? `https://www.youtube.com/watch?v=${entry.id}` : ""));
  if (!webUrl) return null;
  let sourceUrl = playlistTitle ? "" : entry.url || "";
  if (/youtube\.com\/watch|youtu\.be\//.test(sourceUrl)) sourceUrl = "";
  return new Track({ sourceUrl, title: entry.title || "Unknown", url: webUrl, duration: entry.duration || 0, thumbnail: entry.thumbnail || "", uploader: entry.uploader || "Unknown", requester });
}

async function ensureVoice(interaction) {
  if (!interaction.member?.voice?.channel) {
    await reply(interaction, EmbedFactory.error("Kamu harus berada di voice channel terlebih dahulu!"), true);
    return false;
  }
  return true;
}

async function ensureSameChannel(interaction) {
  const botChannel = interaction.guild.members.me?.voice?.channel;
  const userChannel = interaction.member?.voice?.channel;
  if (botChannel && userChannel && botChannel.id !== userChannel.id) {
    await reply(interaction, EmbedFactory.error(`Kamu harus berada di **${botChannel.name}** untuk menggunakan command ini!`), true);
    return false;
  }
  return true;
}

async function reply(interaction, embed, ephemeral = false) {
  const payload = { embeds: [embed], ephemeral, fetchReply: true };
  const message = interaction.deferred || interaction.replied ? await interaction.followUp(payload) : await interaction.reply(payload);
  if (!ephemeral) {
    setTimeout(() => {
      void message.delete().catch(() => {});
    }, CHAT_CLEANUP_DELAY_MS);
  }
  return message;
}

function parseTimestamp(value) {
  if (!value) return null;
  if (/^\d+$/.test(value)) return Number(value);
  const parts = value.split(":").map((item) => Number(item));
  if (parts.some(Number.isNaN) || parts.length < 1 || parts.length > 3) return null;
  const normalized = parts.length === 3 ? parts : parts.length === 2 ? [0, ...parts] : [0, 0, parts[0]];
  const [hours, minutes, seconds] = normalized;
  if (minutes >= 60 || seconds >= 60) return null;
  return hours * 3600 + minutes * 60 + seconds;
}

function parseDuration(value) {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (["off", "cancel", "none", "stop"].includes(normalized)) return 0;
  if (/^\d+$/.test(normalized)) return Number(normalized) * 60;
  const match = normalized.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/);
  if (!match) return null;
  const hours = Number(match[1] || 0);
  const minutes = Number(match[2] || 0);
  const seconds = Number(match[3] || 0);
  const total = hours * 3600 + minutes * 60 + seconds;
  return total > 0 ? total : null;
}

function formatClock(seconds) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return hours ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}` : `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function formatSleep(ms) {
  if (!ms) return "Tidak aktif";
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours) return `${hours}j ${minutes}m`;
  if (minutes) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function autoplayLabel(mode) {
  if (mode === AutoplayMode.YOUTUBE) return "YouTube";
  if (mode === AutoplayMode.CUSTOM) return "Custom 1";
  if (mode === AutoplayMode.CUSTOM2) return "Custom 2";
  return "Off";
}

function buildLyricsEmbed(result, chunk, index) {
  const embed = new EmbedBuilder().setTitle(index === 0 ? `🎤 ${result.title || "Lyrics"}` : `🎤 ${result.title || "Lyrics"} (lanjutan)`).setDescription(chunk).setColor(result.source === "Lrclib" ? 0x00ffff : 0xffff64);
  if (index === 0) {
    if (result.artist) embed.addFields({ name: "Artist", value: result.artist, inline: true });
    if (result.source === "Genius" && result.url) embed.addFields({ name: "Genius", value: `[Lihat di Genius](${result.url})`, inline: true });
    if (result.thumbnail) embed.setThumbnail(result.thumbnail);
  }
  embed.setFooter({ text: `Omnia Music • Lyrics powered by ${result.source}` });
  return embed;
}

function buildPlaylistView(state) {
  const start = state.page * PAGE_SIZE;
  const items = state.playlists.slice(start, start + PAGE_SIZE);
  const embed = new EmbedBuilder()
    .setTitle(state.type === "delete" ? "Hapus Playlist Server" : "Playlist Server")
    .setDescription(
      `${items.map((playlist, index) => `\`${start + index + 1}.\` **${playlist.name || "Untitled"}** — ${(playlist.tracks || []).length} lagu`).join("\n")}\n\nHalaman **${state.page + 1}** / **${Math.max(1, Math.ceil(state.playlists.length / PAGE_SIZE))}**`,
    )
    .setColor(state.type === "delete" ? 0xdc143c : 0x8a2be2);
  const select = new StringSelectMenuBuilder()
    .setCustomId(`playlist:${state.type}`)
    .setPlaceholder(state.type === "delete" ? "Pilih playlist untuk dihapus..." : "Pilih playlist untuk diputar...")
    .addOptions(items.map((playlist, index) => ({ label: String(playlist.name || "Untitled").slice(0, 90), value: String(start + index), description: `${(playlist.tracks || []).length} lagu` })));
  const nav = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId("playlist:prev").setLabel("Previous").setStyle(ButtonStyle.Secondary).setDisabled(state.page <= 0),
    new ButtonBuilder().setCustomId("playlist:next").setLabel("Next").setStyle(ButtonStyle.Secondary).setDisabled(state.page >= Math.ceil(state.playlists.length / PAGE_SIZE) - 1),
  );
  return { embeds: [embed], components: [new ActionRowBuilder().addComponents(select), nav] };
}

function buildRadioCategoryView() {
  const embed = new EmbedBuilder().setTitle("Radio").setDescription("Pilih kategori dulu, lalu pilih stasiun yang ingin diputar.").setColor(0x8a2be2);
  const select = new StringSelectMenuBuilder()
    .setCustomId("radio:category")
    .setPlaceholder("Pilih kategori radio...")
    .addOptions(Object.entries(RADIO_CATEGORY_PRESETS).map(([key, value]) => ({ label: value.label, value: key, description: value.description })));
  return { embeds: [embed], components: [new ActionRowBuilder().addComponents(select)] };
}

function buildRadioStationView(state) {
  const start = state.page * RADIO_PAGE_SIZE;
  const items = state.stations.slice(start, start + RADIO_PAGE_SIZE);
  const embed = new EmbedBuilder()
    .setTitle(`Radio • ${RADIO_CATEGORY_PRESETS[state.categoryKey]?.label || state.categoryKey}`)
    .setDescription(`${items.map((station, index) => `\`${start + index + 1}.\` **${station.name}** — ${station.description}`).join("\n")}\n\nHalaman **${state.page + 1}** / **${Math.max(1, Math.ceil(state.stations.length / RADIO_PAGE_SIZE))}**`)
    .setColor(0x1e90ff);
  const select = new StringSelectMenuBuilder()
    .setCustomId("radio:station")
    .setPlaceholder("Pilih stasiun radio...")
    .addOptions(items.map((station, index) => ({ label: station.name.slice(0, 90), value: String(start + index), description: String(station.description || "Radio stream").slice(0, 100) })));
  const nav = new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId("radio:prev").setLabel("Previous").setStyle(ButtonStyle.Secondary).setDisabled(state.page <= 0),
    new ButtonBuilder().setCustomId("radio:next").setLabel("Next").setStyle(ButtonStyle.Secondary).setDisabled(state.page >= Math.ceil(state.stations.length / RADIO_PAGE_SIZE) - 1),
    new ButtonBuilder().setCustomId("radio:back").setLabel("Back").setStyle(ButtonStyle.Primary),
  );
  return { embeds: [embed], components: [new ActionRowBuilder().addComponents(select), nav] };
}

async function safeFollowup(interaction, payload) {
  const message = await interaction.followUp(payload);
  setTimeout(() => {
    void message.delete().catch(() => {});
  }, CHAT_CLEANUP_DELAY_MS);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
