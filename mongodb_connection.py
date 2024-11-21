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
from aiohttp import web

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
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB connection: {str(e)}")
            self.connected = False
            return False

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
        self.is_fully_ready = False

    async def setup_hook(self):
        try:
            await self.tree.sync()
            logger.info("Bot setup complete!")
        except Exception as e:
            logger.error(f"Setup failed: {str(e)}")
            raise

    async def on_ready(self):
        self.is_fully_ready = True
        logger.info(f'Bot is ready! Logged in as {self.user}')
        for guild in bot.guilds:
            logger.info(f'Connected to guild: {guild.name} (id: {guild.id})')

# Create the bot instance
bot = QABot()

# Health check web server
async def health_check(request):
    """Enhanced health check with startup grace period"""
    try:
        # Give the bot time to fully start up
        startup_grace_period = 10  # seconds
        for _ in range(startup_grace_period):
            if bot.is_fully_ready:
                break
            await asyncio.sleep(1)
        
        status = {
            "discord": bot.is_fully_ready,
            "database": False,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Check MongoDB connection
        success, _ = await bot.db.test_connection()
        status["database"] = success
        
        # Return 200 only if both services are ready
        if status["discord"] and status["database"]:
            return web.Response(
                text=f"Healthy: Discord={status['discord']}, DB={status['database']}, Time={status['timestamp']}", 
                status=200
            )
        else:
            return web.Response(
                text=f"Starting up: Discord={status['discord']}, DB={status['database']}, Time={status['timestamp']}", 
                status=503
            )
            
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return web.Response(text=str(e), status=503)

# Setup web application
app = web.Application()
app.router.add_get('/', health_check)
app.router.add_get('/healthz', health_check)

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