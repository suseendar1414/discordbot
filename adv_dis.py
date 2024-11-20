import os
import discord
from discord import app_commands
import logging
from dotenv import load_dotenv
from openai import OpenAI

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GUILD_ID = 1307930198817116221

# Initialize OpenAI
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Sample trading content (temporary replacement for MongoDB)
TRADING_CONTENT = """
MMBM (Market Maker Buy Model) is when we see bullish price action and MMSM is Bearish order flow.
Market Maker Buy Model (MMBM) indicates a bullish market structure where smart money narrative suggests price is moving to attract buy-side interest from institutional traders.
In an MMBM, we see bullish price action (PA) as the market seeks to push higher. It typically follows a pattern where liquidity is sought out below key lows before a sustained move to the upside occurs.

Order Blocks represent areas where institutional traders place significant orders, creating a base for price reversals or continuations.
Order blocks are crucial for spotting where institutional activity has occurred, thus setting up potential trading opportunities.

The Silver Bullet Strategy is a specific trading approach based on Smart Money Concepts (SMC). It leverages the principles used by institutional traders to understand market movements and make informed trading decisions.
"""

class QABot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        MY_GUILD = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=MY_GUILD)
        await self.tree.sync(guild=MY_GUILD)
        logger.info("Commands synced!")

client = QABot()

@client.event
async def on_ready():
    logger.info(f"Bot is ready! Logged in as {client.user}")

@client.tree.command(name="hello")
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello, {interaction.user.name}!")

@client.tree.command(name="ping")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

@client.tree.command(name="echo")
@app_commands.describe(message="The message to repeat")
async def echo(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(f"You said: {message}")

@client.tree.command(name="ask")
@app_commands.describe(question="Your question about trading")
async def ask(interaction: discord.Interaction, question: str):
    """Answer questions about trading using local content"""
    logger.info(f"Question received: {question}")
    await interaction.response.defer()
    
    try:
        # Use OpenAI to generate response based on local content
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You are a Quantified Ante trading assistant. Answer questions based only on the provided context."
                },
                {
                    "role": "user",
                    "content": f"Context: {TRADING_CONTENT}\n\nQuestion: {question}\n\nAnswer based only on the information provided in the context:"
                }
            ]
        )
        
        answer = response.choices[0].message.content
        
        # Send response
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

@client.tree.command(name="help")
async def help(interaction: discord.Interaction):
    """Show available commands"""
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

@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.error(f"Command error: {str(error)}")
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "An error occurred while processing the command.",
            ephemeral=True
        )

if __name__ == "__main__":
    logger.info("Starting bot...")
    client.run(DISCORD_TOKEN)