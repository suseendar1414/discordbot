import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

# Enhanced logging setup
logging.basicConfig(
    level=logging.DEBUG,  # Changed to DEBUG for more detailed logs
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI')
DB_NAME = 'quantified_ante'

class DatabaseManager:
    def __init__(self):
        try:
            logger.info("Attempting MongoDB Atlas connection...")
            
            if not MONGODB_URI:
                raise ValueError("MONGODB_URI environment variable is not set")
            
            # Modified MongoDB connection with SSL settings
            self.client = MongoClient(
                MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                ssl=True,
                ssl_cert_reqs='CERT_REQUIRED',
                tlsAllowInvalidCertificates=False,
                tlsCAFile=certifi.where()
            )
            
            # Test connection before proceeding
            self.client.server_info()
            
            self.db = self.client[DB_NAME]
            self.qa_collection = self.db.qa_history
            
            collections = self.db.list_collection_names()
            logger.info(f"Available collections: {collections}")
            
            logger.info(f"Successfully connected to MongoDB database: {DB_NAME}")
            
        except Exception as e:
            logger.error(f"MongoDB connection failed: {str(e)}")
            raise


    def mask_mongodb_uri(self, uri):
        """Masks sensitive information in MongoDB URI for logging."""
        if not uri:
            return None
        try:
            # Simple masking - you might want to improve this
            return uri.replace('//', '//***:***@') if '@' in uri else uri
        except:
            return "Invalid URI format"

    async def test_connection(self):
        try:
            # More comprehensive connection test
            server_info = self.client.server_info()
            collections = self.db.list_collection_names()
            
            connection_details = {
                "server_version": server_info.get("version", "unknown"),
                "collections": collections,
                "database": DB_NAME
            }
            
            return True, connection_details
            
        except Exception as e:
            logger.error(f"Database test failed: {str(e)}")
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
            logger.error(f"Setup failed: {str(e)}")
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
                f"✅ Bot and database are working!\n"
                f"Connected to: {interaction.guild.name}\n"
                f"MongoDB Version: {result['server_version']}\n"
                f"Database: {result['database']}\n"
                f"Available collections: {', '.join(result['collections'])}"
            )
        else:
            await interaction.followup.send(f"⚠️ Bot is working but database connection failed: {result}")
    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")