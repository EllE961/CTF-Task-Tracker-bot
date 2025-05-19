#!/usr/bin/env python3
import os
import logging
import asyncio
from typing import Optional, Tuple, List

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
logger = logging.getLogger('bot.cogs.challenge')

class ChallengeCommands(commands.Cog):
    """Commands for managing CTF challenges."""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="challenge_add", description="Add a new challenge to the active CTF")
    @app_commands.describe(
        category="Challenge category (e.g., 'web', 'pwn', 'crypto')",
        name="Name of the challenge"
    )
    async def challenge_add(self, interaction: discord.Interaction, category: str, name: str):
        """
        Add a new challenge to the active CTF.
        
        This command:
        1. Checks if there's an active CTF
        2. Creates a scaffold in GitHub
        3. Adds the challenge to the database
        4. Updates the board
        
        Args:
            category: Challenge category (e.g., 'web', 'pwn')
            name: Name of the challenge
        """
        # Log command
        logging_config.log_command(logger, "challenge_add", interaction, category=category, name=name)
        
        # Check if there's an active CTF
        ctf_name, ctf_year = await db.get_active_ctf()
        if not ctf_name or not ctf_year:
            try:
                await interaction.response.send_message(
                    "⚠️ No active CTF. Use `/ctf_add` to start one first.",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning(f"Interaction expired for challenge_add - no active CTF")
            return
        
        # Clean inputs
        category = category.lower().strip()
        name = name.strip()
        
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.errors.NotFound:
            logger.warning(f"Interaction expired when deferring challenge_add")
            return
        
        try:
            # Create the challenge scaffold in GitHub
            scaffold_created = await github_utils.create_scaffold(
                ctf_name, ctf_year, category, name
            )
            
            if not scaffold_created:
                try:
                    await interaction.followup.send(
                        "⚠️ Failed to create challenge scaffold in GitHub.",
                        ephemeral=True
                    )
                except discord.errors.NotFound:
                    logger.warning("Interaction expired when sending scaffold error for challenge_add")
                return
            
            # Add the challenge to the database
            task_id = await db.add_task(category, name)
            
            # Update the board
            await views.update_board(self.bot)
            
            # Update the repo viewer
            await RepoViewerCommands.trigger_update()
            
            # Success message
            try:
                await interaction.followup.send(
                    f"✅ Added challenge: {category}/{name} (#{task_id})\n"
                    f"GitHub scaffold created in `{ctf_name}-{ctf_year}/{category}/{name}/`",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning("Interaction expired when sending success message for challenge_add")
            
        except Exception as e:
            logger.error(f"Error in challenge_add: {e}")
            try:
                await interaction.followup.send(
                    "⚠️ An error occurred while adding the challenge.",
                    ephemeral=True
                )
            except discord.errors.NotFound:
                logger.warning("Interaction expired when sending error for challenge_add")
    
    @app_commands.command(name="challenge_delete", description="Delete a challenge")
    @app_commands.describe(
        id="ID of the challenge to delete (shown as #123 on the board)"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def challenge_delete(self, interaction: discord.Interaction, id: int):
        """
        Delete a challenge.
        
        This command:
        1. Deletes the challenge from the database
        2. Deletes the challenge folder from GitHub
        3. Updates the board
        
        Args:
            id: ID of the challenge to delete
        """
        # Log command
        logging_config.log_command(logger, "challenge_delete", interaction, id=id)
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Get the challenge details first
            challenge = await db.run(
                "SELECT category, name FROM tasks WHERE id = ?",
                id,
                fetchone=True
            )
            
            if not challenge:
                await interaction.followup.send(
                    f"⚠️ Challenge #{id} not found.",
                    ephemeral=True
                )
                return
            
            category, name = challenge
            
            # Get active CTF for GitHub path
            ctf_name, ctf_year = await db.get_active_ctf()
            
            # Delete the challenge from database
            await db.delete_task(id)
            
            # Try to delete GitHub folder if CTF is active
            github_deleted = False
            if ctf_name and ctf_year:
                # Attempt to delete the GitHub folder
                folder_path = f"{ctf_name.lower()}-{ctf_year}/{category}/{name}"
                github_deleted = await github_utils.delete_path(folder_path)
            
            # Update the board
            await views.update_board(self.bot)
            
            # Success message
            message = [f"✅ Deleted challenge #{id}: {category}/{name}"]
            if github_deleted:
                message.append(f"- GitHub folder deleted")
                
            await interaction.followup.send(
                "\n".join(message),
                ephemeral=True
            )
            
        except discord.app_commands.errors.MissingPermissions:
            await interaction.followup.send(
                "⚠️ You need 'Manage Messages' permission to delete challenges.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in challenge_delete: {e}")
            await interaction.followup.send(
                "⚠️ An error occurred while deleting the challenge.",
                ephemeral=True
            )
    
    @app_commands.command(name="challenges_add", description="Add multiple challenges at once")
    @app_commands.describe(
        challenges="Format: 'category:name,category:name,...' (e.g., 'web:login,pwn:shellcode,crypto:rsa')"
    )
    async def challenges_add(self, interaction: discord.Interaction, challenges: str):
        """
        Add multiple challenges at once to the active CTF.
        
        Args:
            challenges: Comma-separated list of category:name pairs
        """
        # Log command
        logging_config.log_command(logger, "challenges_add", interaction, challenges=challenges)
        
        # Check if there's an active CTF
        ctf_name, ctf_year = await db.get_active_ctf()
        if not ctf_name or not ctf_year:
            await interaction.response.send_message(
                "⚠️ No active CTF. Use `/ctf_add` to start one first.",
                ephemeral=True
            )
            return
        
        # Parse the challenges string
        challenge_list = []
        for challenge_pair in challenges.split(","):
            challenge_pair = challenge_pair.strip()
            if not challenge_pair:
                continue
                
            parts = challenge_pair.split(":")
            if len(parts) != 2:
                await interaction.response.send_message(
                    f"⚠️ Invalid challenge format: '{challenge_pair}'. Use 'category:name'.",
                    ephemeral=True
                )
                return
                
            category, name = parts
            category = category.lower().strip()
            name = name.strip()
            
            if not category or not name:
                await interaction.response.send_message(
                    f"⚠️ Invalid challenge: '{challenge_pair}'. Both category and name must be provided.",
                    ephemeral=True
                )
                return
                
            challenge_list.append((category, name))
        
        if not challenge_list:
            await interaction.response.send_message(
                "⚠️ No valid challenges provided.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        # Format the CTF folder name
        ctf_folder = f"{ctf_name.lower()}-{ctf_year}"
        
        # Process each challenge
        results = []
        success_count = 0
        
        for category, name in challenge_list:
            try:
                # Create the challenge scaffold in GitHub
                scaffold_created = await github_utils.create_scaffold(
                    ctf_name, ctf_year, category, name
                )
                
                if not scaffold_created:
                    results.append(f"❌ {category}/{name} - Failed to create GitHub scaffold")
                    continue
                
                # Add the challenge to the database
                task_id = await db.add_task(category, name)
                
                results.append(f"✅ #{task_id} {category}/{name} - Added successfully")
                success_count += 1
                
            except Exception as e:
                logger.error(f"Error adding challenge {category}/{name}: {e}")
                results.append(f"❌ {category}/{name} - Error: {str(e)[:50]}")
        
        # Update the board
        await views.update_board(self.bot)
        
        # Update the repo viewer
        await RepoViewerCommands.trigger_update()
        
        # Build response message
        if success_count > 0:
            response = [f"Added {success_count}/{len(challenge_list)} challenges to `{ctf_folder}/`:"]
        else:
            response = ["⚠️ Failed to add any challenges."]
            
        response.extend(results)
        
        await interaction.followup.send(
            "\n".join(response),
            ephemeral=True
        )
    
    async def handle_claim(self, interaction: discord.Interaction, task_id: int):
        """
        Handle the Claim button press for a task.
        
        Args:
            interaction: The Discord interaction
            task_id: ID of the task being claimed
        """
        user_id = interaction.user.id
        
        # Log button handler
        logging_config.log_button(logger, "claim", interaction, task_id)
        
        # Check if the user already has a claimed unsolved task
        row = await db.run(
            "SELECT id FROM tasks WHERE claimed_by = ? AND solved = 0",
            user_id,
            fetchone=True
        )
        
        if row:
            # User already has a claimed task
            claimed_id = row[0]
            await interaction.response.send_message(
                f"⚠️ You already have challenge #{claimed_id} claimed. "
                f"Please solve or unclaim it first.",
                ephemeral=True
            )
            return
        
        # Get task details
        task = await db.run(
            "SELECT category, name, claimed_by, solved FROM tasks WHERE id = ?",
            task_id,
            fetchone=True
        )
        
        if not task:
            await interaction.response.send_message(
                f"⚠️ Challenge #{task_id} not found.",
                ephemeral=True
            )
            return
        
        category, name, claimed_by, solved = task
        
        if solved:
            await interaction.response.send_message(
                f"⚠️ Challenge #{task_id} is already solved.",
                ephemeral=True
            )
            return
        
        if claimed_by is not None:
            # Task already claimed by someone
            if claimed_by == user_id:
                await interaction.response.send_message(
                    f"ℹ️ You've already claimed challenge #{task_id}.",
                    ephemeral=True
                )
            else:
                claimer = self.bot.get_user(claimed_by)
                if claimer:
                    await interaction.response.send_message(
                        f"⚠️ Challenge #{task_id} is already claimed by <@{claimed_by}>.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"⚠️ Challenge #{task_id} is already claimed by User {claimed_by}.",
                        ephemeral=True
                    )
            return
        
        # Get active CTF
        ctf_name, ctf_year = await db.get_active_ctf()
        if not ctf_name or not ctf_year:
            await interaction.response.send_message(
                "⚠️ Cannot claim challenge - no active CTF.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Create a claim branch in GitHub
            branch_name = await github_utils.create_claim_branch(
                ctf_name, ctf_year, interaction.user.name, name
            )
            
            if not branch_name:
                await interaction.followup.send(
                    "⚠️ Failed to create claim branch in GitHub.",
                    ephemeral=True
                )
                return
            
            # Update task in database
            await db.claim_task(task_id, user_id)
            
            # Update the board
            await views.update_board(self.bot)
            
            # Update the repo viewer
            await RepoViewerCommands.trigger_update()
            
            # Format the CTF folder path
            ctf_folder = f"{ctf_name.lower()}-{ctf_year}"
            
            # Send DM with git instructions
            try:
                # Build the instructions
                dm_text = (
                    f"🎯 You've claimed **{category}/{name}** (#{task_id})!\n\n"
                    f"To work on this challenge:\n"
                    f"```bash\n"
                    f"# First make sure you're on main and it's clean\n"
                    f"git switch main\n"
                    f"git pull\n\n"
                    f"# Create/switch to claim branch\n"
                    f"git switch -c {branch_name} origin/{branch_name}\n\n"
                    f"# If you get errors about the branch not existing:\n"
                    f"# git fetch\n"
                    f"# git switch --track origin/{branch_name}\n"
                    f"```\n\n"
                    f"The scaffolding has been created at:\n"
                    f"`{ctf_folder}/{category}/{name}/`\n\n"
                    f"Add your files to the `question/` folder and prepare your solution in `answer/`.\n\n"
                    f"⚠️ **If you previously unclaimed this challenge:** You might need to resolve conflicts.\n"
                    f"```bash\n"
                    f"# If you get merge conflicts:\n"
                    f"git status  # See which files have conflicts\n"
                    f"# Resolve conflicts in your editor\n"
                    f"git add {ctf_folder}/{category}/{name}/  # Add the resolved files\n"
                    f"git commit -m \"Resolve conflicts for {category}/{name}\"\n"
                    f"```"
                )
                
                # Send DM
                await interaction.user.send(dm_text)
                
                # Success message in channel
                await interaction.followup.send(
                    f"✅ Claimed challenge #{task_id}.",
                    ephemeral=True
                )
                
            except discord.Forbidden:
                # Cannot DM - send instructions in channel instead
                await interaction.followup.send(
                    f"✅ Claimed challenge #{task_id}.\n\n"
                    f"I couldn't DM you, so here are your instructions:\n"
                    f"```bash\n"
                    f"# First make sure you're on main and it's clean\n"
                    f"git switch main\n"
                    f"git pull\n\n"
                    f"# Create/switch to claim branch\n"
                    f"git switch -c {branch_name} origin/{branch_name}\n\n"
                    f"# If you get errors about the branch not existing:\n"
                    f"# git fetch\n"
                    f"# git switch --track origin/{branch_name}\n"
                    f"```\n"
                    f"Work in: `{ctf_folder}/{category}/{name}/`",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error in handle_claim: {e}")
            await interaction.followup.send(
                "⚠️ An error occurred while claiming the challenge.",
                ephemeral=True
            )
    
    async def handle_unclaim(self, interaction: discord.Interaction, task_id: int):
        """
        Handle the Unclaim button press for a task.
        
        Args:
            interaction: The Discord interaction
            task_id: ID of the task being unclaimed
        """
        user_id = interaction.user.id
        
        # Log button handler
        logging_config.log_button(logger, "unclaim", interaction, task_id)
        
        # Get task details
        task = await db.run(
            "SELECT claimed_by, solved FROM tasks WHERE id = ?",
            task_id,
            fetchone=True
        )
        
        if not task:
            await interaction.response.send_message(
                f"⚠️ Challenge #{task_id} not found.",
                ephemeral=True
            )
            return
        
        claimed_by, solved = task
        
        if solved:
            await interaction.response.send_message(
                f"⚠️ Challenge #{task_id} is already solved and cannot be unclaimed.",
                ephemeral=True
            )
            return
        
        if claimed_by != user_id:
            # Task not claimed by this user
            if claimed_by is None:
                await interaction.response.send_message(
                    f"ℹ️ Challenge #{task_id} is not currently claimed.",
                    ephemeral=True
                )
            else:
                claimer = self.bot.get_user(claimed_by)
                if claimer:
                    await interaction.response.send_message(
                        f"⚠️ Challenge #{task_id} is claimed by <@{claimed_by}>, not you.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"⚠️ Challenge #{task_id} is claimed by User {claimed_by}, not you.",
                        ephemeral=True
                    )
            return
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Unclaim the task
            await db.unclaim_task(task_id)
            
            # Update the board
            await views.update_board(self.bot)
            
            # Update the repo viewer
            await RepoViewerCommands.trigger_update()
            
            # Success message
            await interaction.followup.send(
                f"✅ Unclaimed challenge #{task_id}.",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error in handle_unclaim: {e}")
            await interaction.followup.send(
                "⚠️ An error occurred while unclaiming the challenge.",
                ephemeral=True
            )
    
    async def handle_solved(self, interaction: discord.Interaction, task_id: int):
        """
        Handle the Solved button press for a task.
        
        Args:
            interaction: The Discord interaction
            task_id: ID of the task being marked as solved
        """
        user_id = interaction.user.id
        
        # Log button handler
        logging_config.log_button(logger, "solved", interaction, task_id)
        
        # Get task details
        task = await db.run(
            "SELECT category, name, claimed_by, solved FROM tasks WHERE id = ?",
            task_id,
            fetchone=True
        )
        
        if not task:
            await interaction.response.send_message(
                f"⚠️ Challenge #{task_id} not found.",
                ephemeral=True
            )
            return
        
        category, name, claimed_by, solved = task
        
        if solved:
            await interaction.response.send_message(
                f"ℹ️ Challenge #{task_id} is already marked as solved.",
                ephemeral=True
            )
            return
        
        if claimed_by != user_id:
            # Task not claimed by this user
            if claimed_by is None:
                await interaction.response.send_message(
                    f"⚠️ You need to claim challenge #{task_id} before marking it as solved.",
                    ephemeral=True
                )
            else:
                claimer = self.bot.get_user(claimed_by)
                if claimer:
                    await interaction.response.send_message(
                        f"⚠️ Challenge #{task_id} is claimed by <@{claimed_by}>, not you.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"⚠️ Challenge #{task_id} is claimed by User {claimed_by}, not you.",
                        ephemeral=True
                    )
            return
        
        # Get active CTF
        ctf_name, ctf_year = await db.get_active_ctf()
        if not ctf_name or not ctf_year:
            await interaction.response.send_message(
                "⚠️ Cannot mark as solved - no active CTF.",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Mark as solved in GitHub by creating empty SOLVED file
            solved_marked = await github_utils.mark_challenge_solved(
                ctf_name, ctf_year, category, name
            )
            
            if not solved_marked:
                await interaction.followup.send(
                    "⚠️ Failed to mark as solved in GitHub.",
                    ephemeral=True
                )
                return
            
            # Update task in database
            await db.mark_solved(task_id)
            
            # Update the board
            await views.update_board(self.bot)
            
            # Update the repo viewer
            await RepoViewerCommands.trigger_update()
            
            # Format the CTF folder path
            ctf_folder = f"{ctf_name.lower()}-{ctf_year}"
            
            # Get branch name (reconstruct it)
            safe_username = ''.join(c for c in interaction.user.name if c.isalnum() or c == '_' or c == '-')
            safe_challenge = ''.join(c for c in name if c.isalnum() or c == '_' or c == '-')
            branch_name = f"claim-{safe_username}-{safe_challenge}"
            
            # Send DM with git instructions
            try:
                # Build the instructions
                dm_text = (
                    f"🎉 You've solved **{category}/{name}** (#{task_id})!\n\n"
                    f"To push your solution and merge it:\n"
                    f"```bash\n"
                    f"# 1. Make sure all your changes are committed\n"
                    f"git status  # Check what files need to be added\n"
                    f"git add {ctf_folder}/{category}/{name}/\n"
                    f"git commit -m \"Solved {category}/{name}\"\n\n"
                    
                    f"# 2. Push your solution\n"
                    f"git push -u origin {branch_name}\n\n"
                    
                    f"# 3. Merge to main (automated)\n"
                    f"git switch main\n"
                    f"git pull  # Get latest changes\n"
                    f"git merge --no-ff {branch_name} -m \"Merge solution for {category}/{name}\"\n"
                    f"git push\n"
                    f"```\n\n"
                    
                    f"🔧 **If you encounter merge conflicts:**\n"
                    f"```bash\n"
                    f"# 1. Check which files have conflicts\n"
                    f"git status\n\n"
                    
                    f"# 2. Open each conflicted file and resolve the conflicts\n"
                    f"#    Look for markers like <<<<<<< and ======= and >>>>>>>>\n\n"
                    
                    f"# 3. After fixing ALL conflicts\n"
                    f"git add {ctf_folder}/{category}/{name}/\n"
                    f"git commit -m \"Resolve merge conflicts for {category}/{name}\"\n"
                    f"git push\n"
                    f"```\n\n"

                    f"🧹 **Cleanup (optional):**\n"
                    f"```bash\n"
                    f"# Delete the local branch after successful merge\n"
                    f"git branch -d {branch_name}\n"
                    f"```\n\n"
                    
                    f"This will preserve your work and make it accessible in the main branch."
                )
                
                # Send DM
                await interaction.user.send(dm_text)
                
                # Success message in channel
                await interaction.followup.send(
                    f"✅ Marked challenge #{task_id} as solved!",
                    ephemeral=True
                )
                
            except discord.Forbidden:
                # Cannot DM - send instructions in channel instead
                await interaction.followup.send(
                    f"✅ Marked challenge #{task_id} as solved!\n\n"
                    f"I couldn't DM you, so here are your instructions:\n"
                    f"```bash\n"
                    f"# 1. Make sure all your changes are committed\n"
                    f"git status  # Check what files need to be added\n"
                    f"git add {ctf_folder}/{category}/{name}/\n"
                    f"git commit -m \"Solved {category}/{name}\"\n\n"
                    
                    f"# 2. Push your solution\n"
                    f"git push -u origin {branch_name}\n\n"
                    
                    f"# 3. Merge to main (automated)\n"
                    f"git switch main\n"
                    f"git pull  # Get latest changes\n"
                    f"git merge --no-ff {branch_name} -m \"Merge solution for {category}/{name}\"\n"
                    f"git push\n"
                    f"```\n\n"
                    
                    f"See DM instructions for handling conflicts and cleanup.",
                    ephemeral=True
                )
                
        except Exception as e:
            logger.error(f"Error in handle_solved: {e}")
            await interaction.followup.send(
                "⚠️ An error occurred while marking the challenge as solved.",
                ephemeral=True
            )
    
    @challenge_delete.error
    async def challenge_delete_error(self, interaction: discord.Interaction, error):
        """Handle errors in the challenge_delete command."""
        if isinstance(error, app_commands.errors.MissingPermissions):
            await interaction.response.send_message(
                "⚠️ You need 'Manage Messages' permission to delete challenges.",
                ephemeral=True
            )
        else:
            logger.error(f"Unhandled error in challenge_delete: {error}")
            await interaction.response.send_message(
                "⚠️ An error occurred while executing that command.",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(ChallengeCommands(bot))
