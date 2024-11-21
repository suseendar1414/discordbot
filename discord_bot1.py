import os
import logging
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi
from langchain_openai import OpenAIEmbeddings
from openai import OpenAI
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import asyncio
from aiohttp import web
import re

# Enhanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

def load_environment():
    """Load and validate environment variables"""
    # Try to load from .env file
    load_dotenv()
    
    # Print current working directory and list files
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Files in directory: {os.listdir('.')}")
    
    # Try to read .env file directly
    try:
        with open('.env', 'r') as f:
            logger.info("Contents of .env file:")
            logger.info(f.read())
    except Exception as e:
        logger.warning(f"Could not read .env file: {e}")
    
    # Get environment variables with debug logging
    config = {}
    for var in ['DISCORD_TOKEN', 'OPENAI_API_KEY', 'MONGODB_URI', 'DB_NAME', 'PORT']:
        value = os.environ.get(var)
        config[var] = value
        # Log whether variable is set (without exposing sensitive values)
        if var in ['DISCORD_TOKEN', 'OPENAI_API_KEY', 'MONGODB_URI']:
            logger.info(f"{var}: {'SET' if value else 'NOT SET'}")
        else:
            logger.info(f"{var}: {value}")
    
    # Set defaults for optional variables
    config['DB_NAME'] = config['DB_NAME'] or 'quantified_ante'
    config['PORT'] = int(config['PORT'] or '8080')
    
    # Validate required variables
    missing_vars = []
    for var in ['DISCORD_TOKEN', 'OPENAI_API_KEY', 'MONGODB_URI']:
        if not config[var]:
            missing_vars.append(var)
    
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    return config

# Load environment variables at startup
config = load_environment()

# Use config values throughout your code
DISCORD_TOKEN = config['DISCORD_TOKEN']
OPENAI_API_KEY = config['OPENAI_API_KEY']
MONGODB_URI = config['MONGODB_URI']
DB_NAME = config['DB_NAME']
PORT = config['PORT']

# Validate required environment variables
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is not set")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is not set")
if not MONGODB_URI:
    raise ValueError("MONGODB_URI environment variable is not set")

