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

def search_similar_chunks(self, query, k=3):
    """Search for similar chunks using vector similarity"""
    try:
        # Log the search attempt
        logger.info(f"Starting search for query: {query}")
        
        # First try exact text search
        logger.info("Attempting exact text search...")
        text_query = {"$text": {"$search": query}}
        results = list(self.docs_collection.find(text_query).limit(k))
        
        if not results:
            logger.info("No exact matches, trying regex search...")
            # Try regex search if exact search fails
            regex_query = {"text": {"$regex": f"(?i){query}"}}
            results = list(self.docs_collection.find(regex_query).limit(k))
        
        if not results:
            logger.info("No regex matches, attempting vector search...")
            try:
                # Generate query embedding
                query_embedding = embeddings_model.embed_query(query)
                
                # Check if vector index exists
                indexes = self.db.list_indexes()
                has_vector_index = any('vector_index' in idx.get('name', '') for idx in indexes)
                
                if not has_vector_index:
                    logger.warning("Vector index not found, falling back to basic search")
                    # Fallback to basic keyword search
                    basic_query = {"text": {"$regex": f".*{query}.*", "$options": "i"}}
                    results = list(self.docs_collection.find(basic_query).limit(k))
                else:
                    # Use vector search
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
            except Exception as ve:
                logger.error(f"Vector search failed: {ve}")
                # Fallback to basic search
                basic_query = {"text": {"$regex": f".*{query}.*", "$options": "i"}}
                results = list(self.docs_collection.find(basic_query).limit(k))
        
        # Log search results
        num_results = len(results)
        logger.info(f"Found {num_results} results")
        
        if num_results > 0:
            # Log a sample of what was found (first result)
            first_result = results[0].get('text', '')[:100]  # First 100 chars
            logger.info(f"Sample result: {first_result}...")
        else:
            logger.warning("No results found in any search method")
            
            # Debug: Log collection stats
            count = self.docs_collection.count_documents({})
            logger.info(f"Total documents in collection: {count}")
            
            # Sample a random document to verify data
            sample_doc = self.docs_collection.find_one()
            if sample_doc:
                logger.info("Sample document structure:")
                logger.info(f"Keys present: {list(sample_doc.keys())}")
            else:
                logger.warning("No documents found in collection")
        
        return [doc['text'] for doc in results]
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        logger.error(f"Search error details:", exc_info=True)
        return []

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
# Add these commands to your working bot code

@bot.tree.command(name="debug", description="Check database content and bot status")
async def debug(interaction: discord.Interaction):
    try:
        # Test MongoDB connection
        mongo_client.admin.command('ping')
        
        # Get basic stats
        docs_count = docs_collection.count_documents({})
        qa_count = qa_collection.count_documents({})
        
        debug_msg = f"""✅ System Status:
Bot: Connected as {bot.user}
Server: {interaction.guild.name}
Database: {mongo_client.get_database().name}

📊 Collection Stats:
- Documents: {docs_count}
- QA Entries: {qa_count}
"""
        
        # Get sample document
        sample = docs_collection.find_one()
        if sample:
            debug_msg += "\n📄 Sample Document:\n"
            debug_msg += f"Fields: {', '.join(sample.keys())}"
            if 'text' in sample:
                preview = sample['text'][:150] + "..." if len(sample['text']) > 150 else sample['text']
                debug_msg += f"\nContent Preview: {preview}"
                
        # Recent QA history
        recent_qa = list(qa_collection.find().sort('timestamp', -1).limit(3))
        if recent_qa:
            debug_msg += "\n\n📝 Recent Questions:\n"
            for qa in recent_qa:
                status = "✅" if qa.get('success', False) else "❌"
                q_time = qa['timestamp'].strftime("%H:%M:%S")
                debug_msg += f"{status} [{q_time}] {qa.get('question', 'N/A')}\n"
        
        await interaction.response.send_message(debug_msg)
        
    except Exception as e:
        logger.error(f"Debug error: {e}")
        await interaction.response.send_message(f"Error: {str(e)}")

@bot.tree.command(name="debug_search", description="Test the search functionality")
@app_commands.describe(test_query="Search query to test (optional)")
async def debug_search(interaction: discord.Interaction, test_query: str = None):
    try:
        await interaction.response.defer()
        
        # Use provided query or default
        query = test_query or "trading strategy"
        
        debug_msg = f"""🔍 Search Test:
Query: "{query}"

Searching..."""
        
        # Perform search
        results = search_similar_chunks(query)
        debug_msg += f"\nFound {len(results)} results."
        
        if results:
            debug_msg += "\n\n📑 Top Results:"
            for i, text in enumerate(results[:2], 1):
                preview = text[:200] + "..." if len(text) > 200 else text
                debug_msg += f"\n\n{i}. {preview}"
        else:
            # Show collection stats if no results
            total_docs = docs_collection.count_documents({})
            debug_msg += f"\n\nℹ️ No results found"
            debug_msg += f"\nTotal documents in collection: {total_docs}"
            
            # Show sample document
            sample = docs_collection.find_one()
            if sample:
                debug_msg += "\n\nSample document structure:"
                debug_msg += f"\nFields: {', '.join(sample.keys())}"
        
        # Split long messages
        if len(debug_msg) > 1990:
            chunks = [debug_msg[i:i+1990] for i in range(0, len(debug_msg), 1990)]
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)
        else:
            await interaction.followup.send(debug_msg)
            
    except Exception as e:
        logger.error(f"Debug search error: {e}")
        await interaction.followup.send(f"Error: {str(e)}")
        
@bot.event
async def on_command_error(ctx, error):
    logger.error(f"Command error: {error}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run(DISCORD_TOKEN)