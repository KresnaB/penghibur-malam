import { EmbedBuilder as DiscordEmbedBuilder, Colors } from "discord.js";

export class EmbedFactory {
  static nowPlaying(track, progress = null) {
    const embed = new DiscordEmbedBuilder()
      .setTitle("Now Playing")
      .setDescription(`**[${track.title}](${track.url})**`)
      .setColor(Colors.Blurple)
      .addFields(
        { name: "Durasi", value: track.durationText, inline: true },
        { name: "Uploader", value: track.uploader || "Unknown", inline: true },
        { name: "Requested by", value: track.requester?.displayName || "Unknown", inline: true },
      )
      .setFooter({ text: "Omnia Music" });
    if (track.thumbnail) embed.setThumbnail(track.thumbnail);
    if (progress) embed.addFields({ name: "Progress", value: progress, inline: false });
    return embed;
  }

  static addedToQueue(track, position) {
    const embed = new DiscordEmbedBuilder()
      .setTitle("Ditambahkan ke Queue")
      .setDescription(`**[${track.title}](${track.url})**`)
      .setColor(Colors.Green)
      .addFields(
        { name: "Durasi", value: track.durationText, inline: true },
        { name: "Posisi", value: `#${position}`, inline: true },
        { name: "Requested by", value: track.requester?.displayName || "Unknown", inline: true },
      );
    if (track.thumbnail) embed.setThumbnail(track.thumbnail);
    return embed;
  }

  static queueList(tracks, current, totalSize) {
    const embed = new DiscordEmbedBuilder().setTitle("Music Queue").setColor(Colors.Blue).setFooter({ text: "Omnia Music" });
    if (current) {
      embed.addFields({
        name: "Sedang Diputar",
        value: `**[${current.title}](${current.url})** [${current.durationText}]`,
        inline: false,
      });
    }
    if (!tracks.length) {
      embed.addFields({ name: "Antrian", value: "*Queue kosong*", inline: false });
      return embed;
    }
    let chunk = "";
    let index = 0;
    for (const [offset, track] of tracks.entries()) {
      const label = track.title.length > 40 ? `${track.title.slice(0, 37)}...` : track.title;
      const line = `\`${offset + 1}.\` **[${label}](${track.url})** [${track.durationText}]\n`;
      if (chunk.length + line.length > 1000) {
        embed.addFields({ name: index === 0 ? `Antrian (${totalSize} lagu)` : "Antrian (Lanjutan)", value: chunk, inline: false });
        chunk = "";
        index += 1;
      }
      chunk += line;
    }
    if (totalSize > tracks.length) {
      const remainder = `\n*... dan ${totalSize - tracks.length} lagu lainnya*`;
      chunk += chunk.length + remainder.length <= 1024 ? remainder : "";
    }
    if (chunk) {
      embed.addFields({ name: index === 0 ? `Antrian (${totalSize} lagu)` : "Antrian (Lanjutan)", value: chunk, inline: false });
    }
    return embed;
  }

  static autoplayNext(track) {
    const embed = new DiscordEmbedBuilder()
      .setTitle("Autoplay")
      .setDescription(`**[${track.title}](${track.url})**`)
      .setColor(Colors.Orange)
      .addFields(
        { name: "Durasi", value: track.durationText, inline: true },
        { name: "Uploader", value: track.uploader || "Unknown", inline: true },
      )
      .setFooter({ text: "Autoplay • Omnia Music" });
    if (track.thumbnail) embed.setThumbnail(track.thumbnail);
    return embed;
  }

  static error(message) {
    return new DiscordEmbedBuilder().setTitle("Error").setDescription(message).setColor(Colors.Red);
  }

  static info(title, description) {
    return new DiscordEmbedBuilder().setTitle(title).setDescription(description).setColor(Colors.Blue);
  }

  static success(title, description) {
    return new DiscordEmbedBuilder().setTitle(title).setDescription(description).setColor(Colors.Green);
  }
}
