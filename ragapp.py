import os
import logging
from dotenv import load_dotenv
import openai
from pymongo import MongoClient
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
import discord
from discord import app_commands
from discord.ext import commands

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGODB_URI = os.getenv('MONGODB_URI')

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY

# MongoDB setup
client = MongoClient(MONGODB_URI)
db = client['quantified_ante']
collection = db['documents']

# Initialize embeddings
embeddings_model = OpenAIEmbeddings()

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# The content from your document
DOCUMENT_CONTENT = """SMC Predictive Strategy with Supporting Criteria
for
Quantified Ante Predictive Application
[... your entire document content here ...]"""

def process_text(text):
    """Split text into chunks"""
    logger.info("Processing text content")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = text_splitter.split_text(text)
    logger.info(f"Split text into {len(chunks)} chunks")
    return chunks

def store_embeddings(chunks):
    """Store text chunks and their embeddings in MongoDB"""
    # Clear existing documents
    collection.delete_many({})
    logger.info("Cleared existing documents from MongoDB")

    documents = []
    for i, chunk in enumerate(chunks):
        logger.info(f"Processing chunk {i+1}/{len(chunks)}")
        embedding = embeddings_model.embed_query(chunk)
        doc = {
            'text': chunk,
            'embedding': embedding
        }
        documents.append(doc)
    
    collection.insert_many(documents)
    logger.info(f"Stored {len(documents)} documents in MongoDB")

def search_similar_chunks(query, k=3):
    """Search for similar chunks using vector similarity"""
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
    return [doc['text'] for doc in results]

async def initialize_knowledge_base():
    """Initialize the knowledge base with document content"""
    logger.info("Initializing knowledge base...")
    try:
        # Process text and store in MongoDB
        chunks = process_text(DOCUMENT_CONTENT)
        store_embeddings(chunks)
        logger.info("Knowledge base initialized successfully!")
    except Exception as e:
        logger.error(f"Error initializing knowledge base: {e}")
        raise

@bot.event
async def on_ready():
    """Event triggered when bot is ready"""
    logger.info(f"Bot is ready! Logged in as {bot.user}")
    
    # Initialize knowledge base when bot starts
    await initialize_knowledge_base()
    
    # Sync commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Error syncing commands: {e}")
    
    logger.info(f"Bot is in {len(bot.guilds)} guilds")
    for guild in bot.guilds:
        logger.info(f"- {guild.name} (id: {guild.id})")

@bot.tree.command(name="ping", description="Check if the bot is responsive")
async def ping(interaction: discord.Interaction):
    """Simple ping command to test bot responsiveness"""
    await interaction.response.send_message("Pong! Bot is working!")

@bot.tree.command(name="ask", description="Ask a question about Quantified Ante trading")
async def ask(interaction: discord.Interaction, question: str):
    """Answer questions using RAG"""
    logger.info(f"Question received from {interaction.user}: {question}")
    
    try:
        await interaction.response.defer()
        
        # Get relevant chunks
        similar_chunks = search_similar_chunks(question)
        context = "\n".join(similar_chunks)
        
        # Generate response using OpenAI
        prompt = f"""You are a helpful assistant for Quantified Ante traders. Use the following context to answer the question.
        If you don't find the answer in the context, say so politely.
        
        Context: {context}
        
        Question: {question}
        
        Answer:"""
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a knowledgeable Quantified Ante trading assistant."},
                {"role": "user", "content": prompt}
            ]
        )
        
        answer = response.choices[0].message.content
        logger.info(f"Generated response for {interaction.user}")
        
        # Split response if it exceeds Discord's character limit
        if len(answer) > 2000:
            response_parts = [answer[i:i+1990] for i in range(0, len(answer), 1990)]
            await interaction.followup.send(response_parts[0])
            for part in response_parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(answer)
    except Exception as e:
        logger.error(f"Error generating response: {e}")
        await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)

# Run the bot
if __name__ == "__main__":
    logger.info("Starting bot...")
    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")