# Log configuration (without sensitive details)
logger.info("Environment variables loaded")
logger.info(f"Database name: {DB_NAME}")
logger.info(f"Port: {PORT}")

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
            
            # Verify MONGODB_URI
            if not MONGODB_URI or MONGODB_URI == "your_mongodb_uri":
                raise ValueError("Invalid MONGODB_URI")
                
            connection_options = {
                'serverSelectionTimeoutMS': 5000,
                'connectTimeoutMS': 5000,
                'socketTimeoutMS': 5000,
                'maxPoolSize': 3,
                'minPoolSize': 1,
                'tls': True,
                'tlsCAFile': certifi.where()
            }
            
            # Create MongoDB client with full URI
            self.client = MongoClient(MONGODB_URI, **connection_options)
            
            # Test connection
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
        """Test database connection with proper error handling"""
        try:
            self.client.admin.command('ping')
            self.last_heartbeat = datetime.utcnow()
            return True, {
                'status': 'Connected',
                'database': DB_NAME,
                'last_heartbeat': self.last_heartbeat
            }
        except Exception as e:
            logger.error(f"Database connection test failed: {str(e)}")
            return False, str(e)

    def search_similar_chunks(self, query, k=5):
        """Search function optimized for trading terminology and concepts"""
        try:
            print(f"Searching for: {query}")
            
            # Clean query
            query_clean = query.lower().strip()
            words = query_clean.split()
            
            # Remove common question words
            stop_words = {'what', 'is', 'are', 'how', 'does', 'where', 'when', 'why', 'which'}
            core_terms = [w for w in words if w not in stop_words]
            core_query = ' '.join(core_terms)
            
            # Create trading-specific search patterns
            search_terms = set([
                core_query,
                query_clean,
                *core_terms,
                *(term.upper() for term in core_terms),  # For acronyms
                *(f"{a} {b}" for a, b in zip(core_terms, core_terms[1:])),  # Pairs
            ])
            
            # Build query with trading-specific patterns
            text_query = {
                "$or": []
            }
            
            for term in search_terms:
                if term:
                    text_query["$or"].extend([
                        # Definition matches
                        {"text": {"$regex": f"(?i)Definition:.*{re.escape(term)}", "$options": "i"}},
                        {"text": {"$regex": f"(?i){re.escape(term)}.*definition", "$options": "i"}},
                        
                        # Trading concept patterns
                        {"text": {"$regex": f"(?i){re.escape(term)}[\\s]*:[^\\n]*", "$options": "i"}},
                        {"text": {"$regex": f"(?i)• {re.escape(term)}:", "$options": "i"}},
                        
                        # FAQ patterns
                        {"text": {"$regex": f"(?i)FAQ.*{re.escape(term)}", "$options": "i"}},
                        {"text": {"$regex": f"(?i)Question:.*{re.escape(term)}", "$options": "i"}},
                        
                        # General term match
                        {"text": {"$regex": f"(?i)\\b{re.escape(term)}\\b", "$options": "i"}},
                    ])
            
            def extract_trading_context(text, term):
                """Extract trading-relevant context around a term."""
                paragraphs = text.split('\n\n')
                relevant_sections = []
                
                for i, para in enumerate(paragraphs):
                    if re.search(f"(?i)\\b{re.escape(term)}\\b", para):
                        start_idx = max(0, i - 1)
                        end_idx = min(len(paragraphs), i + 2)
                        context = '\n\n'.join(paragraphs[start_idx:end_idx])
                        context = re.sub(r'\s+', ' ', context)
                        context = context.strip()
                        
                        if len(context) > 50:
                            relevant_sections.append(context)
                
                return relevant_sections
            
            # Execute search
            results = list(self.docs_collection.find(text_query).limit(k))
            print(f"Text search found {len(results)} matches")
            
            # Process results with trading context
            processed_results = []
            for doc in results:
                if 'text' in doc:
                    for term in search_terms:
                        if term:
                            sections = extract_trading_context(doc['text'], term)
                            processed_results.extend(sections)
            
            # Remove duplicates while preserving order
            processed_results = list(dict.fromkeys(processed_results))
            
            # Try vector search if needed
            if len(processed_results) < 2:
                try:
                    query_embedding = embeddings_model.embed_query(core_query)
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
                    vector_results = list(self.docs_collection.aggregate(pipeline))
                    print(f"Vector search found {len(vector_results)} results")
                    
                    for doc in vector_results:
                        if 'text' in doc:
                            for term in search_terms:
                                if term:
                                    sections = extract_trading_context(doc['text'], term)
                                    processed_results.extend(sections)
                except Exception as ve:
                    print(f"Vector search failed: {ve}")
            
            # Remove duplicates again and limit results
            processed_results = list(dict.fromkeys(processed_results))[:k]
            
            # Log results
            if processed_results:
                print(f"Found {len(processed_results)} relevant chunks")
                for i, chunk in enumerate(processed_results[:2]):
                    preview = chunk[:200] + "..." if len(chunk) > 200 else chunk
                    print(f"Preview {i+1}: {preview}")
            else:
                print("No results found")
            
            return processed_results
            
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            return []

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        self.db = DatabaseManager()
        self.is_fully_ready = False
        self.startup_time = datetime.utcnow()

    async def setup_hook(self):
        try:
            await self.tree.sync()
            logger.info("✅ Commands synced globally!")
        except Exception as e:
            logger.error(f"❌ Command sync failed: {str(e)}")
            raise

    async def on_ready(self):
        self.is_fully_ready = True
        logger.info(f'Bot is ready! Logged in as {self.user}')
        for guild in self.guilds:
            logger.info(f'Connected to guild: {guild.name} (id: {guild.id})')

# Initialize bot and clients
bot = QABot()
try:
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_openai_api_key":
        raise ValueError("Invalid OpenAI API key")
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    embeddings_model = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
    logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {str(e)}")
    raise
embeddings_model = OpenAIEmbeddings()

