import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient, ReadPreference
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
import discord
from discord.ext import commands
import certifi
from datetime import datetime
import asyncio

# Enhanced logging with MongoDB topology logging
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
        """Initialize MongoDB connection with optimized settings for high latency"""
        try:
            logger.info("Initializing MongoDB connection with optimized settings...")
            
            # Connection options optimized for high latency
            connection_options = {
                'serverSelectionTimeoutMS': 15000,      # Reduced from 30000
                'connectTimeoutMS': 15000,              # Reduced from 20000
                'socketTimeoutMS': 15000,               # Reduced from 20000
                'maxPoolSize': 5,                       # Reduced pool size
                'minPoolSize': 1,
                'maxIdleTimeMS': 120000,               # 2 minutes idle time
                'heartbeatFrequencyMS': 15000,         # Increased heartbeat frequency
                'retryWrites': True,
                'retryReads': True,
                'waitQueueTimeoutMS': 10000,
                'localThresholdMS': 15000,             # Increased local threshold
                'tls': True,
                'tlsCAFile': certifi.where(),
                'directConnection': False,
                'compressors': ['zlib'],               # Enable compression
                'zlibCompressionLevel': 6              # Moderate compression level
            }
            
            # Initialize client with optimized settings
            self.client = MongoClient(MONGODB_URI, **connection_options)
            
            # Test connection and initialize database with shorter timeout
            self.client.admin.command('ping', serverSelectionTimeoutMS=5000)
            self.db = self.client[DB_NAME]
            
            # Cache collections reference
            self.qa_collection = self.db.qa_history
            
            self.connected = True
            logger.info("✅ MongoDB connection initialized successfully")
            
            # Log connection info
            server_info = self.client.server_info()
            logger.info(f"Connected to MongoDB version: {server_info.get('version', 'unknown')}")
            
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.connected = False
            raise

    async def ensure_connection(self):
        """Ensure database connection is active with retry logic"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                if not self.connected:
                    self.init_connection()
                else:
                    # Quick ping with timeout
                    self.client.admin.command('ping', serverSelectionTimeoutMS=5000)
                    self.last_heartbeat = datetime.utcnow()
                return
            except Exception as e:
                logger.warning(f"Connection check failed (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                else:
                    self.connected = False
                    raise

    async def test_connection(self):
        """Test database connection with quick operations"""
        try:
            await self.ensure_connection()
            
            # Quick operations with timeout
            collections = self.db.list_collection_names(
                serverSelectionTimeoutMS=5000
            )
            
            # Simple ping instead of write operation
            self.client.admin.command('ping')
            
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
        self.health_check_interval = 30  # seconds

    async def setup_hook(self):
        try:
            await self.tree.sync()
            logger.info("Bot commands synced!")
            # Start health monitor with configured interval
            self.loop.create_task(self.monitor_connection())
        except Exception as e:
            logger.error(f"Failed to sync commands: {str(e)}")
            raise

    async def monitor_connection(self):
        """Monitor database connection health"""
        while True:
            try:
                await self.db.ensure_connection()
                logger.debug("Connection health check passed")
                await asyncio.sleep(self.health_check_interval)
            except Exception as e:
                logger.error(f"Connection monitor error: {str(e)}")
                await asyncio.sleep(5)

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