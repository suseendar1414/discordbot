import os
import discord
from discord import app_commands
import logging
from dotenv import load_dotenv
from openai import OpenAI

# Enhanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GUILD_ID = 1307930198817116221

# Initialize OpenAI
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Sample trading content
TRADING_CONTENT = """
[Your existing trading content...]
"""

class QABot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.setup_commands()

    def setup_commands(self):
        @self.tree.command(name="hello", description="Get a greeting")
        async def hello(interaction: discord.Interaction):
            await interaction.response.send_message(f"Hello, {interaction.user.name}!")

        @self.tree.command(name="ping", description="Test bot response")
        async def ping(interaction: discord.Interaction):
            await interaction.response.send_message("Pong!")

        @self.tree.command(name="echo", description="Repeat a message")
        @app_commands.describe(message="The message to repeat")
        async def echo(interaction: discord.Interaction, message: str):
            await interaction.response.send_message(f"You said: {message}")

        @self.tree.command(name="ask", description="Ask about trading")
        @app_commands.describe(question="Your question about trading")
        async def ask(interaction: discord.Interaction, question: str):
            logger.info(f"Question received: {question}")
            await interaction.response.defer()
            
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a Quantified Ante trading assistant."
                        },
                        {
                            "role": "user",
                            "content": f"Context: {TRADING_CONTENT}\n\nQuestion: {question}"
                        }
                    ]
                )
                
                answer = response.choices[0].message.content
                
                if len(answer) > 1900:
                    parts = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
                    await interaction.followup.send(parts[0])
                    for part in parts[1:]:
                        await interaction.followup.send(part)
                else:
                    await interaction.followup.send(answer)
                    
            except Exception as e:
                logger.error(f"Error in ask command: {e}")
                await interaction.followup.send(
                    "An error occurred while processing your question. Please try again."
                )

        @self.tree.command(name="help", description="Show available commands")
        async def help(interaction: discord.Interaction):
            help_text = """
Available Commands:
• /hello - Get a greeting
• /ping - Test bot response
• /echo message:"text" - Repeat a message
• /ask question:"text" - Ask about trading
• /help - Show this help message

Example:
/ask question:"What is MMBM?"
"""
            await interaction.response.send_message(help_text)

    async def setup_hook(self):
        """This is called when the bot starts."""
        logger.info("Starting command sync...")
        try:
            # Sync to specific guild
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Guild commands synced!")
            
            # Sync globally
            await self.tree.sync()
            logger.info("Global commands synced!")
            
        except Exception as e:
            logger.error(f"Error syncing commands: {e}")
            raise

    async def on_ready(self):
        logger.info(f"Bot is ready! Logged in as {self.user}")
        
        # List all guilds
        logger.info("Connected to guilds:")
        for guild in self.guilds:
            logger.info(f"- {guild.name} (ID: {guild.id})")
        
        # List available commands
        commands = await self.tree.fetch_commands()
        logger.info("Available global commands:")
        for cmd in commands:
            logger.info(f"- /{cmd.name}: {cmd.description}")

if __name__ == "__main__":
    logger.info("Starting bot...")
    try:
        bot = QABot()
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
