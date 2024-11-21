
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
import re

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

# MongoDB setup
try:
    mongo_client = MongoClient(
        MONGODB_URI,
        tls=True,
        tlsCAFile=certifi.where()
    )
    db = mongo_client['quantified_ante']
    docs_collection = db['documents']
    qa_collection = db['qa_history']
    logger.info("MongoDB connection established successfully")
except Exception as e:
    logger.error(f"MongoDB connection failed: {str(e)}")
    raise

# Initialize OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)
embeddings_model = OpenAIEmbeddings()

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
    async def setup_hook(self):
        try:
            await self.tree.sync()
            logger.info("✅ Commands synced globally!")
        except Exception as e:
            logger.error(f"❌ Command sync failed: {str(e)}")
            raise

    async def on_ready(self):
        logger.info(f'Bot is ready! Logged in as {self.user}')
        logger.info(f'Connected to {len(self.guilds)} servers:')
        for guild in self.guilds:
            logger.info(f'- {guild.name} (id: {guild.id})')

bot = QABot()

def search_similar_chunks(query, k=5):
    """Search function optimized for trading terminology and concepts.
    
    Args:
        query (str): Search query from user
        k (int): Number of chunks to return
    """
    try:
        print(f"Searching for: {query}")
        
        # Clean query
        query_clean = query.lower().strip()
        words = query_clean.split()
        
        # Remove common question words
        stop_words = {'what', 'is', 'are', 'how', 'does', 'where', 'when', 'why', 'which'}
        core_terms = [w for w in words if w not in stop_words]
        core_query = ' '.join(core_terms)
        
        # Create trading-specific search patterns
        search_terms = set([
            core_query,
            query_clean,
            *core_terms,
            *(term.upper() for term in core_terms),  # For acronyms
            *(f"{a} {b}" for a, b in zip(core_terms, core_terms[1:])),  # Pairs
        ])
        
        # Build query with trading-specific patterns
        text_query = {
            "$or": []
        }
        
        for term in search_terms:
            if term:
                text_query["$or"].extend([
                    # Definition matches
                    {"text": {"$regex": f"(?i)Definition:.*{re.escape(term)}", "$options": "i"}},
                    {"text": {"$regex": f"(?i){re.escape(term)}.*definition", "$options": "i"}},
                    
                    # Trading concept patterns
                    {"text": {"$regex": f"(?i){re.escape(term)}[\\s]*:[^\\n]*", "$options": "i"}},
                    {"text": {"$regex": f"(?i)• {re.escape(term)}:", "$options": "i"}},
                    
                    # FAQ patterns
                    {"text": {"$regex": f"(?i)FAQ.*{re.escape(term)}", "$options": "i"}},
                    {"text": {"$regex": f"(?i)Question:.*{re.escape(term)}", "$options": "i"}},
                    
                    # General term match
                    {"text": {"$regex": f"(?i)\\b{re.escape(term)}\\b", "$options": "i"}},
                ])
        
        def extract_trading_context(text, term):
            """Extract trading-relevant context around a term."""
            # Split into paragraphs
            paragraphs = text.split('\n\n')
            relevant_sections = []
            
            for i, para in enumerate(paragraphs):
                if re.search(f"(?i)\\b{re.escape(term)}\\b", para):
                    # Get surrounding context
                    start_idx = max(0, i - 1)
                    end_idx = min(len(paragraphs), i + 2)
                    
                    # Join paragraphs with context
                    context = '\n\n'.join(paragraphs[start_idx:end_idx])
                    
                    # Clean up the text
                    context = re.sub(r'\s+', ' ', context)
                    context = context.strip()
                    
                    if len(context) > 50:  # Minimum length check
                        relevant_sections.append(context)
            
            return relevant_sections
        
        # Execute search
        results = list(docs_collection.find(text_query).limit(k))
        print(f"Text search found {len(results)} matches")
        
        # Process results with trading context
        processed_results = []
        for doc in results:
            if 'text' in doc:
                # Extract context for each search term
                for term in search_terms:
                    if term:
                        sections = extract_trading_context(doc['text'], term)
                        processed_results.extend(sections)
        
        # Remove duplicates while preserving order
        processed_results = list(dict.fromkeys(processed_results))
        
        # Try vector search if needed
        if len(processed_results) < 2:
            try:
                query_embedding = embeddings_model.embed_query(core_query)
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
                print(f"Vector search found {len(vector_results)} results")
                
                # Process vector results
                for doc in vector_results:
                    if 'text' in doc:
                        for term in search_terms:
                            if term:
                                sections = extract_trading_context(doc['text'], term)
                                processed_results.extend(sections)
            except Exception as ve:
                print(f"Vector search failed: {ve}")
        
        # Remove duplicates again after vector search
        processed_results = list(dict.fromkeys(processed_results))[:k]
        
        # Log results
        if processed_results:
            print(f"Found {len(processed_results)} relevant chunks")
            for i, chunk in enumerate(processed_results[:2]):
                preview = chunk[:200] + "..." if len(chunk) > 200 else chunk
                print(f"Preview {i+1}: {preview}")
        else:
            print("No results found")
        
        return processed_results
        
    except Exception as e:
        print(f"Search error: {str(e)}")
        return []

@bot.tree.command(name="ping", description="Test if the bot and database are working")
async def ping(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        # Test MongoDB connection
        mongo_client.admin.command('ping')
        docs_count = docs_collection.count_documents({})
        
        await interaction.followup.send(
            f"✅ Bot and database are working!\n"
            f"Connected to: {interaction.guild.name}\n"
            f"Documents in database: {docs_count}"
        )
    except Exception as e:
        await interaction.followup.send(f"Error: {str(e)}")

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading concepts")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    try:
        await interaction.response.defer()
        
        logger.info(f"Question from {interaction.user.name} in {interaction.guild.name}: {question}")
        
        # Search for relevant content
        similar_chunks = search_similar_chunks(question)
        
        if not similar_chunks:
            # Log failed question
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
            
            await interaction.followup.send(
                "I couldn't find relevant information. Please try rephrasing your question."
            )
            return
        
        # Combine chunks and generate response
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
        
        # Log successful QA
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
        
        # Split long responses
        if len(answer) > 2000:
            parts = [answer[i:i+1990] for i in range(0, len(answer), 1990)]
            await interaction.followup.send(parts[0])
            for part in parts[1:]:
                await interaction.followup.send(part)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        logger.error(f"Ask command error: {str(e)}")
        await interaction.followup.send(f"Error: {str(e)}")

@bot.tree.command(name="stats", description="Get Q&A statistics for this server")
async def stats(interaction: discord.Interaction):
    try:
        total = qa_collection.count_documents({'guild_id': str(interaction.guild.id)})
        successful = qa_collection.count_documents({
            'guild_id': str(interaction.guild.id),
            'success': True
        })
        
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



@bot.tree.command(name="debug", description="Debug database content")
@app_commands.default_permissions(administrator=True)
async def debug(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        
        # Get collection stats
        docs_count = docs_collection.count_documents({})
        qa_count = qa_collection.count_documents({})
        
        # Sample documents
        sample_doc = docs_collection.find_one()
        
        debug_info = f"""📊 Database Debug Info:
Documents Collection: {docs_count} documents
QA History: {qa_count} entries

Sample Document Fields: {list(sample_doc.keys()) if sample_doc else 'No documents found'}
"""
        
        await interaction.followup.send(debug_info)
    except Exception as e:
        await interaction.followup.send(f"Debug error: {str(e)}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run(DISCORD_TOKEN)
