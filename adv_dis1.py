import os
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi
import logging

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mongodb_test')

def test_mongodb_connection():
    # Load environment variables
    load_dotenv()
    
    # Get MongoDB URI from environment variable
    MONGODB_URI = os.getenv('MONGODB_URI')
    
    if not MONGODB_URI:
        logger.error("MONGODB_URI environment variable is not set")
        return False
    
    try:
        logger.info("Attempting to connect to MongoDB...")
        logger.debug(f"Using URI pattern: {MONGODB_URI.split('@')[0]}@[HIDDEN]")
        
        # Create MongoDB client with updated parameters
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            tls=True,
            tlsCAFile=certifi.where()
        )
        
        # Test the connection
        client.server_info()
        logger.info("✅ Successfully connected to MongoDB!")
        
        # Get database info
        database_names = client.list_database_names()
        logger.info(f"Available databases: {database_names}")
        
        # Test a specific database
        db_name = 'quantified_ante'  # Replace with your database name
        db = client[db_name]
        collections = db.list_collection_names()
        logger.info(f"Collections in {db_name}: {collections}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Connection failed: {str(e)}")
        return False
    finally:
        try:
            client.close()
            logger.info("Connection closed")
        except:
            pass

if __name__ == "__main__":
    print("Testing MongoDB Connection...")
    test_mongodb_connection()