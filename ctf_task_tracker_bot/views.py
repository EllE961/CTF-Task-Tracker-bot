#!/usr/bin/env python3
"""
Views Module for CTF Task-Tracker Bot

This module handles the UI components and display logic for the Discord interface.
It's responsible for:
- Building and updating the challenge board embed
- Creating interactive buttons for each challenge
- Managing button interactions (claim, unclaim, solve)
- Ensuring consistent UI presentation

The module creates a persistent board that shows:
- Current active CTF
- Challenges grouped by category
- Status of each challenge (unclaimed, claimed, solved)
- Real user mentions for claimed challenges

Each challenge has its own set of context-aware buttons that change based on state:
- Unclaimed: Shows a Claim button
- Claimed: Shows Unclaim and Solved buttons
- Solved: Shows no buttons

The board is automatically updated when:
- The bot starts up
- Changes are made to challenges
- On a regular schedule (hourly)

This ensures the board always reflects the current state of challenges.
"""
import os
import logging
import asyncio
import time
import traceback
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Any

import discord
from discord.ui import Button, View
from dotenv import load_dotenv

import db
import logging_config

load_dotenv()
logger = logging.getLogger('bot.views')

# Get board channel ID from environment
BOARD_CHANNEL_ID = int(os.getenv('BOARD_CHANNEL_ID', 0))

class TaskButtons(View):
    """
    Button UI components for the task board.
    
    Buttons:
        - Claim: Claim a task
        - Unclaim: Release a claimed task
        - Solved: Mark a task as solved
    """
    def __init__(self, bot, task_id: int, claimed_by: Optional[int] = None, solved: bool = False):
        super().__init__(timeout=None)  # No timeout for persistent UI
        self.bot = bot
        self.task_id = task_id
        self.claimed_by = claimed_by
        self.solved = solved
        
        # Initialize buttons based on task state
        self._setup_buttons()
        
        # Log button creation
        if solved:
            logger.debug(f"TaskButtons created for task #{task_id} (solved, no buttons)")
        elif claimed_by:
            logger.debug(f"TaskButtons created for task #{task_id} (claimed by {claimed_by}, Unclaim+Solved buttons)")
        else:
            logger.debug(f"TaskButtons created for task #{task_id} (unclaimed, Claim button)")
    
    def _setup_buttons(self):
        """Setup buttons based on task state."""
        # Clear any existing buttons
        self.clear_items()
        
        if self.solved:
            # No buttons for solved tasks
            return
            
        if self.claimed_by:
            # Task is claimed - show Unclaim and Solved buttons
            unclaim_btn = Button(
                label="⚪ Unclaim",
                style=discord.ButtonStyle.secondary,
                custom_id=f"unclaim_{self.task_id}"
            )
            unclaim_btn.callback = self.on_unclaim
            self.add_item(unclaim_btn)
            
            solved_btn = Button(
                label="✅ Solved", 
                style=discord.ButtonStyle.success,
                custom_id=f"solved_{self.task_id}"
            )
            solved_btn.callback = self.on_solved
            self.add_item(solved_btn)
        else:
            # Task is unclaimed - show Claim button
            claim_btn = Button(
                label="🔷 Claim",
                style=discord.ButtonStyle.primary,
                custom_id=f"claim_{self.task_id}"
            )
            claim_btn.callback = self.on_claim
            self.add_item(claim_btn)
    
    async def on_claim(self, interaction: discord.Interaction):
        """Handle claim button press."""
        # Log button click
        user = f"{interaction.user.name}#{interaction.user.discriminator}"
        logger.info(f"Claim button clicked for task #{self.task_id} by {user}")
        logging_config.log_button(logger, "Claim", interaction, self.task_id)
        
        # Import here to avoid circular imports
        from cogs.challenge import ChallengeCommands
        
        # Get the challenge cog
        challenge_cog = self.bot.get_cog("ChallengeCommands")
        if challenge_cog:
            # Use the claim handler from the cog
            await challenge_cog.handle_claim(interaction, self.task_id)
        else:
            logger.error(f"ChallengeCommands cog not found when handling claim for task #{self.task_id}")
            await interaction.response.send_message(
                "⚠️ Error: Challenge commands not available.",
                ephemeral=True
            )
    
    async def on_unclaim(self, interaction: discord.Interaction):
        """Handle unclaim button press."""
        # Log button click
        user = f"{interaction.user.name}#{interaction.user.discriminator}"
        logger.info(f"Unclaim button clicked for task #{self.task_id} by {user}")
        logging_config.log_button(logger, "Unclaim", interaction, self.task_id)
        
        # Import here to avoid circular imports
        from cogs.challenge import ChallengeCommands
        
        # Get the challenge cog
        challenge_cog = self.bot.get_cog("ChallengeCommands")
        if challenge_cog:
            # Use the unclaim handler from the cog
            await challenge_cog.handle_unclaim(interaction, self.task_id)
        else:
            logger.error(f"ChallengeCommands cog not found when handling unclaim for task #{self.task_id}")
            await interaction.response.send_message(
                "⚠️ Error: Challenge commands not available.",
                ephemeral=True
            )
    
    async def on_solved(self, interaction: discord.Interaction):
        """Handle solved button press."""
        # Log button click
        user = f"{interaction.user.name}#{interaction.user.discriminator}"
        logger.info(f"Solved button clicked for task #{self.task_id} by {user}")
        logging_config.log_button(logger, "Solved", interaction, self.task_id)
        
        # Import here to avoid circular imports
        from cogs.challenge import ChallengeCommands
        
        # Get the challenge cog
        challenge_cog = self.bot.get_cog("ChallengeCommands")
        if challenge_cog:
            # Use the solved handler from the cog
            await challenge_cog.handle_solved(interaction, self.task_id)
        else:
            logger.error(f"ChallengeCommands cog not found when handling solved for task #{self.task_id}")
            await interaction.response.send_message(
                "⚠️ Error: Challenge commands not available.",
                ephemeral=True
            )

