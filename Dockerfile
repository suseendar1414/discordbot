FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create a script to load environment variables and start the bot
RUN echo '#!/bin/bash\n\
echo "DISCORD_TOKEN=$DISCORD_TOKEN" > .env\n\
echo "OPENAI_API_KEY=$OPENAI_API_KEY" >> .env\n\
echo "MONGODB_URI=$MONGODB_URI" >> .env\n\
echo "DB_NAME=$DB_NAME" >> .env\n\
echo "PORT=$PORT" >> .env\n\
cat .env\n\
python discord_bot1.py' > start.sh && chmod +x start.sh

# Default port (can be overridden)
ENV PORT=8080

# Expose the port
EXPOSE 8080

# Start the bot using the script
CMD ["./start.sh"]