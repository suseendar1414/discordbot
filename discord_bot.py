import os
import logging
from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient
from langchain_openai import OpenAIEmbeddings
import discord
from discord import app_commands
from discord.ext import commands

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGODB_URI = os.getenv('MONGODB_URI')
GUILD_ID = 1307930198817116221

# Initialize OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# MongoDB setup
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client['quantified_ante']
collection = db['documents']

# Initialize embeddings
embeddings_model = OpenAIEmbeddings()

# Bot setup
class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
    async def setup_hook(self):
        self.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))

bot = QABot()

def search_similar_chunks(query, k=5):  # Increased k to get more context
    """Search for similar chunks with better context"""
    try:
        print(f"Searching for: {query}")
        
        # Create search terms from the query
        search_terms = [
            query.lower(),
            *query.lower().split(),
            *(f"{a} {b}" for a, b in zip(query.lower().split(), query.lower().split()[1:]))
        ]
        
        # Build OR query for multiple terms
        text_query = {
            "$or": [
                {"text": {"$regex": f"(?i).*{term}.*"}} 
                for term in search_terms
            ]
        }
        
        # Get results and surrounding context
        results = list(collection.find(text_query).limit(k))
        
        if not results:
            # Try vector search as backup
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
            results = list(collection.aggregate(pipeline))
        
        print(f"Found {len(results)} matches")
        return [doc['text'] for doc in results]
        
    except Exception as e:
        print(f"Search error: {e}")
        return []


@bot.event
async def on_ready():
    print(f'Bot is ready! Logged in as {bot.user}')
    print(f'Serving guild: {bot.get_guild(GUILD_ID).name}')

@bot.tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong! Bot is working!")

@bot.tree.command(name="test", description="Test database connection")
async def test(interaction: discord.Interaction):
    await interaction.response.send_message("Testing database connection...")
    try:
        count = collection.count_documents({})
        sample = collection.find_one()
        sample_text = sample['text'][:200] + "..." if sample else "No sample found"
        response = f"Found {count} documents in database\nSample text: {sample_text}"
        await interaction.followup.send(response)
    except Exception as e:
        await interaction.followup.send(f"Database error: {str(e)}")

@bot.tree.command(name="find", description="Search for specific content in the database")
@app_commands.describe(term="The term or concept to search for")
async def find(interaction: discord.Interaction, term: str):
    """Search for specific content in the database"""
    await interaction.response.defer()
    
    try:
        print(f"\nSearching for term: {term}")
        similar_chunks = search_similar_chunks(term)
        
        if not similar_chunks:
            await interaction.followup.send(f"No content found containing '{term}'")
            return
        
        # Create a preview of found content
        preview = "Found these relevant sections:\n\n"
        for i, chunk in enumerate(similar_chunks, 1):
            # Take first 200 characters of each chunk
            chunk_preview = chunk[:200].replace('\n', ' ') + "..."
            preview += f"{i}. {chunk_preview}\n\n"
        
        await interaction.followup.send(preview)
            
    except Exception as e:
        error_msg = f"Error during search: {str(e)}"
        print(error_msg)
        await interaction.followup.send(error_msg)

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading concepts")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    try:
        print(f"\nProcessing question: {question}")
        
        # Get relevant chunks
        similar_chunks = search_similar_chunks(question)
        
        if not similar_chunks:
            await interaction.followup.send("I couldn't find relevant information. Please try rephrasing your question.")
            return
        
        context = "\n".join(similar_chunks)
        
        # Enhanced prompt for better context utilization
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
            temperature=0.3  # Lower temperature for more focused answers
        )
        
        answer = response.choices[0].message.content
        
        # Split response if needed
        if len(answer) > 2000:
            parts = [answer[i:i+1990] for i in range(0, len(answer), 1990)]
            await interaction.followup.send(parts[0])
            for part in parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        print(error_msg)
        await interaction.followup.send(error_msg)

        
if __name__ == "__main__":
    print("Starting bot...")
    bot.run(DISCORD_TOKEN)