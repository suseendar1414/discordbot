import os
import logging
from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient
import certifi
from langchain_openai import OpenAIEmbeddings
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import asyncio
from aiohttp import web

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGODB_URI = os.getenv('MONGODB_URI')
PORT = int(os.getenv('PORT', '8080'))

class DatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.connected = False
        self.last_heartbeat = datetime.utcnow()
        self.init_connection()

    def init_connection(self):
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
            self.db = self.client['quantified_ante']
            self.docs_collection = self.db.documents
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
        try:
            self.client.admin.command('ping')
            return True, {
                'status': 'Connected',
                'database': 'quantified_ante',
                'last_heartbeat': self.last_heartbeat
            }
        except Exception as e:
            return False, str(e)

    def search_similar_chunks(self, query, k=5):
        """Search for similar chunks with better context and debug logging"""
        try:
            logger.info(f"Starting search for query: '{query}'")
            
            # Generate search terms from the query
            search_terms = [
                query.lower(),  # Full query
                *query.lower().split(),  # Individual words
                *(f"{a} {b}" for a, b in zip(query.lower().split(), query.lower().split()[1:]))  # Word pairs
            ]
            logger.info(f"Generated search terms: {search_terms}")
            
            # Build OR query for multiple terms
            text_query = {
                "$or": [
                    {"text": {"$regex": f"(?i).*{term}.*"}} 
                    for term in search_terms
                ]
            }
            
            # Try text search first
            results = list(self.docs_collection.find(text_query).limit(k))
            logger.info(f"Found {len(results)} text matches")
            
            # If no text results, try vector search
            if not results:
                logger.info("No text matches found, attempting vector search...")
                try:
                    embeddings_model = OpenAIEmbeddings()
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
                    logger.info(f"Found {len(results)} vector matches")
                except Exception as ve:
                    logger.error(f"Vector search failed: {ve}")
                    results = []
            
            if results:
                logger.info("Sample of found content:")
                for i, doc in enumerate(results[:2], 1):
                    preview = doc['text'][:100] + "..." if len(doc['text']) > 100 else doc['text']
                    logger.info(f"Result {i}: {preview}")
            
            return [doc['text'] for doc in results]
            
        except Exception as e:
            logger.error(f"Search error: {str(e)}", exc_info=True)
            return []

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        super().__init__(command_prefix='!', intents=intents)
        self.db = DatabaseManager()
        self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
        self.is_fully_ready = False

    async def setup_hook(self):
        try:
            await self.tree.sync()
            logger.info("Commands synced globally!")
        except Exception as e:
            logger.error(f"Setup failed: {str(e)}")
            raise

    async def on_ready(self):
        self.is_fully_ready = True
        logger.info(f'Bot is ready! Logged in as {self.user}')
        logger.info(f'Connected to {len(self.guilds)} servers:')
        for guild in self.guilds:
            logger.info(f'- {guild.name} (id: {guild.id})')

# Create bot instance
bot = QABot()

# Health check endpoints
async def health_check(request):
    try:
        status = {
            "discord": bot.is_fully_ready,
            "database": False,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        success, _ = await bot.db.test_connection()
        status["database"] = success
        
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

@bot.tree.command(name="debug_search", description="Debug search functionality")
async def debug_search(interaction: discord.Interaction, query: str):
    try:
        await interaction.response.defer()
        
        total_docs = bot.db.docs_collection.count_documents({})
        similar_chunks = bot.db.search_similar_chunks(query)
        
        debug_info = f"""🔍 Search Debug Info:
Query: "{query}"
Total documents in DB: {total_docs}
Results found: {len(similar_chunks)}

Sample Results:"""
        
        if similar_chunks:
            for i, chunk in enumerate(similar_chunks[:2], 1):
                preview = chunk[:200] + "..." if len(chunk) > 200 else chunk
                debug_info += f"\n\nResult {i}:\n{preview}"
        else:
            debug_info += "\nNo results found"
            
            sample = bot.db.docs_collection.find_one()
            if sample:
                debug_info += f"\n\nSample document structure:\nFields: {list(sample.keys())}"
        
        if len(debug_info) > 1990:
            parts = [debug_info[i:i+1990] for i in range(0, len(debug_info), 1990)]
            await interaction.followup.send(parts[0])
            for part in parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(debug_info)
            
    except Exception as e:
        logger.error(f"Debug search error: {str(e)}")
        await interaction.followup.send(f"Error during debug: {str(e)}")

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading concepts")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    try:
        logger.info(f"Question from {interaction.user.name} in {interaction.guild.name}: {question}")
        
        similar_chunks = bot.db.search_similar_chunks(question)
        
        if not similar_chunks:
            bot.db.qa_collection.insert_one({
                'timestamp': datetime.utcnow(),
                'guild_id': str(interaction.guild.id),
                'guild_name': interaction.guild.name,
                'user_id': str(interaction.user.id),
                'username': interaction.user.name,
                'question': question,
                'answer': "No relevant information found",
                'success': False
            })
            await interaction.followup.send("I couldn't find relevant information. Please try rephrasing your question.")
            return
        
        context = "\n".join(similar_chunks)
        
        prompt = f"""You are a knowledgeable Quantified Ante trading assistant. Answer the question based on the following context.
        Be specific and cite concepts from the context. If something isn't explicitly mentioned in the context, don't make assumptions.

        Context: {context}

        Question: {question}

        Please provide a detailed answer using only information found in the context above."""
        
        response = bot.openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a knowledgeable Quantified Ante trading assistant. Only use information explicitly stated in the provided context."
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.3
        )
        
        answer = response.choices[0].message.content
        
        bot.db.qa_collection.insert_one({
            'timestamp': datetime.utcnow(),
            'guild_id': str(interaction.guild.id),
            'guild_name': interaction.guild.name,
            'user_id': str(interaction.user.id),
            'username': interaction.user.name,
            'question': question,
            'answer': answer,
            'success': True
        })
        
        if len(answer) > 2000:
            parts = [answer[i:i+1990] for i in range(0, len(answer), 1990)]
            await interaction.followup.send(parts[0])
            for part in parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.error(error_msg)
        await interaction.followup.send(error_msg)

@bot.tree.command(name="stats", description="Get Q&A statistics for this server")
async def stats(interaction: discord.Interaction):
    try:
        total = bot.db.qa_collection.count_documents({'guild_id': str(interaction.guild.id)})
        successful = bot.db.qa_collection.count_documents({
            'guild_id': str(interaction.guild.id),
            'success': True
        })
        
        recent = list(bot.db.qa_collection.find(
            {'guild_id': str(interaction.guild.id)}
        ).sort('timestamp', -1).limit(5))
        
        stats_msg = f"""📊 Stats for {interaction.guild.name}:
Total Questions: {total}
Successful Answers: {successful}
Success Rate: {(successful/total*100 if total > 0 else 0):.1f}%

Recent Questions:"""
        
        for qa in recent:
            status = "✅" if qa["success"] else "❌"
            timestamp = qa["timestamp"].strftime("%Y-%m-%d %H:%M")
            stats_msg += f"\n{status} [{timestamp}] {qa['username']}: {qa['question']}"
        
        await interaction.response.send_message(stats_msg)
    except Exception as e:
        await interaction.response.send_message(f"Error getting stats: {str(e)}")

@bot.tree.command(name="ping", description="Test if the bot and database are working")
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