# Health check endpoint
async def health_check(request):
    """Enhanced health check with proper startup checks and error handling"""
    try:
        status = {
            "status": "starting",
            "discord": False,
            "database": False,
            "uptime": None,
            "timestamp": datetime.utcnow().isoformat()
        }

        # Check Discord connection
        status["discord"] = bot.is_fully_ready
        if status["discord"]:
            status["uptime"] = (datetime.utcnow() - bot.startup_time).total_seconds()

        # Check MongoDB connection
        db_success, db_result = await bot.db.test_connection()
        status["database"] = db_success

        # Determine overall health status
        if status["discord"] and status["database"]:
            status["status"] = "healthy"
            return web.Response(
                text=f"Healthy - Discord: {status['discord']}, DB: {status['database']}, Uptime: {status['uptime']}s", 
                status=200
            )
        else:
            status["status"] = "unhealthy"
            return web.Response(
                text=f"Unhealthy - Discord: {status['discord']}, DB: {status['database']}", 
                status=503
            )

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return web.Response(
            text=f"Health check error: {str(e)}", 
            status=503
        )

# Setup web application
app = web.Application()
app.router.add_get('/', health_check)
app.router.add_get('/healthz', health_check)

# Bot Commands
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

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading concepts")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    try:
        await interaction.response.defer()
        
        logger.info(f"Question from {interaction.user.name} in {interaction.guild.name}: {question}")
        
        # Search for relevant content
        similar_chunks = bot.db.search_similar_chunks(question)
        
        if not similar_chunks:
            # Log failed question
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
            
            await interaction.followup.send(
                "I couldn't find relevant information. Please try rephrasing your question."
            )
            return
        
        # Combine chunks and generate response
        context = "\n".join(similar_chunks)
        
        prompt = f"""You are a knowledgeable Quantified Ante trading assistant. Answer the question based on the following context.
        Be specific and cite concepts from the context. If something isn't explicitly mentioned in the context, don't make assumptions.

        Context: {context}

        Question: {question}

        Please provide a detailed answer using only information found in the context above."""
        
        response = openai_client.chat.completions.create(
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
        
        # Log successful QA
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
        
        # Split long responses
        if len(answer) > 2000:
            parts = [answer[i:i+1990] for i in range(0, len(answer), 1990)]
            await interaction.followup.send(parts[0])
            for part in parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        logger.error(f"Ask command error: {str(e)}")
        await interaction.followup.send(f"Error: {str(e)}")

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

@bot.tree.command(name="debug", description="Debug database content")
@app_commands.default_permissions(administrator=True)
async def debug(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        # Get collection stats
        docs_count = bot.db.docs_collection.count_documents({})
        qa_count = bot.db.qa_collection.count_documents({})
        
        # Sample documents
        sample_doc = bot.db.docs_collection.find_one()
        
        debug_info = f"""📊 Database Debug Info:
Documents Collection: {docs_count} documents
QA History: {qa_count} entries

Sample Document Fields: {list(sample_doc.keys()) if sample_doc else 'No documents found'}
"""
        
        await interaction.followup.send(debug_info)
    except Exception as e:
        await interaction.followup.send(f"Debug error: {str(e)}")

@bot.event
async def on_command_error(ctx, error):
    """Global error handler for command errors"""
    logger.error(f"Command error: {error}")
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.")
    else:
        await ctx.send(f"An error occurred: {str(error)}")

async def start_bot():
    """Start the Discord bot with proper error handling"""
    try:
        await bot.start(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {str(e)}")
        raise

async def start_server():
    """Start the web server with proper error handling"""
    try:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', PORT)
        await site.start()
        logger.info(f"Web server started on port {PORT}")
    except Exception as e:
        logger.error(f"Failed to start web server: {str(e)}")
        raise

async def main():
    """Main function with proper error handling and graceful shutdown"""
    try:
        # Create tasks for both the bot and web server
        bot_task = asyncio.create_task(start_bot())
        server_task = asyncio.create_task(start_server())
        
        # Wait for both tasks to complete
        await asyncio.gather(bot_task, server_task)
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        # Clean up resources
        await bot.close()
    except Exception as e:
        logger.error(f"Application startup failed: {str(e)}")
        raise
    finally:
        # Ensure MongoDB connection is closed
        if bot.db.client:
            bot.db.client.close()

if __name__ == "__main__":
    try:
        # Verify all required services are properly configured
        if not all([DISCORD_TOKEN, OPENAI_API_KEY, MONGODB_URI]):
            raise ValueError("Missing required environment variables")
            
        logger.info("Starting services...")
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application crashed: {str(e)}")
        raise