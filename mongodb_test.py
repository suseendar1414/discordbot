import os
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('mongodb_test')

# Load environment variables
load_dotenv()
MONGODB_URI = os.getenv('MONGODB_URI')

def test_mongodb_connection():
    try:
        # Connect with SSL/TLS settings
        client = MongoClient(
            MONGODB_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000
        )
        
        # Test the connection
        client.admin.command('ping')
        logger.info("MongoDB connection successful!")
        
        # Test database access
        db = client['quantified_ante']
        collections = db.list_collection_names()
        logger.info(f"Available collections: {collections}")
        
        # Close the connection
        client.close()
        logger.info("Connection closed successfully")
        
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        raise

if __name__ == "__main__":
    test_mongodb_connection()
