import os
import discord
from discord import app_commands
import logging
from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient
import certifi
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGODB_URI = os.getenv('MONGODB_URI')
GUILD_ID = 1307930198817116221

# Initialize OpenAI
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize MongoDB
try:
    mongo_client = MongoClient(
        MONGODB_URI,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=5000
    )
    db = mongo_client['quantified_ante']
    docs_collection = db['documents']
    qa_collection = db['qa_history']
except Exception as e:
    logger.error(f"MongoDB initialization error: {e}")

class QABot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        MY_GUILD = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        logger.info("Commands synced!")

client = QABot()

@client.event
async def on_ready():
    logger.info(f"Bot is ready! Logged in as {client.user}")

@client.tree.command(name="hello")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello, {interaction.user.name}!")

@client.tree.command(name="ping")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

@client.tree.command(name="echo")
@app_commands.describe(text="The text to repeat")
async def echo(interaction: discord.Interaction, text: str):
    await interaction.response.send_message(f"You said: {text}")

@client.tree.command(name="dbtest")
async def dbtest(interaction: discord.Interaction):
    """Test database connection"""
    await interaction.response.defer()
    
    try:
        # Test MongoDB connection
        mongo_client.admin.command('ping')
        doc_count = docs_collection.count_documents({})
        sample = docs_collection.find_one()
        
        response = f"""Database Status:
Connected: ✅
Documents: {doc_count}
Sample: {sample['text'][:200] if sample else 'No documents'} ..."""
        
        await interaction.followup.send(response)
    except Exception as e:
        await interaction.followup.send(f"Database error: {str(e)}")

@client.tree.command(name="ask")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    """Answer questions about trading"""
    logger.info(f"Question received: {question}")
    await interaction.response.defer()
    
    try:
        # Search in MongoDB
        results = list(docs_collection.find(
            {"text": {"$regex": question, "$options": "i"}},
            {"text": 1, "_id": 0}
        ).limit(3))
        
        if not results:
            await interaction.followup.send(
                "I couldn't find information about that. Try asking about MMBM, Order Blocks, or Market Structure."
            )
            return
        
        # Prepare context
        context = "\n".join(doc["text"] for doc in results)
        
        # Get OpenAI response
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
            ]
        )
        
        answer = response.choices[0].message.content
        
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
        logger.error(f"Error in ask command: {e}")
        await interaction.followup.send(
            "An error occurred while processing your question. Please try again."
        )

@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"Command error: {str(error)}")
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "An error occurred while processing the command.",
            ephemeral=True
        )

if __name__ == "__main__":
    logger.info("Starting bot...")
    client.run(DISCORD_TOKEN)
