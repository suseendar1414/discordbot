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
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 5  # seconds

    async def connect(self):
        """Establish database connection with retry logic"""
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                logger.info(f"Attempting MongoDB connection (attempt {self.reconnect_attempts + 1})")
                
                # Initialize MongoDB client with optimized settings for Railway
                self.client = MongoClient(
                    MONGODB_URI,
                    serverSelectionTimeoutMS=30000,
                    connectTimeoutMS=30000,
                    socketTimeoutMS=30000,
                    maxPoolSize=50,
                    retryWrites=True,
                    tls=True,
                    tlsCAFile=certifi.where()
                )
                
                # Test connection
                self.client.admin.command('ping')
                
                # Initialize database and collections
                self.db = self.client[DB_NAME]
                
                # Log successful connection
                logger.info("✅ Successfully connected to MongoDB!")
                logger.info(f"Available databases: {self.client.list_database_names()}")
                logger.info(f"Collections in {DB_NAME}: {self.db.list_collection_names()}")
                
                # Reset reconnection attempts on successful connection
                self.reconnect_attempts = 0
                return True
                
            except (ServerSelectionTimeoutError, ConnectionFailure) as e:
                self.reconnect_attempts += 1
                logger.error(f"Connection attempt {self.reconnect_attempts} failed: {str(e)}")
                
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    logger.info(f"Retrying in {self.reconnect_delay} seconds...")
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    logger.error("Max reconnection attempts reached")
                    raise
                    
            except Exception as e:
                logger.error(f"Unexpected error during connection: {str(e)}")
                raise

    async def ensure_connected(self):
        """Ensure database connection is active"""
        try:
            if not self.client:
                await self.connect()
            else:
                # Test existing connection
                self.client.admin.command('ping')
        except Exception:
            await self.connect()

    async def test_connection(self):
        """Test database connection with retry logic"""
        try:
            await self.ensure_connected()
            
            # Test write operation
            test_collection = self.db.test
            result = test_collection.insert_one({
                "test": True,
                "timestamp": datetime.utcnow()
            })
            
            # Clean up test document
            test_collection.delete_one({"_id": result.inserted_id})
            
            collections = self.db.list_collection_names()
            return True, {
                'status': 'Connected',
                'database': DB_NAME,
                'collections': collections
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
            logger.info("Initializing bot...")
            await self.db.connect()
            await self.tree.sync()
            logger.info("Bot setup complete!")
        except Exception as e:
            logger.error(f"Bot setup failed: {str(e)}")
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
                f"Database: {result['database']}\n"
                f"Collections: {', '.join(result['collections'])}"
            )
        else:
            await interaction.followup.send(f"⚠️ Bot is working but database connection failed: {result}")
    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")

# Periodic connection check
async def check_connection():
    while True:
        try:
            await bot.db.ensure_connected()
            await asyncio.sleep(60)  # Check every minute
        except Exception as e:
            logger.error(f"Connection check failed: {str(e)}")
            await asyncio.sleep(5)

@bot.event
async def on_connect():
    # Start connection checker
    bot.loop.create_task(check_connection())

if __name__ == "__main__":
    logger.info("Starting bot...")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {str(e)}")
        raise