#!/usr/bin/env python3
import os
import logging
import asyncio
import traceback
import platform
import time
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# Local imports
import db
import views
from cogs.ctf import CTFCommands
from cogs.challenge import ChallengeCommands
from cogs.repo_viewer import RepoViewerCommands
import logging_config
from cogs.debug import DebugCommands

# Start execution timer for startup metrics
start_time = time.time()

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
DEFAULT_GUILD = os.getenv('DEFAULT_GUILD')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# Setup logging
logger = logging_config.setup_logging(LOG_LEVEL)
logger = logging.getLogger('bot')

# Initialize the bot with proper intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned,  # Only respond to @mentions
    intents=intents,
    help_command=None  # We'll use a custom /help command
)

# Periodic task to refresh the board
@tasks.loop(hours=1)
async def refresh_board():
    """Periodically refresh the CTF board to keep it up-to-date."""
    logger.info("Running scheduled board refresh...")
    try:
        await views.update_board(bot)
        logger.info("Scheduled board refresh completed")
    except Exception as e:
        logger.error(f"Error during scheduled board refresh: {e}")
        logger.error(traceback.format_exc())

@refresh_board.before_loop
async def before_refresh_board():
    """Wait until the bot is ready before starting the board refresh task."""
    await bot.wait_until_ready()
    logger.info("Board refresh task is ready to start")

@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    # Calculate startup time
    startup_time = time.time() - start_time
    
    # Log system information
    logger.info(f"Bot connected as {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"Discord.py version: {discord.__version__}")
    logger.info(f"Python version: {platform.python_version()}")
    logger.info(f"Running on: {platform.system()} {platform.release()} ({os.name})")
    logger.info(f"Startup time: {startup_time:.2f} seconds")
    
    # Count guilds the bot is in
    guild_count = len(bot.guilds)
    logger.info(f"Connected to {guild_count} guilds")
    
    # Register cogs
    await bot.add_cog(CTFCommands(bot))
    await bot.add_cog(ChallengeCommands(bot))
    await bot.add_cog(RepoViewerCommands(bot))
    
    # Always add the debug commands (but in DEBUG mode, log it)
    await bot.add_cog(DebugCommands(bot))
    if LOG_LEVEL == 'DEBUG':
        logger.debug("Debug commands enabled in DEBUG mode")
    else:
        logger.info("Debug commands available for operational use")
    
    # Sync commands
    if DEFAULT_GUILD:
        guild = discord.Object(id=int(DEFAULT_GUILD))
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        logger.info(f"Synced commands to guild {DEFAULT_GUILD}")
    else:
        await bot.tree.sync()
        logger.info('Synced commands globally (may take up to 1 hour)')
    
    # Update the CTF board on startup
    logger.info("Updating CTF board at startup to reflect fresh state...")
    try:
        await views.update_board(bot)
        logger.info("CTF board updated successfully - showing fresh state with no active CTF")
    except Exception as e:
        logger.error(f"Error updating CTF board at startup: {e}")
        logger.error(traceback.format_exc())
    
    # Start the periodic board refresh
    if not refresh_board.is_running():
        refresh_board.start()
        logger.info("Started periodic board refresh task (runs hourly)")
    
    logger.info("Bot is fully ready!")


@bot.event
async def on_application_command_error(ctx, error):
    """Global error handler for slash commands"""
    # Extract the original error if it's wrapped in a CommandInvokeError
    if isinstance(error, discord.app_commands.CommandInvokeError):
        error = error.original
    
    # Handle known error types
    if isinstance(error, discord.errors.NotFound) and error.code == 10062:
        # This is an interaction timeout - log it but don't notify the user
        command_name = ctx.command.name if ctx.command else "Unknown command"
        user = f"{ctx.user.name}" if ctx.user else "Unknown user"
        guild = ctx.guild.name if ctx.guild else "DM"
        logger.warning(f"Interaction expired for command '{command_name}' by {user} in {guild}")
        return
    
    # Log the full traceback with context
    trace = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    
    # Get command context for better logging
    command_name = ctx.command.name if ctx.command else "Unknown command"
    user = f"{ctx.user.name}" if ctx.user else "Unknown user"
    guild = ctx.guild.name if ctx.guild else "DM"
    
    logger.error(
        f"Error in command '{command_name}' invoked by {user} in {guild}:\n{trace}"
    )
    
    # Send a user-friendly error message
    try:
        error_message = "⚠️ Something went wrong while executing that command."
        
        # If in DEBUG mode, add more details for testers
        if LOG_LEVEL == 'DEBUG':
            error_message += f"\n\nError: `{type(error).__name__}: {str(error)}`"
            
        await ctx.response.send_message(
            error_message,
            ephemeral=True
        )
    except discord.errors.InteractionResponded:
        # If the interaction has already been responded to
        await ctx.followup.send(
            "⚠️ Something went wrong while executing that command.",
            ephemeral=True
        )
    except discord.errors.NotFound:
        # If the interaction is no longer valid, don't try to respond
        logger.debug(f"Could not respond to expired interaction for '{command_name}'")


@bot.event
async def on_guild_join(guild):
    """Log when the bot joins a new guild."""
    logger.info(f"Joined new guild: {guild.name} (ID: {guild.id})")
    logger.info(f"Guild owner: {guild.owner} (ID: {guild.owner_id})")
    logger.info(f"Guild member count: {guild.member_count}")


@bot.event 
async def on_guild_remove(guild):
    """Log when the bot is removed from a guild."""
    logger.info(f"Removed from guild: {guild.name} (ID: {guild.id})")


async def main():
    """Main entry point for the bot."""
    try:
        # Log current working directory
        logger.debug(f"Current working directory: {os.getcwd()}")
        
        # Initialize database
        logger.info("Initializing database...")
        await db.init()
        
        # Reset database to fresh state on startup
        logger.info("Resetting to fresh state...")
        await db.reset_db()
        
        # Start the bot
        logger.info("Starting bot...")
        async with bot:
            await bot.start(TOKEN)
    except Exception as e:
        logger.critical(f"Fatal error during startup: {e}")
        logger.critical(traceback.format_exc())
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped via keyboard interrupt")
    except Exception as e:
        logger.critical(f"Unhandled exception: {e}")
        logger.critical(traceback.format_exc()) 