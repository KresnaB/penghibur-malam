import "dotenv/config";
import libsodium from "libsodium-wrappers";
import { ActivityType, Client, GatewayIntentBits } from "discord.js";
import { DEBUG_MEMORY, DEBUG_MEMORY_INTERVAL_MS } from "./config.js";
import { commandDefinitions, handleInteraction, handleVoiceStateUpdate } from "./commands.js";
import { createLogger } from "./logger.js";
import { MusicManager } from "./musicManager.js";
import { YtdlService } from "./player/ytdlService.js";

const logger = createLogger("omnia");

const token = process.env.DISCORD_TOKEN;
if (!token) {
  logger.error("DISCORD_TOKEN tidak ditemukan di environment");
  process.exit(1);
}

await libsodium.ready;

const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent],
});

const manager = new MusicManager(client);

client.once("ready", async () => {
  logger.info(`Bot ${client.user.username} sudah online`);
  logger.info(`Servers: ${client.guilds.cache.size}`);
  await client.application.commands.set(commandDefinitions);
  await client.user.setPresence({
    activities: [{ type: ActivityType.Listening, name: "/play 🎵" }],
    status: "online",
  });
  void YtdlService.warmup();
  if (DEBUG_MEMORY) {
    setInterval(() => {
      const usage = process.memoryUsage();
      logger.info("Memory snapshot", {
        rssMiB: (usage.rss / 1024 / 1024).toFixed(1),
        heapMiB: (usage.heapUsed / 1024 / 1024).toFixed(1),
        players: manager.players.size,
      });
    }, DEBUG_MEMORY_INTERVAL_MS);
  }
});

client.on("interactionCreate", async (interaction) => {
  try {
    await handleInteraction(interaction, manager);
  } catch (error) {
    logger.error("Interaction failed", { error: String(error), command: interaction.commandName || interaction.customId });
    if (interaction.isRepliable()) {
      const payload = { content: "Terjadi error saat memproses command.", ephemeral: true };
      if (interaction.deferred || interaction.replied) {
        await interaction.followUp(payload).catch(() => {});
      } else {
        await interaction.reply(payload).catch(() => {});
      }
    }
  }
});

client.on("voiceStateUpdate", async (oldState, newState) => {
  try {
    await handleVoiceStateUpdate(oldState, newState, manager);
  } catch (error) {
    logger.warn("voiceStateUpdate handler error", { error: String(error) });
  }
});

process.on("SIGINT", async () => {
  for (const player of manager.players.values()) {
    await player.disconnect().catch(() => {});
  }
  client.destroy();
  process.exit(0);
});

await client.login(token);
