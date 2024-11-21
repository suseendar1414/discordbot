import os
import logging
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from pymongo import MongoClient
import certifi
from openai import OpenAI
from langchain_openai import OpenAIEmbeddings
import json

# Enhanced logging setup
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

# Initialize clients with error handling
try:
    # MongoDB setup with extended timeout
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
    
    # Test MongoDB connection
    mongo_client.admin.command('ping')
    logger.info("MongoDB connection successful")
    
except Exception as e:
    logger.error(f"MongoDB connection error: {str(e)}", exc_info=True)
    raise

# OpenAI setup
client = OpenAI(api_key=OPENAI_API_KEY)
embeddings_model = OpenAIEmbeddings()

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
    async def setup_hook(self):
        await self.tree.sync()
        logger.info("Commands synced globally!")

bot = QABot()

async def debug_database():
    """Function to debug database connectivity and content"""
    try:
        # Test basic connectivity
        mongo_client.admin.command('ping')
        logger.info("MongoDB connection test successful")
        
        # Check collection contents
        doc_count = docs_collection.count_documents({})
        logger.info(f"Documents in collection: {doc_count}")
        
        # Check indexes
        indexes = list(docs_collection.list_indexes())
        logger.info(f"Collection indexes: {[idx['name'] for idx in indexes]}")
        
        # Sample documents
        sample_docs = list(docs_collection.find().limit(2))
        for i, doc in enumerate(sample_docs):
            logger.info(f"Sample document {i+1} fields: {list(doc.keys())}")
            logger.info(f"Sample text preview: {doc.get('text', 'NO TEXT FIELD')[:100]}")
        
        return True
    except Exception as e:
        logger.error(f"Database debug failed: {str(e)}", exc_info=True)
        return False

def search_similar_chunks(query, k=5):
    """Enhanced search function with detailed logging"""
    try:
        logger.info(f"Starting search for query: '{query}'")
        
        # Log current database state
        doc_count = docs_collection.count_documents({})
        logger.info(f"Total documents in collection: {doc_count}")
        
        # Prepare search terms
        search_terms = [
            query.lower(),
            *[term.strip() for term in query.lower().split() if term.strip()],
            *[f"{a} {b}" for a, b in zip(query.lower().split(), query.lower().split()[1:])]
        ]
        logger.info(f"Search terms: {search_terms}")
        
        results = []
        
        # 1. Try basic text search
        text_query = {
            "$or": [
                {"text": {"$regex": f"(?i){term}", "$options": "i"}} 
                for term in search_terms
            ]
        }
        
        text_results = list(docs_collection.find(text_query).limit(k))
        logger.info(f"Text search found {len(text_results)} results")
        results.extend(text_results)
        
        # 2. Try vector search if needed
        if len(results) < k:
            try:
                query_embedding = embeddings_model.embed_query(query)
                
                # Check for vector index
                indexes = list(docs_collection.list_indexes())
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
                    vector_results = list(docs_collection.aggregate(pipeline))
                    logger.info(f"Vector search found {len(vector_results)} results")
                    results.extend(vector_results)
                else:
                    logger.warning("No vector index found")
            except Exception as ve:
                logger.error(f"Vector search error: {str(ve)}", exc_info=True)
        
        # Log search results
        if results:
            logger.info("Search results preview:")
            for i, doc in enumerate(results[:2]):
                preview = doc.get('text', '')[:100]
                logger.info(f"Result {i+1}: {preview}...")
        else:
            logger.warning("No results found in any search method")
        
        return [doc.get('text', '') for doc in results if doc.get('text')]
        
    except Exception as e:
        logger.error(f"Search error: {str(e)}", exc_info=True)
        return []

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    try:
        await interaction.response.defer()
        logger.info(f"Processing question from {interaction.user.name}: {question}")
        
        # Debug database state
        db_status = await debug_database()
        if not db_status:
            await interaction.followup.send("⚠️ Database connection issues detected. Please try again later.")
            return
        
        # Search for relevant content
        similar_chunks = search_similar_chunks(question)
        
        if not similar_chunks:
            logger.warning(f"No results found for question: {question}")
            await interaction.followup.send(
                "I couldn't find any relevant information. Please try rephrasing your question or check if the information exists in the database."
            )
            return
        
        # Generate response
        context = "\n".join(similar_chunks)
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a Quantified Ante trading assistant. Use only information from the provided context."},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}
                ],
                temperature=0.3
            )
            
            answer = response.choices[0].message.content
            
            # Store Q&A in history
            qa_collection.insert_one({
                'timestamp': datetime.utcnow(),
                'guild_id': str(interaction.guild.id),
                'guild_name': interaction.guild.name,
                'user_id': str(interaction.user.id),
                'username': interaction.user.name,
                'question': question,
                'answer': answer,
                'context_used': similar_chunks,
                'success': True
            })
            
            # Send response
            if len(answer) > 1990:
                parts = [answer[i:i+1990] for i in range(0, len(answer), 1990)]
                await interaction.followup.send(parts[0])
                for part in parts[1:]:
                    await interaction.followup.send(part)
            else:
                await interaction.followup.send(answer)
                
        except Exception as e:
            logger.error(f"OpenAI API error: {str(e)}", exc_info=True)
            await interaction.followup.send("Error generating response. Please try again later.")
            
    except Exception as e:
        logger.error(f"Ask command error: {str(e)}", exc_info=True)
        await interaction.followup.send("An error occurred while processing your question.")

@bot.event
async def on_ready():
    logger.info(f"Bot is ready! Logged in as {bot.user}")
    # Initial database check
    db_status = await debug_database()
    if not db_status:
        logger.error("Initial database check failed!")
    else:
        logger.info("Initial database check successful!")

if __name__ == "__main__":
    logger.info("Starting services...")
    bot.run(DISCORD_TOKEN)