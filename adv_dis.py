import os
import logging
from dotenv import load_dotenv
import discord
from discord import app_commands

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Bot setup
class QABot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        
    async def setup_hook(self):
        # This copies the global commands over to your guild.
        logger.info("Syncing commands...")
        await self.tree.sync()
        logger.info("Commands synced!")

client = QABot()

@client.event
async def on_ready():
    logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
    logger.info(f'Connected to {len(client.guilds)} guilds:')
    for guild in client.guilds:
        logger.info(f'- {guild.name} (ID: {guild.id})')

@client.tree.command(name="hello", description="Says hello")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f'Hi, {interaction.user.name}!')

@client.tree.command(name="ping", description="Check if bot is working")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f'Pong! ({round(client.latency * 1000)}ms)')

if __name__ == "__main__":
    logger.info("Starting bot....")
    client.run(DISCORD_TOKEN)