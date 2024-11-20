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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGODB_URI = os.getenv('MONGODB_URI')

# Initialize OpenAI
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize MongoDB
mongo_client = MongoClient(
    MONGODB_URI,
    tls=True,
    tlsCAFile=certifi.where()
)
db = mongo_client['quantified_ante']
docs_collection = db['documents']
qa_collection = db['qa_history']

# Bot setup
class QABot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        
    async def setup_hook(self):
        logger.info("Syncing commands...")
        await self.tree.sync()
        logger.info("Commands synced!")

client = QABot()

def search_content(query):
    """Search for relevant content in MongoDB"""
    try:
        # Simple text search
        results = list(docs_collection.find(
            {"text": {"$regex": query, "$options": "i"}},
            {"text": 1, "_id": 0}
        ).limit(3))
        
        return [doc["text"] for doc in results]
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

def store_interaction(user_id, username, question, answer, success):
    """Store Q&A interaction in MongoDB"""
    try:
        qa_collection.insert_one({
            "timestamp": datetime.utcnow(),
            "user_id": str(user_id),
            "username": username,
            "question": question,
            "answer": answer,
            "success": success
        })
    except Exception as e:
        logger.error(f"Failed to store interaction: {e}")

@client.event
async def on_ready():
    logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
    logger.info(f'Connected to {len(client.guilds)} guilds:')
    for guild in client.guilds:
        logger.info(f'- {guild.name} (ID: {guild.id})')

@client.tree.command(name="hello", description="Says hello")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f'Hi, {interaction.user.name}!')

@client.tree.command(name="ping", description="Check if bot is working")
async def ping(interaction: discord.Interaction):
    # Test database connection
    try:
        mongo_client.admin.command('ping')
        db_status = "✅"
    except:
        db_status = "❌"
        
    await interaction.response.send_message(
        f'Pong! ({round(client.latency * 1000)}ms)\nDatabase: {db_status}'
    )

@client.tree.command(name="ask", description="Ask about Quantified Ante trading")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    try:
        # Search for relevant content
        content = search_content(question)
        
        if not content:
            response = "I couldn't find relevant information. Please try rephrasing your question."
            store_interaction(
                interaction.user.id,
                interaction.user.name,
                question,
                response,
                False
            )
            await interaction.followup.send(response)
            return
        
        # Format context and generate response
        context = "\n".join(content)
        chat_response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You are a knowledgeable Quantified Ante trading assistant. Answer questions based only on the provided context."
                },
                {
                    "role": "user",
                    "content": f"Context: {context}\n\nQuestion: {question}\n\nAnswer:"
                }
            ]
        )
        
        answer = chat_response.choices[0].message.content
        
        # Store successful interaction
        store_interaction(
            interaction.user.id,
            interaction.user.name,
            question,
            answer,
            True
        )
        
        # Split long responses
        if len(answer) > 1900:
            parts = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
            await interaction.followup.send(parts[0])
            for part in parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        logger.error(f"Error processing question: {e}")
        await interaction.followup.send(
            "An error occurred while processing your question. Please try again later."
        )

@client.tree.command(name="stats", description="Show usage statistics")
async def stats(interaction: discord.Interaction):
    try:
        total_questions = qa_collection.count_documents({})
        successful = qa_collection.count_documents({"success": True})
        recent = list(qa_collection.find(
            {},
            {"question": 1, "success": 1, "username": 1, "timestamp": 1}
        ).sort("timestamp", -1).limit(5))
        
        stats_msg = f"""📊 Bot Statistics
Total Questions: {total_questions}
Successful Answers: {successful}
Success Rate: {(successful/total_questions*100 if total_questions > 0 else 0):.1f}%

Recent Questions:"""
        
        for qa in recent:
            status = "✅" if qa.get("success") else "❌"
            timestamp = qa.get("timestamp").strftime("%Y-%m-%d %H:%M")
            stats_msg += f"\n{status} [{timestamp}] {qa.get('username')}: {qa.get('question')}"
        
        await interaction.response.send_message(stats_msg)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        await interaction.response.send_message("Error retrieving statistics.")

if __name__ == "__main__":
    logger.info("Starting bot...")
    client.run(DISCORD_TOKEN)
