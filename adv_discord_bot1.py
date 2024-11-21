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
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        try:
            await self.tree.sync()
            logger.info("Commands synced!")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

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

@bot.tree.command(name="debug", description="Debug database and bot status")
async def debug(interaction: discord.Interaction):
    """Command to check database status and content"""
    try:
        await interaction.response.defer()
        
        debug_info = "🔧 Debug Information:\n\n"
        
        # 1. Check MongoDB Connection
        try:
            mongo_client.admin.command('ping')
            debug_info += "📡 MongoDB Connection: ✅ Connected\n"
        except Exception as e:
            debug_info += f"📡 MongoDB Connection: ❌ Error: {str(e)}\n"
        
        # 2. Document Collections Stats
        try:
            # Check documents collection
            docs_count = docs_collection.count_documents({})
            debug_info += f"\n📚 Documents Collection:\n"
            debug_info += f"Total documents: {docs_count}\n"
            
            # Sample document structure
            sample_doc = docs_collection.find_one()
            if sample_doc:
                debug_info += "Document structure:\n"
                debug_info += f"Fields: {', '.join(sample_doc.keys())}\n"
                # Show a preview of the text content
                if 'text' in sample_doc:
                    preview = sample_doc['text'][:200] + "..." if len(sample_doc['text']) > 200 else sample_doc['text']
                    debug_info += f"Sample text preview:\n{preview}\n"
            
            # Check QA history collection
            qa_count = qa_collection.count_documents({})
            debug_info += f"\n💬 QA History Collection:\n"
            debug_info += f"Total QA pairs: {qa_count}\n"
            
            # Recent questions
            recent_questions = list(qa_collection.find().sort('timestamp', -1).limit(3))
            if recent_questions:
                debug_info += "\nRecent questions:\n"
                for qa in recent_questions:
                    status = "✅" if qa.get('success', False) else "❌"
                    debug_info += f"{status} {qa.get('question', 'N/A')}\n"
            
        except Exception as e:
            debug_info += f"\nCollection Stats Error: {str(e)}\n"
        
        await interaction.followup.send(debug_info)
        
    except Exception as e:
        logger.error(f"Debug command error: {str(e)}")
        await interaction.followup.send(f"Error during debug: {str(e)}")

@bot.tree.command(name="debug_search", description="Test search functionality")
@app_commands.describe(query="Test query to search for")
async def debug_search(interaction: discord.Interaction, query: str = None):
    """Command to test search functionality"""
    try:
        await interaction.response.defer()
        
        debug_info = "🔍 Search Debug Results:\n\n"
        
        # If no query provided, use a test query
        if not query:
            query = "trading basics"
            debug_info += f"Using test query: '{query}'\n\n"
        else:
            debug_info += f"Query: '{query}'\n\n"
        
        # 1. Collection Status
        docs_count = docs_collection.count_documents({})
        debug_info += f"📚 Total documents in database: {docs_count}\n"
        
        # 2. Perform Search
        try:
            # Generate search terms for visibility
            search_terms = [
                query.lower(),
                *query.lower().split(),
                *(f"{a} {b}" for a, b in zip(query.lower().split(), query.lower().split()[1:]))
            ]
            debug_info += f"\n🔤 Search terms generated:\n{', '.join(search_terms)}\n"
            
            # Execute search
            results = search_similar_chunks(query)
            debug_info += f"\n🎯 Results found: {len(results)}\n"
            
            # Show results preview
            if results:
                debug_info += "\n📑 Result previews:\n"
                for i, result in enumerate(results[:2], 1):
                    preview = result[:200] + "..." if len(result) > 200 else result
                    debug_info += f"\nResult {i}:\n{preview}\n"
            else:
                debug_info += "\n❌ No results found\n"
                
                # Show a sample document for debugging
                sample = docs_collection.find_one()
                if sample:
                    debug_info += "\n📄 Sample document from database:\n"
                    if 'text' in sample:
                        preview = sample['text'][:200] + "..." if len(sample['text']) > 200 else sample['text']
                        debug_info += f"Text preview: {preview}\n"
                    debug_info += f"Available fields: {', '.join(sample.keys())}\n"
                    
        except Exception as e:
            debug_info += f"\n⚠️ Search error: {str(e)}\n"
        
        # Split response if too long
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

@bot.event
async def on_command_error(ctx, error):
    logger.error(f"Command error: {error}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run(DISCORD_TOKEN)