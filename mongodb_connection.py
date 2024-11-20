import os
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi
import logging
from datetime import datetime

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
        
        # Create MongoDB client
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            tls=True,
            tlsCAFile=certifi.where()
        )
        
        # Test connection by writing and reading a document
        db = client['test_database']
        collection = db['test_collection']
        
        # Insert a test document
        test_doc = {
            "test": "connection",
            "timestamp": datetime.utcnow()
        }
        
        result = collection.insert_one(test_doc)
        logger.info("✅ Successfully wrote to database!")
        
        # Read the document back
        found_doc = collection.find_one({"_id": result.inserted_id})
        logger.info("✅ Successfully read from database!")
        
        # Clean up - delete the test document
        collection.delete_one({"_id": result.inserted_id})
        logger.info("✅ Successfully cleaned up test document!")
        
        # Get database info
        database_names = client.list_database_names()
        logger.info(f"Available databases: {database_names}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Connection failed: {str(e)}")
        logger.error("Please check if 0.0.0.0/0 is added to MongoDB Atlas Network Access")
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