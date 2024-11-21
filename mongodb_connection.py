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
import aiohttp
from aiohttp import web
import threading

# Enhanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
MONGODB_URI = os.getenv('MONGODB_URI')
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DB_NAME = os.getenv('DB_NAME', 'quantified_ante')
PORT = int(os.getenv('PORT', '8080'))

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.connected = False
        self.last_heartbeat = datetime.utcnow()
        self.init_connection()

    def init_connection(self):
        """Initialize MongoDB connection"""
        try:
            logger.info("Initializing MongoDB connection...")
            
            connection_options = {
                'serverSelectionTimeoutMS': 5000,
                'connectTimeoutMS': 5000,
                'socketTimeoutMS': 5000,
                'maxPoolSize': 3,
                'minPoolSize': 1,
                'tls': True,
                'tlsCAFile': certifi.where()
            }
            
            self.client = MongoClient(MONGODB_URI, **connection_options)
            self.client.admin.command('ping')
            self.db = self.client[DB_NAME]
            self.qa_collection = self.db.qa_history
            
            self.connected = True
            self.last_heartbeat = datetime.utcnow()
            logger.info("✅ MongoDB connection initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.connected = False
            raise

    async def test_connection(self):
        """Test database connection"""
        try:
            self.client.admin.command('ping')
            return True, {
                'status': 'Connected',
                'database': DB_NAME,
                'last_heartbeat': self.last_heartbeat
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
            logger.info("Bot setup complete!")
        except Exception as e:
            logger.error(f"Setup failed: {str(e)}")
            raise

# Create the bot instance
bot = QABot()

# Health check web server
async def health_check(request):
    try:
        # Check Discord connection
        if not bot.is_ready():
            return web.Response(text="Discord bot not ready", status=503)
        
        # Check MongoDB connection
        success, _ = await bot.db.test_connection()
        if not success:
            return web.Response(text="Database not connected", status=503)
        
        return web.Response(text="OK", status=200)
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return web.Response(text=str(e), status=503)

# Setup web application
app = web.Application()
app.router.add_get('/', health_check)
app.router.add_get('/healthz', health_check)

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
                f"Last Heartbeat: {result['last_heartbeat'].strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
        else:
            await interaction.followup.send(f"⚠️ Bot is working but database connection failed: {result}")
    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")

async def start_bot():
    """Start the Discord bot"""
    try:
        await bot.start(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {str(e)}")
        raise

async def start_server():
    """Start the web server"""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

async def main():
    """Main function to run both the bot and web server"""
    await asyncio.gather(
        start_server(),
        start_bot()
    )

if __name__ == "__main__":
    logger.info("Starting services...")
    asyncio.run(main())