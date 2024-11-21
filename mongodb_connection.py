import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient, WriteConcern
from pymongo.read_preferences import ReadPreference
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
import discord
from discord.ext import commands
import certifi
from datetime import datetime, timedelta
import asyncio

# Enhanced logging
logging.basicConfig(
    level=logging.INFO,  # Changed to INFO to reduce noise
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
        self.next_health_check = datetime.utcnow()
        self.health_check_interval = timedelta(seconds=60)  # Increased to 60 seconds
        self.init_connection()

    def init_connection(self):
        """Initialize MongoDB connection with optimized settings"""
        try:
            logger.info("Initializing MongoDB connection...")
            
            # Optimized connection settings
            connection_options = {
                'serverSelectionTimeoutMS': 5000,     # Reduced timeout
                'connectTimeoutMS': 5000,
                'socketTimeoutMS': 5000,
                'maxPoolSize': 3,                     # Reduced pool size
                'minPoolSize': 1,
                'maxIdleTimeMS': 300000,             # 5 minutes idle time
                'heartbeatFrequencyMS': 30000,       # 30 seconds heartbeat
                'retryWrites': True,
                'w': 'majority',                     # Write concern
                'readPreference': 'primaryPreferred', # Read preference
                'tls': True,
                'tlsCAFile': certifi.where(),
                'compressors': ['zlib'],
                'zlibCompressionLevel': 6,
                'appname': 'DiscordBot-Railway'      # For monitoring
            }
            
            self.client = MongoClient(MONGODB_URI, **connection_options)
            
            # Quick connection test
            self.client.admin.command('ping')
            
            self.db = self.client[DB_NAME]
            self.qa_collection = self.db.get_collection(
                'qa_history',
                write_concern=WriteConcern(w='majority', wtimeout=5000)
            )
            
            self.connected = True
            self.last_heartbeat = datetime.utcnow()
            self.next_health_check = datetime.utcnow() + self.health_check_interval
            
            logger.info("✅ MongoDB connection initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.connected = False
            raise

    async def ensure_connection(self):
        """Check connection only if needed"""
        now = datetime.utcnow()
        
        # Only check if it's time or if not connected
        if not self.connected or now >= self.next_health_check:
            try:
                # Quick ping test
                self.client.admin.command('ping', serverSelectionTimeoutMS=2000)
                self.connected = True
                self.last_heartbeat = now
                self.next_health_check = now + self.health_check_interval
                logger.debug("Connection verified")
            except Exception as e:
                logger.warning(f"Connection check failed: {str(e)}")
                self.connected = False
                self.init_connection()

    async def test_connection(self):
        """Lightweight connection test"""
        try:
            await self.ensure_connection()
            return True, {
                'status': 'Connected',
                'database': DB_NAME,
                'last_heartbeat': self.last_heartbeat,
                'next_check': self.next_health_check
            }
        except Exception as e:
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
            # Start minimal monitoring
            self.loop.create_task(self.minimal_health_monitor())
            logger.info("Bot setup complete!")
        except Exception as e:
            logger.error(f"Setup failed: {str(e)}")
            raise

    async def minimal_health_monitor(self):
        """Minimal health monitoring"""
        while True:
            try:
                await self.db.ensure_connection()
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Health monitor error: {str(e)}")
                await asyncio.sleep(10)

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
                f"Last Heartbeat: {result['last_heartbeat'].strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"Next Check: {result['next_check'].strftime('%Y-%m-%d %H:%M:%S UTC')}"
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