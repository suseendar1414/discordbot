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

class DatabaseManager:
    def __init__(self, uri: str):
        # Remove srv from URI if present
        uri = uri.replace('mongodb+srv://', 'mongodb://')
        
        self.client = MongoClient(
            uri,
            tls=True,
            tlsInsecure=True,  # For testing only
            directConnection=True,
            retryWrites=True,
            w='majority'
        )
        try:
            self.client.admin.command('ping')
            logger.info("MongoDB connection successful")
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            raise
            
        self.db = self.client['quantified_ante']
        self.docs_collection = self.db['documents']
        self.qa_collection = self.db['qa_history']

    def search_documents(self, query: str, k: int = 5):
        search_terms = [
            query.lower(),
            *query.lower().split(),
            *(f"{a} {b}" for a, b in zip(query.lower().split(), query.lower().split()[1:]))
        ]
        
        text_query = {
            "$or": [
                {"text": {"$regex": f"(?i).*{term}.*"}} 
                for term in search_terms
            ]
        }
        
        results = list(self.docs_collection.find(text_query).limit(k))
        logger.info(f"Found {len(results)} text matches")
        return results

    def store_qa(self, interaction: discord.Interaction, question: str, answer: str, success: bool):
        self.qa_collection.insert_one({
            'timestamp': datetime.utcnow(),
            'guild_id': str(interaction.guild.id),
            'guild_name': interaction.guild.name,
            'user_id': str(interaction.user.id),
            'username': interaction.user.name,
            'question': question,
            'answer': answer,
            'success': success
        })

    def get_stats(self, guild_id: str):
        total = self.qa_collection.count_documents({'guild_id': str(guild_id)})
        successful = self.qa_collection.count_documents({
            'guild_id': str(guild_id),
            'success': True
        })
        recent = list(self.qa_collection.find(
            {'guild_id': str(guild_id)}
        ).sort('timestamp', -1).limit(5))
        
        return {
            'total': total,
            'successful': successful,
            'success_rate': (successful/total*100 if total > 0 else 0),
            'recent': recent
        }

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        # Initialize services
        self.db = DatabaseManager(MONGODB_URI)
        self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
        self.embeddings_model = OpenAIEmbeddings()
        
    async def setup_hook(self):
        await self.tree.sync()
        logger.info("Commands synced globally!")

    async def process_question(self, question: str):
        similar_chunks = self.db.search_documents(question)
        
        if not similar_chunks:
            return None
            
        context = "\n".join(doc['text'] for doc in similar_chunks)
        
        prompt = f"""You are a knowledgeable Quantified Ante trading assistant. 
        Answer the question based on the following context.

        Context: {context}
        Question: {question}

        Please provide a detailed answer using only information found in the context above."""
        
        response = self.openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You are a knowledgeable Quantified Ante trading assistant."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3
        )
        
        return response.choices[0].message.content

bot = QABot()

@bot.event
async def on_ready():
    logger.info(f'Bot is ready! Logged in as {bot.user}')
    logger.info(f'Connected to {len(bot.guilds)} servers:')
    for guild in bot.guilds:
        logger.info(f'- {guild.name} (id: {guild.id})')

@bot.tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        bot.db.client.admin.command('ping')
        await interaction.followup.send(
            f"✅ Bot and Database are working!\nServer: {interaction.guild.name}"
        )
    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"Error: {str(e)}")
        else:
            await interaction.followup.send(f"Error: {str(e)}")

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading concepts")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    try:
        logger.info(f"Question from {interaction.user.name} in {interaction.guild.name}: {question}")
        
        answer = await bot.process_question(question)
        
        if not answer:
            bot.db.store_qa(interaction, question, "No relevant information found", False)
            await interaction.followup.send("I couldn't find relevant information. Please try rephrasing your question.")
            return
        
        bot.db.store_qa(interaction, question, answer, True)
        
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
        await interaction.response.defer()
        stats = bot.db.get_stats(str(interaction.guild.id))
        
        stats_msg = f"""📊 Stats for {interaction.guild.name}:
Total Questions: {stats['total']}
Successful Answers: {stats['successful']}
Success Rate: {stats['success_rate']:.1f}%

Recent Questions:"""
        
        for qa in stats['recent']:
            status = "✅" if qa["success"] else "❌"
            timestamp = qa["timestamp"].strftime("%Y-%m-%d %H:%M")
            stats_msg += f"\n{status} [{timestamp}] {qa['username']}: {qa['question']}"
        
        await interaction.followup.send(stats_msg)
    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"Error: {str(e)}")
        else:
            await interaction.followup.send(f"Error: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")