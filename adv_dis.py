import os
import logging
from dotenv import load_dotenv
import discord
from discord import app_commands
from openai import OpenAI
from pymongo import MongoClient
import certifi
from datetime import datetime

# Enhanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGODB_URI = os.getenv('MONGODB_URI')

# Initialize clients with error checking
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    mongo_client = MongoClient(MONGODB_URI, tls=True, tlsCAFile=certifi.where())
    db = mongo_client['quantified_ante']
    docs_collection = db['documents']
    qa_collection = db['qa_history']
    
    # Test MongoDB connection
    mongo_client.admin.command('ping')
    logger.info("MongoDB connected successfully!")
    
    # Check if documents exist
    doc_count = docs_collection.count_documents({})
    logger.info(f"Found {doc_count} documents in collection")
    
except Exception as e:
    logger.error(f"Initialization error: {e}")
    raise

class QABot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        MY_GUILD = discord.Object(id=1307930198817116221)
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        logger.info("Commands synced!")

client = QABot()

@client.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {client.user}')
    for guild in client.guilds:
        logger.info(f'Connected to guild: {guild.name} (ID: {guild.id})')

def search_documents(query: str):
    """Search documents with error logging"""
    try:
        logger.info(f"Searching for: {query}")
        results = list(docs_collection.find(
            {"text": {"$regex": f"(?i){query}"}},
            {"text": 1, "_id": 0}
        ).limit(3))
        logger.info(f"Found {len(results)} matching documents")
        return results
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

@client.tree.command(name="ping", description="Check if bot is working")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! Bot is working.")

@client.tree.command(name="test", description="Test database connection")
async def test(interaction: discord.Interaction):
    try:
        # Test MongoDB
        mongo_client.admin.command('ping')
        doc_count = docs_collection.count_documents({})
        sample = docs_collection.find_one()
        
        response = f"""Database Status:
Connected: ✅
Documents: {doc_count}
Sample: {sample['text'][:100] if sample else 'No documents'}"""
        
        await interaction.response.send_message(response)
    except Exception as e:
        await interaction.response.send_message(f"Database error: {str(e)}")

@client.tree.command(name="ask", description="Ask about Quantified Ante trading")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    logger.info(f"Question received from {interaction.user.name}: {question}")
    await interaction.response.defer()
    
    try:
        # Search for relevant documents
        results = search_documents(question)
        
        if not results:
            logger.info("No relevant documents found")
            await interaction.followup.send(
                "I couldn't find information about that topic. Try asking about MMBM, Order Blocks, or Market Structure."
            )
            return
        
        # Prepare context
        context = "\n".join(doc["text"] for doc in results)
        logger.info(f"Context length: {len(context)} characters")
        
        # Get OpenAI response
        logger.info("Requesting OpenAI response")
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You are a Quantified Ante trading assistant. Answer questions based only on the provided context."
                },
                {
                    "role": "user",
                    "content": f"Context: {context}\n\nQuestion: {question}\n\nAnswer:"
                }
            ],
            max_tokens=500
        )
        
        answer = response.choices[0].message.content
        logger.info(f"Generated response length: {len(answer)} characters")
        
        # Store Q&A
        qa_collection.insert_one({
            "timestamp": datetime.utcnow(),
            "user_id": str(interaction.user.id),
            "username": interaction.user.name,
            "question": question,
            "answer": answer,
            "success": True
        })
        
        # Send response
        if len(answer) > 1900:
            parts = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
            await interaction.followup.send(parts[0])
            for part in parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        logger.error(f"Error in ask command: {str(e)}")
        await interaction.followup.send(
            "An error occurred processing your question. Please try again or use different terms."
        )

if __name__ == "__main__":
    logger.info("Starting bot...")
    client.run(DISCORD_TOKEN)