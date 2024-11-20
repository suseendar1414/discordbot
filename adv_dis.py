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
openai_client = OpenAI(api_key=OPENAI_API_KEY)
mongo_client = MongoClient(MONGODB_URI, tls=True, tlsCAFile=certifi.where())
db = mongo_client['quantified_ante']
docs_collection = db['documents']
qa_collection = db['qa_history']

# Bot setup
class QABot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.activity = discord.Game(name="/help for commands")

    async def setup_hook(self):
        """This is called when the bot starts."""
        logger.info("Syncing commands...")
        # Sync commands to your test server first
        MY_GUILD = discord.Object(id=1307930198817116221)  # Your server ID
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        logger.info("Commands synced to guild!")

client = QABot()

@client.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {client.user}')
    for guild in client.guilds:
        logger.info(f'Connected to guild: {guild.name} (ID: {guild.id})')

@client.tree.command(
    name="help",
    description="Show available commands"
)
async def help(interaction: discord.Interaction):
    help_text = """
Available Commands:
• /help - Show this help message
• /ask [question] - Ask about Quantified Ante trading
• /ping - Check if bot is working

Example:
/ask What is MMBM?
"""
    await interaction.response.send_message(help_text)

@client.tree.command(
    name="ping",
    description="Check if bot is working"
)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! Bot is working.")

@client.tree.command(
    name="ask",
    description="Ask about Quantified Ante trading"
)
@app_commands.describe(
    question="Your question about trading"
)
async def ask(interaction: discord.Interaction, question: str):
    logger.info(f"Question received from {interaction.user}: {question}")
    
    # Defer the response since it might take some time
    await interaction.response.defer()
    
    try:
        # Search in MongoDB
        results = list(docs_collection.find(
            {"text": {"$regex": question, "$options": "i"}},
            {"text": 1, "_id": 0}
        ).limit(3))
        
        if not results:
            await interaction.followup.send(
                "I couldn't find information about that. Try asking something about MMBM, Order Blocks, or Market Structure."
            )
            return
            
        # Combine found texts
        context = "\n".join([doc["text"] for doc in results])
        
        # Get response from OpenAI
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a Quantified Ante trading assistant. Answer questions based only on the provided context."
                },
                {
                    "role": "user", 
                    "content": f"Context: {context}\n\nQuestion: {question}\n\nProvide a clear, concise answer based only on the context provided."
                }
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        answer = response.choices[0].message.content
        
        # Store the Q&A
        qa_collection.insert_one({
            "timestamp": datetime.utcnow(),
            "user_id": str(interaction.user.id),
            "username": interaction.user.name,
            "question": question,
            "answer": answer,
            "success": True
        })
        
        # Send response in chunks if needed
        if len(answer) > 1900:
            parts = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
            await interaction.followup.send(parts[0])
            for part in parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        logger.error(f"Error processing question: {str(e)}")
        await interaction.followup.send(
            "An error occurred. Please try asking your question differently or try again later."
        )

@client.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, 
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"Please wait {error.retry_after:.2f} seconds before using this command again.",
            ephemeral=True
        )
    else:
        logger.error(f"Command error: {str(error)}")
        await interaction.response.send_message(
            "An error occurred. Please try again.",
            ephemeral=True
        )

if __name__ == "__main__":
    logger.info("Starting bot...")
    client.run(DISCORD_TOKEN)