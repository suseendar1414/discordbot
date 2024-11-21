import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
import discord
from discord.ext import commands
from discord import app_commands
import certifi
from datetime import datetime
import asyncio
from aiohttp import web
from openai import OpenAI
from langchain_openai import OpenAIEmbeddings

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
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DB_NAME = os.getenv('DB_NAME', 'quantified_ante')
PORT = int(os.getenv('PORT', '8080'))

# Initialize OpenAI
openai_client = OpenAI(api_key=OPENAI_API_KEY)
embeddings_model = OpenAIEmbeddings()

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
            self.docs_collection = self.db.documents
            
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

    def search_similar_chunks(self, query, k=3):
        """Search for similar chunks using vector similarity"""
        try:
            # Simple text search first
            text_query = {"text": {"$regex": f"(?i){query}"}}
            results = list(self.docs_collection.find(text_query).limit(k))
            
            if not results:
                # Try vector search
                query_embedding = embeddings_model.embed_query(query)
                pipeline = [
                    {
                        '$search': {
                            'index': 'vector_index',
                            'knnBeta': {
                                'vector': query_embedding,
                                'path': 'embedding',
                                'k': k
                            }
                        }
                    }
                ]
                results = list(self.docs_collection.aggregate(pipeline))
            
            return [doc['text'] for doc in results]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

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
        for guild in self.guilds:
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

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    try:
        # Immediately acknowledge the interaction
        await interaction.response.defer()
        
        # Log the question
        logger.info(f"Question from {interaction.user}: {question}")
        
        # Search for relevant content
        similar_chunks = bot.db.search_similar_chunks(question)
        
        if not similar_chunks:
            await interaction.followup.send(
                "I couldn't find relevant information. Please try rephrasing your question.",
                ephemeral=True
            )
            return
        
        # Generate response
        context = "\n".join(similar_chunks)
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a Quantified Ante trading assistant."},
                {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"}
            ]
        )
        
        answer = response.choices[0].message.content
        
        # Send response in chunks if needed
        if len(answer) > 1900:
            chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        logger.error(f"Ask error: {e}")
        if not interaction.response.is_done():
            await interaction.followup.send(
                "An error occurred while processing your question",
                ephemeral=True
            )

@bot.event
async def on_command_error(ctx, error):
    logger.error(f"Command error: {error}")

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