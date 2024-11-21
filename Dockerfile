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

# Create an entrypoint script
RUN echo '#!/bin/sh\n\
printenv > /app/.env\n\
python discord_bot1.py\n' > /app/entrypoint.sh && \
    chmod +x /app/entrypoint.sh

# Default port
EXPOSE 8080

# Use entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]