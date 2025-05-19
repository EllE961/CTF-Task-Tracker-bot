#!/usr/bin/env python3
import os
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import github_utils
import logging_config

load_dotenv()
logger = logging.getLogger('bot.cogs.repo_viewer')

# Get the repository viewer channel ID from environment variable
REPO_VIEWER_CHANNEL_ID = os.getenv('REPO_VIEWER_CHANNEL_ID')
# Update interval in minutes
REPO_UPDATE_INTERVAL = int(os.getenv('REPO_UPDATE_INTERVAL', '30'))
# Max message size to handle Discord's character limits
MAX_MESSAGE_SIZE = 1900  # Leave some buffer from the 2000 character limit

class RepoViewerCommands(commands.Cog):
    """Commands for managing the GitHub repository viewer."""
    
    def __init__(self, bot):
        self.bot = bot
        self.last_message_ids = []  # Store IDs of messages with repo structure
        # Register this instance for other cogs to access
        RepoViewerCommands.register_instance(self)
        # Start the auto-update task
        self.auto_update_repo.start()
    
    def cog_unload(self):
        """Called when the cog is unloaded."""
        self.auto_update_repo.cancel()  # Stop the auto-update task
    
    # Static reference to instance for other cogs to access
    _instance = None
    
    @classmethod
    def register_instance(cls, instance):
        """Register the instance for other cogs to access."""
        cls._instance = instance
    
    @classmethod
    async def trigger_update(cls):
        """Trigger a repository update from other cogs."""
        if cls._instance:
            await cls._instance.update_repo_view()
        else:
            logger.warning("Cannot trigger repo view update: No instance registered")
    
    async def get_repo_viewer_channel(self):
        """Get the repository viewer channel."""
        if not REPO_VIEWER_CHANNEL_ID:
            logger.warning("REPO_VIEWER_CHANNEL_ID not set in environment variables")
            return None
        
        try:
            channel_id = int(REPO_VIEWER_CHANNEL_ID)
            channel = self.bot.get_channel(channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(channel_id)
            return channel
        except (ValueError, discord.errors.NotFound, discord.errors.Forbidden) as e:
            logger.error(f"Failed to get repo viewer channel: {e}")
            return None
    
    async def clear_previous_messages(self, channel):
        """Clear previous repository structure messages."""
        for msg_id in self.last_message_ids:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
            except (discord.errors.NotFound, discord.errors.Forbidden) as e:
                logger.warning(f"Failed to delete message {msg_id}: {e}")
        
        self.last_message_ids = []
    
    async def update_repo_view(self):
        """Update the repository view in the dedicated channel."""
        channel = await self.get_repo_viewer_channel()
        if not channel:
            return False
        
        try:
            # Get repository structure
            structure = await github_utils.get_repo_structure()
            
            # Format the structure as text
            formatted_structure = f"# 📁 GitHub Repository Structure\n\n```\n{github_utils.format_repo_structure(structure)}\n```"
            
            # Clear previous messages
            await self.clear_previous_messages(channel)
            
            # Split into chunks if needed (Discord has 2000 character limit)
            chunks = self._split_message(formatted_structure)
            
            # Send messages
            for chunk in chunks:
                message = await channel.send(chunk)
                self.last_message_ids.append(message.id)
            
            logger.info(f"Updated repository structure in channel {channel.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating repository view: {e}")
            return False
    
    def _split_message(self, message):
        """Split a message into chunks that fit within Discord's limits."""
        if len(message) <= MAX_MESSAGE_SIZE:
            return [message]
        
        chunks = []
        current_pos = 0
        
        while current_pos < len(message):
            # Find a good break point
            end_pos = current_pos + MAX_MESSAGE_SIZE
            
            if end_pos >= len(message):
                # This is the last chunk
                chunks.append(message[current_pos:])
                break
                
            # Try to break at a newline
            break_pos = message.rfind('\n', current_pos, end_pos)
            if break_pos == -1:
                # No newline found, break at the max size
                break_pos = end_pos
            else:
                # Include the newline
                break_pos += 1
                
            chunks.append(message[current_pos:break_pos])
            current_pos = break_pos
            
        return chunks
    
    @tasks.loop(minutes=REPO_UPDATE_INTERVAL)
    async def auto_update_repo(self):
        """Automatically update the repository view periodically."""
        logger.debug(f"Running scheduled repository update (every {REPO_UPDATE_INTERVAL} minutes)")
        await self.update_repo_view()
    
    @auto_update_repo.before_loop
    async def before_auto_update(self):
        """Wait for the bot to be ready before starting the auto-update loop."""
        await self.bot.wait_until_ready()
        logger.info("Bot ready, waiting 10 seconds before initial repo structure update")
        await asyncio.sleep(10)  # Wait a bit after startup before first update
        
        # Initial update
        logger.info("Performing initial repository structure update")
        await self.update_repo_view()
    
    @app_commands.command(name="update_repo_view", description="Update the repository structure view")
    async def update_repo_view_command(self, interaction: discord.Interaction):
        """Manually update the repository structure view."""
        # Log command
        logging_config.log_command(logger, "update_repo_view", interaction)
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        # Update the repository view
        success = await self.update_repo_view()
        
        if success:
            await interaction.followup.send(
                "✅ Repository structure view has been updated.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "⚠️ Failed to update repository structure view. Check the logs for details.",
                ephemeral=True
            )
    
    @app_commands.command(name="show_repo_structure", description="Show the repository structure in the current channel")
    async def show_repo_structure(self, interaction: discord.Interaction):
        """Show the repository structure in the current channel."""
        # Log command
        logging_config.log_command(logger, "show_repo_structure", interaction)
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Get repository structure
            structure = await github_utils.get_repo_structure()
            
            # Format the structure as text
            formatted_structure = f"# 📁 GitHub Repository Structure\n\n```\n{github_utils.format_repo_structure(structure)}\n```"
            
            # Split into chunks if needed
            chunks = self._split_message(formatted_structure)
            
            # Send the first chunk as a followup
            await interaction.followup.send(chunks[0], ephemeral=True)
            
            # Send additional chunks as regular messages
            for chunk in chunks[1:]:
                await interaction.channel.send(chunk, ephemeral=True)
                
            logger.info(f"Showed repository structure to user {interaction.user.name}")
            
        except Exception as e:
            logger.error(f"Error showing repository structure: {e}")
            await interaction.followup.send(
                "⚠️ Failed to show repository structure. Check the logs for details.",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(RepoViewerCommands(bot)) 