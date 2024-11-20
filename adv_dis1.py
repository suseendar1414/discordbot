import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
import discord
from discord.ext import commands
from discord import app_commands
import certifi
from urllib.parse import quote_plus

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,  # Keep DEBUG level for deployment troubleshooting
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables - with Railway fallback
load_dotenv()

# Get environment variables with fallbacks
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')
MONGODB_URI = os.environ.get('MONGODB_URI')
DB_NAME = os.environ.get('DB_NAME', 'quantified_ante')

class DatabaseManager:
    def __init__(self):
        try:
            logger.info("Attempting MongoDB connection in Railway environment...")
            
            if not MONGODB_URI:
                raise ValueError("MONGODB_URI environment variable is not set in Railway")
            
            # Parse and reconstruct the URI to ensure proper encoding
            logger.info("Initializing database connection...")
            
            # Create MongoDB client with Railway-specific settings
            self.client = MongoClient(
                MONGODB_URI,
                serverSelectionTimeoutMS=10000,  # Increased timeout for Railway
                connectTimeoutMS=10000,
                tls=True,
                tlsCAFile=certifi.where(),
                retryWrites=True,
                w='majority'
            )
            
            # Test connection immediately
            self.client.admin.command('ping')
            
            self.db = self.client[DB_NAME]
            self.qa_collection = self.db.qa_history
            
            # Log successful connection
            db_names = self.client.list_database_names()
            collections = self.db.list_collection_names()
            logger.info(f"Successfully connected to MongoDB. Available databases: {db_names}")
            logger.info(f"Collections in {DB_NAME}: {collections}")
            
        except Exception as e:
            logger.error(f"Railway MongoDB connection failed: {str(e)}")
            raise

    async def test_connection(self):
        try:
            # Comprehensive connection test
            self.client.admin.command('ping')
            collections = self.db.list_collection_names()
            return True, {
                'status': 'Connected',
                'database': DB_NAME,
                'collections': collections
            }
        except Exception as e:
            logger.error(f"Railway database test failed: {str(e)}")
            return False, str(e)

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.db = None

    async def setup_hook(self):
        try:
            self.db = DatabaseManager()
            await self.tree.sync()
            logger.info("Commands synced globally!")
        except Exception as e:
            logger.error(f"Railway setup failed: {str(e)}")
            raise

bot = QABot()

@bot.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {bot.user}')
    for guild in bot.guilds:
        logger.info(f'Connected to guild: {guild.name} (id: {guild.id})')

@bot.tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        success, result = await bot.db.test_connection()
        if success:
            await interaction.followup.send(
                f"✅ Bot and database are working in Railway!\n"
                f"Connected to: {interaction.guild.name}\n"
                f"Database: {result['database']}\n"
                f"Collections: {', '.join(result['collections'])}"
            )
        else:
            await interaction.followup.send(f"⚠️ Bot is working but Railway database connection failed: {result}")
    except Exception as e:
        await interaction.followup.send(f"Error in Railway: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting bot in Railway environment...")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot in Railway: {e}")