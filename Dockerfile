FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Make sure environment variables are passed through
ENV DISCORD_TOKEN=${DISCORD_TOKEN}
ENV OPENAI_API_KEY=${OPENAI_API_KEY}
ENV MONGODB_URI=${MONGODB_URI}
ENV PORT=8080

# Expose the port
EXPOSE 8080

# Start the bot
CMD ["python", "discord_bot1.py"]