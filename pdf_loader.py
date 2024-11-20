import os
from dotenv import load_dotenv
import PyPDF2
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from pymongo import MongoClient
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('pdf_loader')

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
MONGODB_URI = os.getenv('MONGODB_URI')

PDF_PATH = "/Users/suseendarmuralidharan/Documents/QuantifiedAI/SMC Predictive Strategy with Supporting Criteria for Quantified Ante Predictive Application.pdf"

def load_pdf_to_mongodb():
    """Load PDF content into MongoDB with embeddings"""
    logger.info("Starting PDF loading process...")
    
    # MongoDB setup
    client = MongoClient(MONGODB_URI)
    db = client['quantified_ante']
    collection = db['documents']
    
    # Initialize embeddings
    embeddings_model = OpenAIEmbeddings()
    
    # Read PDF
    logger.info(f"Reading PDF from: {PDF_PATH}")
    with open(PDF_PATH, 'rb') as file:
        pdf_reader = PyPDF2.PdfReader(file)
        text = ''
        for page in pdf_reader.pages:
            text += page.extract_text()
    
    # Split text into chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = text_splitter.split_text(text)
    logger.info(f"Split PDF into {len(chunks)} chunks")
    
    # Clear existing documents
    collection.delete_many({})
    logger.info("Cleared existing documents from MongoDB")
    
    # Store chunks with embeddings
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
    logger.info(f"Successfully stored {len(documents)} documents in MongoDB")
    
    client.close()
    logger.info("MongoDB connection closed")

if __name__ == "__main__":
    load_pdf_to_mongodb()