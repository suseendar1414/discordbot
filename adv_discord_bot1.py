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

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGODB_URI = os.getenv('MONGODB_URI')

# Initialize OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# MongoDB setup
mongo_client = MongoClient(
    MONGODB_URI,
    tls=True,
    tlsCAFile=certifi.where()
)
db = mongo_client['quantified_ante']
docs_collection = db['documents']
qa_collection = db['qa_history']

# Initialize embeddings
embeddings_model = OpenAIEmbeddings()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
    async def setup_hook(self):
        try:
            await self.tree.sync()  # Syncs commands globally
            logger.info("✅ Commands synced globally!")
            
            # Verify sync by listing registered commands
            commands = await self.tree.fetch_commands()
            logger.info(f"Registered commands: {[cmd.name for cmd in commands]}")
        except Exception as e:
            logger.error(f"❌ Command sync failed: {str(e)}")
            raise

    async def on_ready(self):
        logger.info(f'Bot is ready! Logged in as {bot.user}')
        logger.info(f'Connected to {len(bot.guilds)} servers:')
        for guild in bot.guilds:
            logger.info(f'- {guild.name} (id: {guild.id})')

bot = QABot()

def search_similar_chunks(query, k=5):
    """Search for similar chunks using multiple search strategies"""
    try:
        logger.info(f"Starting search for query: '{query}'")
        
        # 1. Prepare search terms for better matching
        search_terms = [
            query.lower(),  # Full query
            *[term.strip() for term in query.lower().split() if term.strip()],  # Individual words
            # Word pairs for better context matching
            *[f"{a} {b}".strip() for a, b in zip(query.lower().split(), query.lower().split()[1:]) if a.strip() and b.strip()]
        ]
        logger.info(f"Search terms: {search_terms}")
        
        results = []
        
        # 2. Try exact text search first
        if not results:
            text_query = {
                "$or": [
                    {"text": {"$regex": f"(?i){term}"}} 
                    for term in search_terms
                ]
            }
            results = list(docs_collection.find(text_query).limit(k))
            logger.info(f"Text search found {len(results)} results")
        
        # 3. Try vector search if text search fails
        if not results:
            logger.info("Attempting vector search...")
            try:
                query_embedding = embeddings_model.embed_query(query)
                
                # Verify vector index exists
                indexes = docs_collection.list_indexes()
                has_vector_index = any('vector_index' in idx.get('name', '') for idx in indexes)
                
                if has_vector_index:
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
                    results = list(docs_collection.aggregate(pipeline))
                    logger.info(f"Vector search found {len(results)} results")
            except Exception as ve:
                logger.error(f"Vector search failed: {ve}", exc_info=True)
        
        # 4. If still no results, try fuzzy text search
        if not results:
            logger.info("Attempting fuzzy text search...")
            fuzzy_query = {
                "$or": [
                    {"text": {"$regex": f"(?i).*{term}.*"}} 
                    for term in search_terms
                ]
            }
            results = list(docs_collection.find(fuzzy_query).limit(k))
            logger.info(f"Fuzzy search found {len(results)} results")
        
        # Log results for debugging
        if results:
            for i, doc in enumerate(results[:2]):
                preview = doc.get('text', '')[:100]
                logger.info(f"Result {i+1} preview: {preview}...")
        else:
            # Debug information if no results found
            doc_count = docs_collection.count_documents({})
            logger.warning(f"No results found. Collection has {doc_count} documents")
            sample_doc = docs_collection.find_one()
            if sample_doc:
                logger.info(f"Sample document fields: {list(sample_doc.keys())}")
        
        return [doc.get('text', '') for doc in results if doc.get('text')]
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}", exc_info=True)
        return []

# Helper function to verify database setup
async def verify_db_setup():
    try:
        # Test basic connectivity
        mongo_client.admin.command('ping')
        
        # Verify collections exist
        db_list = mongo_client.list_database_names()
        if 'quantified_ante' not in db_list:
            logger.error("Database 'quantified_ante' not found!")
            return False
            
        # Check collection contents
        doc_count = docs_collection.count_documents({})
        logger.info(f"Found {doc_count} documents in collection")
        
        # Verify indexes
        indexes = list(docs_collection.list_indexes())
        logger.info(f"Collection indexes: {[idx.get('name') for idx in indexes]}")
        
        # Sample a document
        sample = docs_collection.find_one()
        if sample:
            logger.info(f"Sample document fields: {list(sample.keys())}")
            if 'text' not in sample:
                logger.error("Documents missing 'text' field!")
                return False
        else:
            logger.error("No documents found in collection!")
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"Database verification failed: {str(e)}", exc_info=True)
        return False

@bot.tree.command(name="debug_db", description="Debug database content")
async def debug_db(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        # Get collection stats
        doc_count = bot.db.docs_collection.count_documents({})
        
        # Sample a document
        sample_doc = bot.db.docs_collection.find_one()
        
        # Check indexes
        indexes = list(bot.db.docs_collection.list_indexes())
        index_names = [index.get('name') for index in indexes]
        
        response = (
            f"📊 Database Debug Info:\n"
            f"Total documents: {doc_count}\n"
            f"Indexes: {', '.join(index_names)}\n\n"
        )
        
        if sample_doc:
            response += (
                f"📄 Sample document structure:\n"
                f"Fields: {', '.join(sample_doc.keys())}\n"
                f"Text preview: {sample_doc.get('text', 'N/A')[:100]}...\n"
            )
        else:
            response += "❌ No documents found in collection"
        
        await interaction.followup.send(response)
        
    except Exception as e:
        logger.error(f"Debug command error: {e}")
        await interaction.followup.send(
            "An error occurred while debugging the database",
            ephemeral=True
        )

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')
    await bot.tree.sync()

@bot.tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    try:
        # Immediately acknowledge the interaction
        await interaction.response.defer(ephemeral=True)
        
        # Test MongoDB connection
        mongo_client.admin.command('ping')
        mongo_status = "Connected"
        
        response = f"""Bot Status: Online
MongoDB: {mongo_status}
Latency: {round(bot.latency * 1000)}ms"""
        
        await interaction.followup.send(response, ephemeral=True)
    except Exception as e:
        logger.error(f"Ping error: {e}")
        # Make sure we haven't already responded
        if not interaction.response.is_done():
            await interaction.response.send_message("Error checking status", ephemeral=True)

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    try:
        # Immediately acknowledge the interaction
        await interaction.response.defer()
        
        # Log the question
        logger.info(f"Question from {interaction.user}: {question}")
        
        # Search for relevant content
        similar_chunks = search_similar_chunks(question)
        
        if not similar_chunks:
            await interaction.followup.send(
                "I couldn't find relevant information. Please try rephrasing your question.",
                ephemeral=True
            )
            return
        
        # Generate response
        context = "\n".join(similar_chunks)
        response = client.chat.completions.create(
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
            await interaction.response.send_message(
                "An error occurred while processing your question",
                ephemeral=True
            )


@bot.event
async def on_command_error(ctx, error):
    logger.error(f"Command error: {error}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run(DISCORD_TOKEN)