"""
Omnia Music Bot — Main Entry Point
Discord music bot with YouTube playback, queue, loop, autoplay, and auto disconnect.
"""

import os
import asyncio
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

# ─────────────────────── Logging Setup ───────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('omnia')

# Reduce noise from discord.py and yt-dlp
logging.getLogger('discord').setLevel(logging.INFO)
logging.getLogger('discord.http').setLevel(logging.INFO)

# ─────────────────────── Environment ───────────────────────

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    logger.error("DISCORD_TOKEN tidak ditemukan di .env file!")
    logger.error("Silakan isi token di file .env")
    exit(1)

# ─────────────────────── Bot Setup ───────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    member_cache_flags=discord.MemberCacheFlags.from_intents(intents),
    description='Omnia Music Bot 🎵'
)


@bot.event
async def on_ready():
    """Called when bot is ready."""
    logger.info(f'✅ Bot {bot.user.name} sudah online!')
    logger.info(f'🆔 Bot ID: {bot.user.id}')
    logger.info(f'🌐 Servers: {len(bot.guilds)}')
    logger.info('-----------------------------------')

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f'⚡ Synced {len(synced)} slash commands')
    except Exception as e:
        logger.error(f'❌ Gagal sync commands: {e}')

    # Set activity
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="/play 🎵"
        )
    )


async def load_cogs():
    """Load all cogs."""
    cogs = ['cogs.music']
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            logger.info(f'📦 Loaded cog: {cog}')
        except Exception as e:
            logger.error(f'❌ Failed to load {cog}: {e}')


async def main():
    """Main entry point."""
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


# ─────────────────────── Run ───────────────────────

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info('🛑 Bot dihentikan oleh user.')
