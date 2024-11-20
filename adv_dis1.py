import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
from discord.ext import commands
import discord
from discord import app_commands
from datetime import datetime
import certifi

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')

if not MONGODB_URI:
    raise ValueError("MONGODB_URI environment variable not set")

logger.info("Attempting to connect to MongoDB...")

class DatabaseManager:
    def __init__(self):
        # Initialize with basic settings
        try:
            self.client = MongoClient(
                MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000
            )
            # Test connection
            self.client.admin.command('ping')
            logger.info("Successfully connected to MongoDB")
            
            self.db = self.client.get_database()
            self.qa_collection = self.db.qa_history
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def store_qa(self, interaction, question, answer, success):
        try:
            result = self.qa_collection.insert_one({
                'timestamp': datetime.utcnow(),
                'guild_id': str(interaction.guild.id),
                'guild_name': interaction.guild.name,
                'user_id': str(interaction.user.id),
                'username': interaction.user.name,
                'question': question,
                'answer': answer,
                'success': success
            })
            return result.inserted_id
        except Exception as e:
            logger.error(f"Failed to store Q&A: {e}")
            raise

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.db = None  # Initialize later

    async def setup_hook(self):
        try:
            self.db = DatabaseManager()
            await self.tree.sync()
            logger.info("Commands synced globally!")
        except Exception as e:
            logger.error(f"Setup failed: {e}")
            raise

bot = QABot()

@bot.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {bot.user}')
    for guild in bot.guilds:
        logger.info(f'Connected to guild: {guild.name} (id: {guild.id})')

@bot.tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        # Basic ping test
        await interaction.followup.send("🏓 Pong! Bot is working!")
    except Exception as e:
        logger.error(f"Ping command failed: {e}")
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

@bot.tree.command(name="dbtest", description="Test database connection")
async def dbtest(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        if bot.db and bot.db.client:
            bot.db.client.admin.command('ping')
            await interaction.followup.send("✅ Database connection successful!")
        else:
            await interaction.followup.send("❌ Database not initialized!")
    except Exception as e:
        logger.error(f"Database test failed: {e}")
        await interaction.followup.send(f"Database connection failed: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")