#!/usr/bin/env python3
import os
import logging
import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import db
import github_utils
import views
import logging_config
from cogs.repo_viewer import RepoViewerCommands

load_dotenv()
logger = logging.getLogger('bot.cogs.ctf')
LEAD_ROLE_NAME = os.getenv('LEAD_ROLE_NAME', 'CTF Lead')

class CTFCommands(commands.Cog):
    """Commands for managing CTF events."""
    
    def __init__(self, bot):
        self.bot = bot
    
    async def _is_lead(self, interaction: discord.Interaction) -> bool:
        """Check if the user has the CTF Lead role."""
        lead_role = discord.utils.get(interaction.guild.roles, name=LEAD_ROLE_NAME)
        if not lead_role:
            await interaction.response.send_message(
                f"⚠️ The '{LEAD_ROLE_NAME}' role doesn't exist on this server.", 
                ephemeral=True
            )
            return False
            
        if lead_role not in interaction.user.roles:
            await interaction.response.send_message(
                f"⚠️ You need the '{LEAD_ROLE_NAME}' role to use this command.", 
                ephemeral=True
            )
            return False
            
        return True
    
    @app_commands.command(name="ctf_add", description="Start a new CTF session")
    @app_commands.describe(
        name="Name of the CTF (e.g., 'dam' for 'dam-2025')",
        year="Year of the CTF (e.g., 2025)"
    )
    async def ctf_add(self, interaction: discord.Interaction, name: str, year: int):
        """
        Start a new CTF session by setting it as the active CTF.
        
        Args:
            name: Name of the CTF
            year: Year of the CTF
        """
        # Check if user has the lead role
        if not await self._is_lead(interaction):
            return
        
        # Normalize CTF name (lowercase, no spaces)
        name = name.lower().strip()
        
        # Log command
        logging_config.log_command(logger, "ctf_add", interaction, name=name, year=year)
        
        # Respond to acknowledge the command
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Check if there's already an active CTF
            current_ctf_name, current_ctf_year = await db.get_active_ctf()
            if current_ctf_name and current_ctf_year:
                await interaction.followup.send(
                    f"⚠️ There is already an active CTF: `{current_ctf_name}-{current_ctf_year}`.\n"
                    f"Please run `/ctf_done` first to mark it as finished before starting a new one.",
                    ephemeral=True
                )
                return
            
            # Format the CTF folder name
            ctf_folder = f"{name}-{year}"
            
            # Create the CTF directory in GitHub if it doesn't exist
            logger.info(f"Creating root directory for CTF: {ctf_folder}")
            
            # Try to create a placeholder README.md in the CTF folder
            readme_path = f"{ctf_folder}/README.md"
            readme_content = f"# {name.upper()} {year}\n\nCTF challenge write-ups and resources.\n"
            
            try:
                # Create CTF root directory with a README
                created = await github_utils.create_file_if_not_exists(
                    path=readme_path,
                    content=readme_content,
                    message=f"Initialize CTF directory: {ctf_folder}"
                )
                
                if created:
                    logger.info(f"Created CTF root directory in GitHub: {ctf_folder}")
                else:
                    logger.info(f"CTF directory already exists in GitHub: {ctf_folder}")
            except Exception as e:
                logger.warning(f"Failed to create CTF directory: {e}")
                # Continue anyway - the directory will be created when adding challenges
            
            # Set the active CTF
            await db.set_active_ctf(name, year)
            
            # Clear all tasks from previous CTFs
            await db.delete_all_tasks()
            
            # Update the board
            await views.update_board(self.bot)
            
            # Set the repository to private for security during active CTF
            repo_private = await github_utils.set_repo_private()
            privacy_status = "and set to private" if repo_private else "(note: failed to set repository to private)"
            
            # Update the repo viewer
            await RepoViewerCommands.trigger_update()
            
            # Send success message
            await interaction.followup.send(
                f"✅ Now tracking `{name}-{year}` as the active CTF {privacy_status}.\n"
                f"GitHub directory initialized at `{ctf_folder}/`\n"
                f"Task IDs have been reset for this CTF.",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in ctf_add: {e}")
            await interaction.followup.send(
                "⚠️ An error occurred while setting up the CTF.",
                ephemeral=True
            )
    
    @app_commands.command(name="ctf_done", description="Mark the current CTF as finished")
    async def ctf_done(self, interaction: discord.Interaction):
        """Mark the current CTF as finished, preventing further challenge additions."""
        # Check if user has the lead role
        if not await self._is_lead(interaction):
            return
        
        # Log command
        logging_config.log_command(logger, "ctf_done", interaction)
        
        # Get active CTF
        ctf_name, ctf_year = await db.get_active_ctf()
        if not ctf_name or not ctf_year:
            try:
                await interaction.response.send_message(
                    "⚠️ No active CTF to mark as done.",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning("Interaction expired for ctf_done command - no active CTF")
            return
        
        # Try to defer, but catch NotFound errors
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.errors.NotFound:
            logger.warning("Interaction expired when deferring ctf_done command")
            return
        
        try:
            # Clear the active CTF
            await db.clear_active_ctf()
            
            # Update the board to show "No active CTF"
            await views.update_board(self.bot)
            
            # Update the repo viewer
            await RepoViewerCommands.trigger_update()
            
            try:
                await interaction.followup.send(
                    f"✅ Marked `{ctf_name}-{ctf_year}` as finished. No more challenges can be added.\n"
                    f"To start a new CTF, use `/ctf_add`",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning("Interaction expired when sending followup for ctf_done")
            
        except Exception as e:
            logger.error(f"Error in ctf_done: {e}")
            try:
                await interaction.followup.send(
                    "⚠️ An error occurred while marking the CTF as done.",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning("Interaction expired when sending error for ctf_done")
    
    @app_commands.command(name="ctf_publish", description="Make the repository public (only when no active CTF)")
    async def ctf_publish(self, interaction: discord.Interaction):
        """
        Publish the CTF repository by making it public.
        This command should only be used when the CTF is over.
        """
        # Check if user has the lead role
        if not await self._is_lead(interaction):
            return
        
        # Log command
        logging_config.log_command(logger, "ctf_publish", interaction)
        
        # Check if there's no active CTF (safety check)
        ctf_name, ctf_year = await db.get_active_ctf()
        if ctf_name and ctf_year:
            try:
                await interaction.response.send_message(
                    "⚠️ There is an active CTF running. For safety, you cannot publish the repository while a CTF is active.\n"
                    "Please run `/ctf_done` first to mark the CTF as finished.",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning("Interaction expired for ctf_publish command - safety check")
            return
        
        # Try to defer, but catch NotFound errors
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.errors.NotFound:
            logger.warning("Interaction expired when deferring ctf_publish command")
            return
        
        try:
            # Set the repository to public
            success = await github_utils.set_repo_public()
            
            if success:
                # Update the repo viewer
                await RepoViewerCommands.trigger_update()
                
                try:
                    await interaction.followup.send(
                        "✅ Repository has been successfully made public.\n"
                        "All CTF content is now publicly accessible.",
                        ephemeral=True
                    )
                except discord.errors.NotFound:
                    logger.warning("Interaction expired when sending success message for ctf_publish")
            else:
                try:
                    await interaction.followup.send(
                        "⚠️ Failed to make the repository public. Check the logs for details.",
                        ephemeral=True
                    )
                except discord.errors.NotFound:
                    logger.warning("Interaction expired when sending failure message for ctf_publish")
            
        except Exception as e:
            logger.error(f"Error in ctf_publish: {e}")
            try:
                await interaction.followup.send(
                    "⚠️ An error occurred while publishing the repository.",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning("Interaction expired when sending error for ctf_publish")
    
    @app_commands.command(name="ctf_clear", description="Clear claim branches for a CTF")
    @app_commands.describe(
        name="Name of the CTF to clear",
        year="Year of the CTF to clear"
    )
    async def ctf_clear(self, interaction: discord.Interaction, name: str, year: int):
        """
        Clear all claim branches for a specific CTF.
        
        Args:
            name: Name of the CTF
            year: Year of the CTF
        """
        # Check if user has the lead role
        if not await self._is_lead(interaction):
            return
        
        # Normalize CTF name
        name = name.lower().strip()
        
        # Log command
        logging_config.log_command(logger, "ctf_clear", interaction, name=name, year=year)
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Delete claim branches for this CTF
            deleted_count = await github_utils.delete_claim_branches(name, year)
            
            # Update the repo viewer
            await RepoViewerCommands.trigger_update()
            
            if deleted_count > 0:
                await interaction.followup.send(
                    f"✅ Cleared {deleted_count} claim branches for `{name}-{year}`.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"ℹ️ No claim branches found for `{name}-{year}`.",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error in ctf_clear: {e}")
            await interaction.followup.send(
                "⚠️ An error occurred while clearing claim branches.",
                ephemeral=True
            )
    
    @app_commands.command(name="ctf_delete", description="Delete a CTF and all its challenges")
    @app_commands.describe(
        name="Name of the CTF to delete",
        year="Year of the CTF to delete"
    )
    async def ctf_delete(self, interaction: discord.Interaction, name: str, year: int):
        """
        Delete a CTF and all its challenges.
        
        This command:
        1. Deletes the CTF folder in GitHub
        2. Deletes all claim branches
        3. Clears the database if it's the active CTF
        4. Updates the board
        
        Args:
            name: Name of the CTF
            year: Year of the CTF
        """
        # Check if user has the lead role
        if not await self._is_lead(interaction):
            return
        
        # Normalize CTF name
        name = name.lower().strip()
        
        # Log command
        logging_config.log_command(logger, "ctf_delete", interaction, name=name, year=year)
        
        # Get active CTF to check if we're deleting the active one
        active_name, active_year = await db.get_active_ctf()
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Format the CTF folder name
            ctf_folder = f"{name}-{year}"
            
            # Delete the CTF folder in GitHub
            folder_deleted = await github_utils.delete_path(ctf_folder)
            
            # Delete claim branches for this CTF
            branch_count = await github_utils.delete_claim_branches(name, year)
            
            # If this is the active CTF, clear it
            if active_name == name and active_year == year:
                await db.clear_active_ctf()
                await db.delete_all_tasks()
                await views.update_board(self.bot)
            
            # Build response message
            message = [f"✅ Deleted CTF: `{ctf_folder}`"]
            if folder_deleted:
                message.append("- GitHub folder deleted")
            if branch_count > 0:
                message.append(f"- {branch_count} claim branches deleted")
            if active_name == name and active_year == year:
                message.append("- Cleared as active CTF")
                message.append("- All tasks deleted from database")
            
            # Update the repo viewer
            await RepoViewerCommands.trigger_update()
            
            await interaction.followup.send(
                "\n".join(message),
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in ctf_delete: {e}")
            await interaction.followup.send(
                "⚠️ An error occurred while deleting the CTF.",
                ephemeral=True
            )
    
    @app_commands.command(name="ctf_list", description="List all CTFs in the GitHub repository")
    async def ctf_list(self, interaction: discord.Interaction):
        """
        List all CTFs in the GitHub repository.
        Shows active CTF and all available CTFs from the repository.
        """
        # Log command
        logging_config.log_command(logger, "ctf_list", interaction)
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Get active CTF
            active_name, active_year = await db.get_active_ctf()
            active_ctf = f"{active_name}-{active_year}" if active_name and active_year else None
            
            # Get all CTF directories from GitHub
            ctf_dirs = await github_utils.list_ctf_directories()
            
            # Create the embed
            embed = discord.Embed(
                title="📋 CTF List",
                description="List of all CTFs in the repository",
                color=discord.Color.blue()
            )
            
            # Add active CTF
            if active_ctf:
                embed.add_field(
                    name="🟢 Active CTF",
                    value=f"`{active_ctf}`",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Active CTF",
                    value="No active CTF",
                    inline=False
                )
            
            # Add all CTFs
            if ctf_dirs:
                # Sort by year (descending)
                ctf_dirs.sort(reverse=True)
                
                ctf_list = "\n".join([f"`{ctf}`" for ctf in ctf_dirs])
                embed.add_field(
                    name="Available CTFs",
                    value=ctf_list,
                    inline=False
                )
            else:
                embed.add_field(
                    name="Available CTFs",
                    value="No CTFs found in the repository",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error in ctf_list: {e}")
            await interaction.followup.send(
                "⚠️ An error occurred while listing CTFs.",
                ephemeral=True
            )
    
    @app_commands.command(name="help", description="Show available commands and usage")
    async def help_command(self, interaction: discord.Interaction):
        """Display help information about the bot's commands."""
        # Log command
        logging_config.log_command(logger, "help", interaction)
        
        # Create an embed with helpful information
        embed = discord.Embed(
            title="CTF Task-Tracker Bot - Help",
            description="This bot helps manage CTF challenges, tracking who's working on what, and organizing write-ups in a GitHub repository.",
            color=discord.Color.blue()
        )
        
        # Add CTF commands section
        embed.add_field(
            name="🏁 CTF Commands",
            value=(
                "`/ctf_add name year` - Start a new CTF session (sets repo to private, Lead only)\n"
                "`/ctf_done` - Mark the current CTF as finished (Lead only)\n"
                "`/ctf_publish` - Make the repository public when CTF is over (Lead only)\n"
                "`/ctf_clear name year` - Clear claim branches for a CTF (Lead only)\n"
                "`/ctf_delete name year` - Delete a CTF and all its challenges (Lead only)\n"
                "`/ctf_list` - List all CTFs in the repository"
            ),
            inline=False
        )
        
        # Add Challenge commands section
        embed.add_field(
            name="🧩 Challenge Commands",
            value=(
                "`/challenge_add category name` - Add a new challenge\n"
                "`/challenges_add challenges` - Add multiple challenges at once (format: 'category:name,category:name')\n"
                "`/challenge_delete id` - Delete a challenge (Manage Messages required)\n\n"
                "**Board Buttons**:\n"
                "- **Claim** - Claim a challenge (creates a branch and DMs instructions)\n"
                "- **Unclaim** - Release a claimed challenge\n"
                "- **Solved** - Mark as solved (creates SOLVED marker and DMs git commands)"
            ),
            inline=False
        )
        
        # Add Repository and Utility commands section
        embed.add_field(
            name="📂 Repository & Utility Commands",
            value=(
                "`/update_repo_view` - Manually update the repository structure display\n"
                "`/show_repo_structure` - Show the repository structure in current channel\n"
                "`/debug` - Show comprehensive bot and system information\n"
                "`/give_treat` - Give the bot a treat (just for fun)"
            ),
            inline=False
        )
        
        # Add Workflow section
        embed.add_field(
            name="💡 Typical Workflow",
            value=(
                "1. Team lead starts a CTF: `/ctf_add dam 2025` (repo set to private)\n"
                "2. Add challenges as they appear: `/challenge_add web login-portal`\n"
                "3. Team members claim tasks from the board\n"
                "4. When solved, click **Solved** and follow the git instructions\n"
                "5. After the CTF, run `/ctf_done` to lock it\n"
                "6. When ready to share, run `/ctf_publish` to make repository public"
            ),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="give_treat", description="Give a treat to the bot")
    async def give_treat(self, interaction: discord.Interaction):
        """Just a fun command to interact with the bot."""
        # Log command
        logging_config.log_command(logger, "give_treat", interaction)
        
        # List of possible responses
        responses = [
            "🍪 Yum! Thanks for the cookie! I'll work extra hard on tracking CTF challenges!",
            "🍩 A donut! Just what I needed for parsing all those GitHub repositories!",
            "🍕 Pizza! My favorite fuel for handling Discord slash commands!",
            "🍦 Ice cream! Cool, just like how I keep the team's CTF progress organized!",
            "🍫 Chocolate! Sweet, like the feeling of solving CTF challenges!",
            "🧁 A cupcake! That's a great reward for managing all those claim branches!",
            "🍎 An apple! Keeping this bot healthy and running smoothly!",
            "🥓 Bacon! The secret ingredient to successful CTF competitions!",
            "🍬 Candy! A sweet reward for all those Git merges I've helped with!"
        ]
        
        # Choose a random response
        import random
        response = random.choice(responses)
        
        # Create a fun embed
        embed = discord.Embed(
            title="Treat Received!",
            description=response,
            color=discord.Color.gold()
        )
        
        # Add a footer
        embed.set_footer(text="Thanks for the treat! Happy hacking!")
        
        await interaction.response.send_message(embed=embed, ephemeral=False)

async def setup(bot):
    await bot.add_cog(CTFCommands(bot)) 