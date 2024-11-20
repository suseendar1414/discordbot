
import os
import discord
from discord import app_commands
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = 1307930198817116221  # Your server ID

# Bot setup
class SimpleBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # This copies the global commands over to your guild
        MY_GUILD = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        logger.info("Commands synced!")

client = SimpleBot()

@client.event
async def on_ready():
    logger.info(f"Bot is ready! Logged in as {client.user}")

@client.tree.command(
    name="hello",
    description="Says hello"
)
async def hello(interaction: discord.Interaction):
    try:
        await interaction.response.send_message(f"Hello, {interaction.user.name}!")
    except Exception as e:
        logger.error(f"Error in hello command: {e}")

@client.tree.command(
    name="ping",
    description="Simple ping command"
)
async def ping(interaction: discord.Interaction):
    try:
        await interaction.response.send_message("Pong!")
    except Exception as e:
        logger.error(f"Error in ping command: {e}")

@client.tree.command(
    name="echo",
    description="Repeats your message"
)
@app_commands.describe(message="The message to repeat")
async def echo(interaction: discord.Interaction, message: str):
    try:
        await interaction.response.send_message(f"You said: {message}")
    except Exception as e:
        logger.error(f"Error in echo command: {e}")

# Error handling for app commands
@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"Command error: {str(error)}")
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "An error occurred while processing the command.",
            ephemeral=True
        )

if __name__ == "__main__":
    logger.info("Starting bot...")
    client.run(DISCORD_TOKEN)