async def build_board_embed(bot) -> Tuple[discord.Embed, List[TaskButtons]]:
    """
    Build the board embed and task buttons.
    
    Returns:
        A tuple containing the board embed and a list of TaskButtons views
    """
    start_time = time.time()
    logger.debug("Building board embed")
    
    # Get active CTF
    ctf_name, ctf_year = await db.get_active_ctf()
    
    # Create embed
    embed = discord.Embed(color=discord.Color.blue())
    
    if ctf_name and ctf_year:
        # Active CTF - set title and get tasks
        embed.title = f"📋 {ctf_name.lower()}-{ctf_year} Board"
        logger.debug(f"Building board for active CTF: {ctf_name}-{ctf_year}")
        tasks = await db.get_all_tasks()
    else:
        # No active CTF
        embed.title = "📋 No active CTF"
        embed.description = "No CTF is currently active. Use `/ctf_add` to start one."
        logger.debug("No active CTF, returning empty board")
        return embed, []
    
    if not tasks:
        # No tasks in the active CTF
        embed.description = "No challenges added yet. Use `/challenge_add` to add one."
        logger.debug(f"No tasks for CTF {ctf_name}-{ctf_year}, returning empty board")
        return embed, []
    
    # Group tasks by category
    tasks_by_category = defaultdict(list)
    for task in tasks:
        task_id, category, name, claimed_by, solved = task
        tasks_by_category[category].append((task_id, name, claimed_by, solved))
    
    logger.debug(f"Found {len(tasks)} tasks in {len(tasks_by_category)} categories")
    
    # Create task buttons list
    task_buttons = []
    
    # Add categories and tasks to embed
    for i, (category, tasks) in enumerate(sorted(tasks_by_category.items())):
        # Add a separator between categories
        if i > 0:
            embed.add_field(name="\u200b", value="───────────────────", inline=False)
            
        # Add category as a field title (capitalized)
        category_text = category.capitalize()
        embed.add_field(name=category_text, value="", inline=False)
        logger.debug(f"Added category '{category}' with {len(tasks)} tasks")
        
        # Add tasks under the category
        tasks_text = []
        for task_id, name, claimed_by, solved in sorted(tasks, key=lambda t: t[0]):
            # Format the task entry
            status_emoji = "✅" if solved else "🚧"
            task_text = f"{status_emoji}  #{task_id} {name}"
            
            if solved:
                # Solved task
                task_text += "  ✓ solved"
                logger.debug(f"Task #{task_id} ({name}) is solved")
            elif claimed_by:
                # Claimed but not solved
                user = bot.get_user(claimed_by)
                if user:
                    # Use a real Discord mention
                    task_text += f"  <@{claimed_by}>"
                    logger.debug(f"Task #{task_id} ({name}) is claimed by {user.name} (using mention)")
                else:
                    task_text += f"  User {claimed_by}"
                    logger.debug(f"Task #{task_id} ({name}) is claimed by unknown user {claimed_by}")
            else:
                # Unclaimed
                task_text += "  ▫️ unclaimed"
                logger.debug(f"Task #{task_id} ({name}) is unclaimed")
            
            tasks_text.append(task_text)
            
            # Create buttons for this task
            buttons = TaskButtons(bot, task_id, claimed_by, solved)
            if buttons.children:  # Only add if there are buttons
                task_buttons.append(buttons)
        
        # Join task entries with newlines and add as field value
        field_value = "\n".join(tasks_text) if tasks_text else "No challenges in this category."
        embed.set_field_at(-1, name=category_text, value=field_value, inline=False)
    
    build_time = time.time() - start_time
    logger.debug(f"Board embed built in {build_time:.6f} seconds with {len(task_buttons)} button views")
    
    return embed, task_buttons

