import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
import certifi
from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient, ASCENDING
from pymongo.errors import OperationFailure
from langchain_openai import OpenAIEmbeddings
import discord
from discord import app_commands
from discord.ext import commands

# Setup logging with more detailed format
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

class DocumentSearch:
    def __init__(self, mongo_uri: str, db_name: str = 'quantified_ante', 
                 collection_name: str = 'documents'):
        self.logger = logging.getLogger('document_search')
        self.mongo_client = MongoClient(mongo_uri, tls=True, tlsCAFile=certifi.where())
        self.db = self.mongo_client[db_name]
        self.collection = self.db[collection_name]
        self.embeddings_model = OpenAIEmbeddings()
        
        # Ensure indexes exist
        self._setup_indexes()
    
    def _setup_indexes(self):
        """Setup necessary indexes for efficient searching"""
        try:
            # Text index for text-based searches
            self.collection.create_index([("text", "text")], 
                                      name="text_search_index")
            
            # Regular index on text field for regex queries
            self.collection.create_index([("text", ASCENDING)], 
                                       name="text_regex_index")
            
            self.logger.info("Indexes created successfully")
        except OperationFailure as e:
            self.logger.error(f"Failed to create indexes: {e}")
    
    def _clean_query(self, query: str) -> str:
        """Clean and normalize the query string"""
        return " ".join(query.lower().split())
    
    def _get_search_terms(self, query: str) -> List[str]:
        """Generate search terms from the query"""
        words = query.lower().split()
        terms = [
            query.lower(),  # Full query
            *[term.strip() for term in words if term.strip()],  # Individual words
            *[f"{a} {b}" for a, b in zip(words, words[1:])],  # Word pairs
        ]
        return [term for term in terms if term]  # Remove empty terms
    
    async def verify_connection(self) -> bool:
        """Verify database connection and setup"""
        try:
            # Test connection
            self.mongo_client.admin.command('ping')
            
            # Verify collection exists and has documents
            doc_count = self.collection.count_documents({})
            if doc_count == 0:
                self.logger.error("Collection is empty")
                return False
            
            # Verify document structure
            sample = self.collection.find_one()
            if not sample or 'text' not in sample:
                self.logger.error("Invalid document structure")
                return False
            
            self.logger.info(f"Connection verified. {doc_count} documents found")
            return True
            
        except Exception as e:
            self.logger.error(f"Connection verification failed: {e}")
            return False
    
    def search(self, query: str, k: int = 5) -> List[str]:
        """
        Multi-strategy search implementation
        Returns list of relevant text chunks
        """
        try:
            clean_query = self._clean_query(query)
            search_terms = self._get_search_terms(clean_query)
            results = []
            
            # 1. Try exact phrase match first
            if not results:
                results = list(self.collection.find(
                    {"$text": {"$search": f"\"{clean_query}\""}},
                    {"score": {"$meta": "textScore"}, "text": 1}
                ).sort([("score", {"$meta": "textScore"})]).limit(k))
            
            # 2. Try text search with individual terms
            if not results:
                results = list(self.collection.find(
                    {"$text": {"$search": " ".join(search_terms)}},
                    {"score": {"$meta": "textScore"}, "text": 1}
                ).sort([("score", {"$meta": "textScore"})]).limit(k))
            
            # 3. Try vector search if available
            if not results:
                try:
                    query_embedding = self.embeddings_model.embed_query(clean_query)
                    pipeline = [
                        {
                            "$search": {
                                "index": "vector_index",
                                "knnBeta": {
                                    "vector": query_embedding,
                                    "path": "embedding",
                                    "k": k
                                }
                            }
                        },
                        {"$project": {"text": 1, "_id": 0}}
                    ]
                    results = list(self.collection.aggregate(pipeline))
                except Exception as ve:
                    self.logger.warning(f"Vector search failed: {ve}")
            
            # 4. Fallback to regex search
            if not results:
                regex_patterns = [
                    {"text": {"$regex": f"(?i){term}", "$options": "i"}}
                    for term in search_terms
                ]
                results = list(self.collection.find(
                    {"$or": regex_patterns},
                    {"text": 1, "_id": 0}
                ).limit(k))
            
            # Extract and return text from results
            texts = [doc.get('text', '') for doc in results if doc.get('text')]
            
            # Log search results
            self.logger.info(
                f"Query: '{query}' found {len(texts)} results using "
                f"{'vector' if 'vector_index' in str(results) else 'text'} search"
            )
            
            return texts
            
        except Exception as e:
            self.logger.error(f"Search failed: {e}", exc_info=True)
            return []

