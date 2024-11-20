import os
import logging
from dotenv import load_dotenv
import discord
from discord import app_commands
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

# Initialize clients
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    mongo_client = MongoClient(MONGODB_URI, tls=True, tlsCAFile=certifi.where())
    db = mongo_client['quantified_ante']
    docs_collection = db['documents']
    qa_collection = db['qa_history']
except Exception as e:
    logger.error(f"Initialization error: {e}")

# Bot setup
class QABot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

client = QABot()

@client.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {client.user}')
    
@client.tree.command(name="hello")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello {interaction.user.name}!")

@client.tree.command(name="ping")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

@client.tree.command(name="ask")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    # First, acknowledge the interaction
    await interaction.response.defer()
    
    try:
        # Search in MongoDB
        results = list(docs_collection.find(
            {"text": {"$regex": question, "$options": "i"}},
            {"text": 1, "_id": 0}
        ).limit(3))
        
        if not results:
            await interaction.followup.send("I couldn't find an answer to that question.")
            return
            
        context = "\n".join([doc["text"] for doc in results])
        
        # Get response from OpenAI
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a Quantified Ante trading assistant."},
                {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"}
            ]
        )
        
        answer = response.choices[0].message.content
        
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
        await interaction.followup.send("An error occurred while processing your question.")

@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"Command error: {str(error)}")
    if not interaction.response.is_done():
        await interaction.response.send_message("An error occurred.", ephemeral=True)

if __name__ == "__main__":
    client.run(DISCORD_TOKEN)

