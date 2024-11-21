
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

# Initialize MongoDB with working configuration
mongo_client = MongoClient(
    MONGODB_URI,
    tls=True,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000
)
db = mongo_client['quantified_ante']
docs_collection = db['documents']
qa_collection = db['qa_history']

# Initialize OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize embeddings
embeddings_model = OpenAIEmbeddings()

# Bot setup
class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
    async def setup_hook(self):
        await self.tree.sync()
        logger.info("Commands synced globally!")

bot = QABot()

def search_similar_chunks(query, k=5):
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
        logger.info("Attempting text-based search...")
        results = list(docs_collection.find(text_query).limit(k))
        logger.info(f"Found {len(results)} text matches")
        
        # If no text results, try vector search
        if not results:
            logger.info("No text matches found, attempting vector search...")
            try:
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
                results = list(docs_collection.aggregate(pipeline))
                logger.info(f"Found {len(results)} vector matches")
            except Exception as ve:
                logger.error(f"Vector search failed: {ve}")
                results = []
        
        # Debug log the results
        if results:
            logger.info("Sample of found content:")
            for i, doc in enumerate(results[:2], 1):  # Log first 2 results
                preview = doc['text'][:100] + "..." if len(doc['text']) > 100 else doc['text']
                logger.info(f"Result {i}: {preview}")
        else:
            # If no results, log collection stats for debugging
            total_docs = docs_collection.count_documents({})
            logger.warning(f"No results found. Total documents in collection: {total_docs}")
            
            # Log a sample document structure
            sample = docs_collection.find_one()
            if sample:
                logger.info(f"Sample document fields: {list(sample.keys())}")
        
        return [doc['text'] for doc in results]
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}", exc_info=True)
        return []

@bot.tree.command(name="debug_search", description="Debug search functionality")
async def debug_search(interaction: discord.Interaction, query: str):
    """Command to debug search results"""
    try:
        await interaction.response.defer()
        
        # Get collection stats
        total_docs = docs_collection.count_documents({})
        
        # Try the search
        similar_chunks = search_similar_chunks(query)
        
        # Build debug response
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
            
            # Add sample document for debugging
            sample = docs_collection.find_one()
            if sample:
                debug_info += f"\n\nSample document structure:\nFields: {list(sample.keys())}"
        
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
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {bot.user}')
    logger.info(f'Connected to {len(bot.guilds)} servers:')
    for guild in bot.guilds:
        logger.info(f'- {guild.name} (id: {guild.id})')

@bot.tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    try:
        # Test MongoDB connection
        mongo_client.admin.command('ping')
        await interaction.response.send_message(
            f"✅ Bot and Database are working!\nServer: {interaction.guild.name}"
        )
    except Exception as e:
        await interaction.response.send_message(f"Error: {str(e)}")

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading concepts")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    try:
        logger.info(f"Question from {interaction.user.name} in {interaction.guild.name}: {question}")
        
        similar_chunks = search_similar_chunks(question)
        
        if not similar_chunks:
            # Store the failed question attempt
            qa_collection.insert_one({
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
        
        response = client.chat.completions.create(
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
        
        # Store successful Q&A
        qa_collection.insert_one({
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
        # Get stats for this server
        total = qa_collection.count_documents({'guild_id': str(interaction.guild.id)})
        successful = qa_collection.count_documents({
            'guild_id': str(interaction.guild.id),
            'success': True
        })
        
        # Get recent questions
        recent = list(qa_collection.find(
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

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run(DISCORD_TOKEN)