class QABot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        # Initialize OpenAI client
        self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Initialize document search
        self.document_search = DocumentSearch(MONGODB_URI)
        
        # Initialize MongoDB for QA history
        self.mongo_client = MongoClient(MONGODB_URI, tls=True, tlsCAFile=certifi.where())
        self.db = self.mongo_client['quantified_ante']
        self.qa_collection = self.db['qa_history']
        
    async def setup_hook(self):
        """Initial setup after bot is ready"""
        try:
            # Verify database connection
            if not await self.document_search.verify_connection():
                logger.error("❌ Database verification failed!")
                return
            
            # Sync commands
            await self.tree.sync()
            logger.info("✅ Commands synced globally!")
            
            # Log registered commands
            commands = await self.tree.fetch_commands()
            logger.info(f"Registered commands: {[cmd.name for cmd in commands]}")
            
        except Exception as e:
            logger.error(f"❌ Setup failed: {str(e)}")
            raise

    def store_qa_interaction(self, user_id: int, question: str, answer: str):
        """Store Q&A interaction in MongoDB"""
        try:
            self.qa_collection.insert_one({
                'user_id': user_id,
                'question': question,
                'answer': answer,
                'timestamp': datetime.utcnow()
            })
        except Exception as e:
            logger.error(f"Failed to store Q&A interaction: {e}")

    async def generate_response(self, question: str, context: str) -> str:
        """Generate response using OpenAI"""
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a Quantified Ante trading assistant. "
                            "Provide accurate, helpful responses based on the "
                            "context provided. If the context doesn't contain "
                            "relevant information, acknowledge that and suggest "
                            "rephrasing the question."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Context: {context}\n\nQuestion: {question}"
                    }
                ],
                temperature=0.7,
                max_tokens=500
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

bot = QABot()

@bot.tree.command(name="ping", description="Test if the bot is working")
async def ping(interaction: discord.Interaction):
    """Simple ping command to check bot's status"""
    try:
        await interaction.response.defer(ephemeral=True)
        
        # Test MongoDB connection
        db_status = "Connected" if await bot.document_search.verify_connection() else "Disconnected"
        
        response = f"""🤖 Bot Status: Online
📊 MongoDB: {db_status}
⚡ Latency: {round(bot.latency * 1000)}ms"""
        
        await interaction.followup.send(response, ephemeral=True)
    except Exception as e:
        logger.error(f"Ping error: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Error checking status",
                ephemeral=True
            )

@bot.tree.command(name="ask", description="Ask about Quantified Ante trading")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    """Main Q&A command"""
    try:
        await interaction.response.defer()
        
        # Log the question
        logger.info(f"Question from {interaction.user}: {question}")
        
        # Search for relevant content
        similar_chunks = bot.document_search.search(question)
        
        if not similar_chunks:
            await interaction.followup.send(
                "I couldn't find relevant information. Please try rephrasing your question.",
                ephemeral=True
            )
            return
        
        # Generate response
        context = "\n".join(similar_chunks)
        answer = await bot.generate_response(question, context)
        
        # Store the interaction
        bot.store_qa_interaction(
            interaction.user.id,
            question,
            answer
        )
        
        # Send response in chunks if needed
        if len(answer) > 1900:  # Discord's message length limit
            chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
            await interaction.followup.send(chunks[0])
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)
        else:
            await interaction.followup.send(answer)
            
    except Exception as e:
        logger.error(f"Ask error: {e}")
        if not interaction.response.is_done():
            await interaction.followup.send(
                "An error occurred while processing your question",
                ephemeral=True
            )

@bot.tree.command(name="debug_db", description="Debug database content")
async def debug_db(interaction: discord.Interaction):
    """Command to debug database status"""
    try:
        await interaction.response.defer()
        
        # Get collection stats
        doc_count = bot.db.documents.count_documents({})
        qa_count = bot.qa_collection.count_documents({})
        
        # Sample documents
        sample_doc = bot.db.documents.find_one()
        recent_qa = list(bot.qa_collection.find().sort('timestamp', -1).limit(1))
        
        # Check indexes
        doc_indexes = list(bot.db.documents.list_indexes())
        
        response = (
            f"📊 Database Stats:\n"
            f"Documents: {doc_count}\n"
            f"QA Records: {qa_count}\n"
            f"Indexes: {', '.join(idx['name'] for idx in doc_indexes)}\n\n"
        )
        
        if sample_doc:
            response += (
                f"📄 Sample Document:\n"
                f"Fields: {', '.join(sample_doc.keys())}\n"
                f"Text Preview: {sample_doc.get('text', 'N/A')[:100]}...\n\n"
            )
        
        if recent_qa:
            qa = recent_qa[0]
            response += (
                f"❓ Latest Q&A:\n"
                f"Time: {qa['timestamp']}\n"
                f"Q: {qa['question'][:100]}...\n"
                f"A: {qa['answer'][:100]}...\n"
            )
        
        await interaction.followup.send(response)
        
    except Exception as e:
        logger.error(f"Debug command error: {e}")
        await interaction.followup.send(
            "An error occurred while debugging the database",
            ephemeral=True
        )

@bot.event
async def on_command_error(ctx, error):
    """Global error handler"""
    logger.error(f"Command error: {error}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    bot.run(DISCORD_TOKEN)