import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
import discord
from discord.ext import commands
import certifi
from datetime import datetime
import asyncio

# Enhanced logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
MONGODB_URI = os.getenv('MONGODB_URI')
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DB_NAME = os.getenv('DB_NAME', 'quantified_ante')

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.connected = False
        self.last_heartbeat = datetime.utcnow()
        self.init_connection()

    def init_connection(self):
        """Initialize MongoDB connection with optimized settings"""
        try:
            logger.info("Initializing MongoDB connection...")
            
            # Simplified connection options
            connection_options = {
                'serverSelectionTimeoutMS': 30000,
                'connectTimeoutMS': 20000,
                'socketTimeoutMS': 20000,
                'maxPoolSize': 10,
                'minPoolSize': 1,
                'retryWrites': True,
                'tls': True,
                'tlsCAFile': certifi.where()
            }
            
            # Initialize client with optimized settings
            self.client = MongoClient(MONGODB_URI, **connection_options)
            
            # Test connection and initialize database
            self.client.admin.command('ping')
            self.db = self.client[DB_NAME]
            
            # Initialize collections
            self.qa_collection = self.db.qa_history
            
            self.connected = True
            logger.info("✅ MongoDB connection initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.connected = False
            raise

    async def ensure_connection(self):
        """Ensure database connection is active"""
        try:
            if not self.connected:
                self.init_connection()
            else:
                # Test existing connection
                self.client.admin.command('ping')
                self.last_heartbeat = datetime.utcnow()
        except Exception as e:
            logger.error(f"Connection check failed: {str(e)}")
            self.connected = False
            self.init_connection()

    async def test_connection(self):
        """Test database connection"""
        try:
            await self.ensure_connection()
            collections = self.db.list_collection_names()
            
            # Test write operation
            test_doc = {
                "test": True,
                "timestamp": datetime.utcnow()
            }
            result = self.db.connection_tests.insert_one(test_doc)
            self.db.connection_tests.delete_one({"_id": result.inserted_id})
            
            return True, {
                'status': 'Connected',
                'database': DB_NAME,
                'collections': collections,
                'last_heartbeat': self.last_heartbeat
            }
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False, str(e)

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.db = DatabaseManager()

    async def setup_hook(self):
        try:
            await self.tree.sync()
            logger.info("Bot commands synced!")
        except Exception as e:
            logger.error(f"Failed to sync commands: {str(e)}")
            raise

# Connection health check task
async def monitor_connection(db_manager: DatabaseManager):
    while True:
        try:
            await db_manager.ensure_connection()
            logger.debug("Connection health check passed")
            await asyncio.sleep(30)  # Check every 30 seconds
        except Exception as e:
            logger.error(f"Connection monitor error: {str(e)}")
            await asyncio.sleep(5)

bot = QABot()

@bot.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {bot.user}')
    # Start connection monitor
    bot.loop.create_task(monitor_connection(bot.db))
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
                f"Database: {result['database']}\n"
                f"Collections: {', '.join(result['collections'])}\n"
                f"Last Heartbeat: {result['last_heartbeat'].strftime('%Y-%m-%d %H:%M:%S UTC')}"
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
        logger.error(f"Failed to start bot: {str(e)}")
        raise