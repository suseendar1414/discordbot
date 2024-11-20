
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
    """Search for similar chunks with better context"""
    try:
        logger.info(f"Searching for: {query}")
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
        
        results = list(docs_collection.find(text_query).limit(k))
        logger.info(f"Found {len(results)} text matches")
        
        if not results:
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
        
        return [doc['text'] for doc in results]
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return []

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