async def update_board(bot) -> bool:
    """
    Update the CTF board message.
    
    If a board message exists, edit it.
    If not, create a new one.
    
    Returns:
        True if successful, False otherwise
    """
    start_time = time.time()
    logger.info("Updating board message")
    
    if not BOARD_CHANNEL_ID:
        logger.error("BOARD_CHANNEL_ID not set in environment variables")
        return False
    
    # Get the board channel
    channel = bot.get_channel(BOARD_CHANNEL_ID)
    if not channel:
        logger.error(f"Cannot find channel with ID {BOARD_CHANNEL_ID}")
        return False
    
    try:
        # Build the board embed and button views
        embed, task_buttons = await build_board_embed(bot)
        
        # Try to get existing board message ID
        message_id = await db.get_board_message(BOARD_CHANNEL_ID)
        
        if message_id:
            try:
                # Try to fetch and edit the existing message
                logger.debug(f"Attempting to edit existing board message {message_id}")
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=None)
                
                # Add buttons as separate messages under the board
                # First, delete any existing button messages
                button_count = 0
                async for msg in channel.history(limit=100):
                    if msg.author == bot.user and msg.id != message_id:
                        await msg.delete()
                        button_count += 1
                
                logger.debug(f"Deleted {button_count} existing button messages")
                
                # Then add new button messages
                for buttons in task_buttons:
                    # Get task info to label the buttons
                    task_info = await db.run(
                        "SELECT category, name FROM tasks WHERE id = ?",
                        buttons.task_id,
                        fetchone=True
                    )
                    if task_info:
                        category, name = task_info
                        button_label = f"#{buttons.task_id} - {category}/{name}"
                        await channel.send(content=button_label, view=buttons)
                    else:
                        await channel.send(content=f"Challenge #{buttons.task_id}", view=buttons)
                
                update_time = time.time() - start_time
                logger.info(f"Updated board message {message_id} in {update_time:.6f} seconds with {len(task_buttons)} button messages")
                return True
                
            except discord.NotFound:
                # Message was deleted, create a new one
                logger.warning(f"Board message {message_id} not found, creating new one")
                message_id = None
        
        if not message_id:
            # Create a new board message
            logger.debug("Creating new board message")
            message = await channel.send(embed=embed)
            await db.set_board_message(BOARD_CHANNEL_ID, message.id)
            
            # Add buttons as separate messages under the board
            for buttons in task_buttons:
                # Get task info to label the buttons
                task_info = await db.run(
                    "SELECT category, name FROM tasks WHERE id = ?",
                    buttons.task_id,
                    fetchone=True
                )
                if task_info:
                    category, name = task_info
                    button_label = f"#{buttons.task_id} - {category}/{name}"
                    await channel.send(content=button_label, view=buttons)
                else:
                    await channel.send(content=f"Challenge #{buttons.task_id}", view=buttons)
            
            update_time = time.time() - start_time
            logger.info(f"Created new board message {message.id} in {update_time:.6f} seconds with {len(task_buttons)} button messages")
            return True
            
    except Exception as e:
        logger.error(f"Error updating board: {e}")
        logger.error(traceback.format_exc())
        return False
        
    return True 