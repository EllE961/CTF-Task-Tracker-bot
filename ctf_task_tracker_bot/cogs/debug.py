#!/usr/bin/env python3
import os
import sys
import logging
import platform
import asyncio
import time
import json
import traceback
from datetime import datetime
from typing import Optional, Dict, Any, List

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import db
import views
import logging_config

# Try to import psutil for memory usage stats
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

load_dotenv()
logger = logging.getLogger('bot.cogs.debug')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

class DebugCommands(commands.Cog):
    """Debug commands for bot administrators."""
    
    def __init__(self, bot):
        self.bot = bot
        self.startup_time = datetime.now()
    
    async def _is_admin(self, interaction: discord.Interaction) -> bool:
        """Check if the user has administrator permissions."""
        if not interaction.guild:
            await interaction.response.send_message(
                "⚠️ This command can only be used in a server.", 
                ephemeral=True
            )
            return False
            
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⚠️ You need administrator permissions to use this command.", 
                ephemeral=True
            )
            return False
            
        return True
    
    async def _check_command_access(self, interaction: discord.Interaction, command_name: str) -> bool:
        """
        Check access permissions for debug commands.
        The main '/debug' command is available to everyone, but other debug_* commands require admin.
        """
        # The main /debug command is available to everyone
        if command_name == "debug":
            return True
            
        # Other debug commands require admin privileges
        return await self._is_admin(interaction)
    
    @app_commands.command(name="debug_status", description="Show bot status and diagnostics")
    async def debug_status(self, interaction: discord.Interaction):
        """Display detailed bot status information for debugging."""
        logging_config.log_command(logger, "debug_status", interaction)
        
        # Check if user is an admin
        if not await self._check_command_access(interaction, "debug_status"):
            return
        
        # Gather system information
        uptime = datetime.now() - self.startup_time
        uptime_str = str(uptime).split('.')[0]  # Remove microseconds
        
        # Get current active CTF
        ctf_name, ctf_year = await db.get_active_ctf()
        active_ctf = f"{ctf_name}-{ctf_year}" if ctf_name and ctf_year else "None"
        
        # Count tasks
        tasks = await db.get_all_tasks()
        task_count = len(tasks) if tasks else 0
        
        # Create an embed with detailed information
        embed = discord.Embed(
            title="🔍 Bot Status & Diagnostics",
            description="Detailed information about the bot's current state",
            color=discord.Color.blue()
        )
        
        # Add system information
        embed.add_field(
            name="System",
            value=(
                f"**Discord.py:** {discord.__version__}\n"
                f"**Python:** {platform.python_version()}\n"
                f"**OS:** {platform.system()} {platform.release()}\n"
                f"**Uptime:** {uptime_str}\n"
                f"**Log Level:** {LOG_LEVEL}"
            ),
            inline=False
        )
        
        # Add bot information
        embed.add_field(
            name="Bot",
            value=(
                f"**Name:** {self.bot.user.name}\n"
                f"**ID:** {self.bot.user.id}\n"
                f"**Guilds:** {len(self.bot.guilds)}\n"
                f"**Active CTF:** {active_ctf}\n"
                f"**Task Count:** {task_count}"
            ),
            inline=False
        )
        
        # Add database information
        try:
            db_path = os.path.abspath(db.DB_PATH)
            db_size = os.path.getsize(db_path) / 1024  # Size in KB
            
            embed.add_field(
                name="Database",
                value=(
                    f"**Path:** {db_path}\n"
                    f"**Size:** {db_size:.2f} KB"
                ),
                inline=False
            )
        except Exception as e:
            embed.add_field(
                name="Database",
                value=f"Error getting DB info: {e}",
                inline=False
            )
        
        # Send the embed
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @app_commands.command(name="debug_log", description="Show recent log entries")
    @app_commands.describe(
        lines="Number of lines to show (default: 10, max: 50)",
        level="Log level to filter by (default: all)"
    )
    async def debug_log(
        self, 
        interaction: discord.Interaction, 
        lines: Optional[int] = 10,
        level: Optional[str] = None
    ):
        """Show recent log entries for debugging."""
        logging_config.log_command(logger, "debug_log", interaction, lines=lines, level=level)
        
        # Check if user is an admin
        if not await self._check_command_access(interaction, "debug_log"):
            return
        
        # Validate and limit lines
        if lines <= 0:
            lines = 10
        if lines > 50:
            lines = 50
        
        # Defer response to allow time for log retrieval
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get log file path
            log_file = os.path.join('logs', 'bot.log')
            
            # Check if log file exists
            if not os.path.exists(log_file):
                await interaction.followup.send(
                    "⚠️ Log file not found.",
                    ephemeral=True
                )
                return
            
            # Read the log file
            with open(log_file, 'r', encoding='utf-8') as f:
                # Read all lines and then take the last N lines
                all_logs = f.readlines()
                
            # Filter by level if specified
            if level and level.upper() in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
                filtered_logs = [line for line in all_logs if f"[{level.upper()}]" in line]
                log_lines = filtered_logs[-lines:]
            else:
                log_lines = all_logs[-lines:]
            
            # Format log content for display
            if log_lines:
                log_content = "```\n" + "".join(log_lines) + "\n```"
                
                # Check if content is too long for Discord
                if len(log_content) > 2000:
                    log_content = "```\n" + "".join(log_lines[-20:]) + "\n```"
                    await interaction.followup.send(
                        f"⚠️ Log output too large, showing last 20 lines:\n{log_content}",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        f"📋 Last {len(log_lines)} log entries:\n{log_content}",
                        ephemeral=True
                    )
            else:
                await interaction.followup.send(
                    "ℹ️ No log entries found with the specified criteria.",
                    ephemeral=True
                )
        
        except Exception as e:
            logger.error(f"Error retrieving logs: {e}")
            await interaction.followup.send(
                f"⚠️ Error retrieving logs: {e}",
                ephemeral=True
            )
    
    @app_commands.command(name="debug_task", description="Show detailed information about a task")
    @app_commands.describe(
        task_id="ID of the task to inspect"
    )
    async def debug_task(self, interaction: discord.Interaction, task_id: int):
        """Show detailed information about a task for debugging."""
        logging_config.log_command(logger, "debug_task", interaction, task_id=task_id)
        
        # Check if user is an admin
        if not await self._check_command_access(interaction, "debug_task"):
            return
        
        # Defer response
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Get task details
            task = await db.run(
                "SELECT id, category, name, claimed_by, solved FROM tasks WHERE id = ?",
                task_id,
                fetchone=True
            )
            
            if not task:
                await interaction.followup.send(
                    f"⚠️ Task #{task_id} not found in the database.",
                    ephemeral=True
                )
                return
            
            # Unpack task data
            id, category, name, claimed_by, solved = task
            
            # Get active CTF
            ctf_name, ctf_year = await db.get_active_ctf()
            
            # Create embed
            embed = discord.Embed(
                title=f"🔍 Task #{id} Debug Info",
                description=f"Detailed information about task: {category}/{name}",
                color=discord.Color.blue()
            )
            
            # Add basic task info
            embed.add_field(
                name="Basic Info",
                value=(
                    f"**ID:** {id}\n"
                    f"**Category:** {category}\n"
                    f"**Name:** {name}\n"
                    f"**Solved:** {'Yes' if solved else 'No'}"
                ),
                inline=False
            )
            
            # Add claim info
            if claimed_by:
                user = self.bot.get_user(claimed_by)
                username = f"{user.name}#{user.discriminator}" if user else f"Unknown User (ID: {claimed_by})"
                
                embed.add_field(
                    name="Claim Info",
                    value=(
                        f"**Claimed By:** {username}\n"
                        f"**User ID:** {claimed_by}"
                    ),
                    inline=False
                )
            else:
                embed.add_field(
                    name="Claim Info",
                    value="Not claimed by any user",
                    inline=False
                )
            
            # Add GitHub info if CTF is active
            if ctf_name and ctf_year:
                ctf_folder = f"{ctf_name.lower()}-{ctf_year}"
                
                embed.add_field(
                    name="GitHub Info",
                    value=(
                        f"**CTF Folder:** {ctf_folder}\n"
                        f"**Task Path:** {ctf_folder}/{category}/{name}/\n"
                        f"**Question Path:** {ctf_folder}/{category}/{name}/question/\n"
                        f"**Answer Path:** {ctf_folder}/{category}/{name}/answer/"
                    ),
                    inline=False
                )
                
                if claimed_by:
                    # Calculate branch name
                    user = self.bot.get_user(claimed_by)
                    if user:
                        safe_username = ''.join(c for c in user.name if c.isalnum() or c == '_' or c == '-')
                        safe_challenge = ''.join(c for c in name if c.isalnum() or c == '_' or c == '-')
                        branch_name = f"claim-{safe_username}-{safe_challenge}"
                        
                        embed.add_field(
                            name="Branch Info",
                            value=f"**Claim Branch:** {branch_name}",
                            inline=False
                        )
            
            # Add raw DB row
            embed.add_field(
                name="Raw Database Row",
                value=f"```\n{task}\n```",
                inline=False
            )
            
            # Send the embed
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error debugging task: {e}")
            await interaction.followup.send(
                f"⚠️ Error debugging task: {e}",
                ephemeral=True
            )
    
    @app_commands.command(name="debug_refresh_board", description="Force refresh the board message")
    async def debug_refresh_board(self, interaction: discord.Interaction):
        """Force refresh the board message for debugging."""
        logging_config.log_command(logger, "debug_refresh_board", interaction)
        
        # Check if user is an admin
        if not await self._check_command_access(interaction, "debug_refresh_board"):
            return
        
        # Defer response
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Update the board
            success = await views.update_board(self.bot)
            
            if success:
                await interaction.followup.send(
                    "✅ Board message refreshed successfully.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "⚠️ Failed to refresh board message. Check logs for details.",
                    ephemeral=True
                )
        except Exception as e:
            logger.error(f"Error refreshing board: {e}")
            await interaction.followup.send(
                f"⚠️ Error refreshing board: {e}",
                ephemeral=True
            )
    
    @app_commands.command(name="debug", description="Show comprehensive debug information and statistics")
    async def debug(self, interaction: discord.Interaction):
        """Show comprehensive debug information about the bot, system, network, and database."""
        logging_config.log_command(logger, "debug", interaction)
        
        # Check access - this should always pass for the /debug command
        if not await self._check_command_access(interaction, "debug"):
            return
            
        # Defer response to allow time to gather all information
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        try:
            # Start timing
            start_time = time.time()
            
            # Measure Discord API latency
            latency_ms = round(self.bot.latency * 1000)
            
            # Get uptime
            uptime = datetime.now() - self.startup_time
            uptime_str = str(uptime).split('.')[0]  # Remove microseconds
            
            # Get active CTF
            ctf_name, ctf_year = await db.get_active_ctf()
            active_ctf = f"{ctf_name}-{ctf_year}" if ctf_name and ctf_year else "None"
            
            # Get database stats
            db_stats = await db.get_db_stats()
            
            # Get memory usage (this is an approximation)
            if HAS_PSUTIL:
                try:
                    process = psutil.Process(os.getpid())
                    memory_usage = f"{process.memory_info().rss / 1024 / 1024:.2f} MB"
                except Exception as e:
                    memory_usage = f"Error: {str(e)}"
            else:
                memory_usage = "N/A (psutil not installed)"
            
            # Create embed
            embed = discord.Embed(
                title="🛠️ Debug Information",
                description="Comprehensive system status and diagnostics",
                color=discord.Color.gold()
            )
            
            # Bot information
            embed.add_field(
                name="🤖 Bot Status",
                value=(
                    f"**Name:** {self.bot.user.name}\n"
                    f"**ID:** {self.bot.user.id}\n"
                    f"**Uptime:** {uptime_str}\n"
                    f"**Active CTF:** {active_ctf}\n"
                    f"**Guilds:** {len(self.bot.guilds)}\n"
                    f"**User Count:** {sum(g.member_count for g in self.bot.guilds)}\n"
                    f"**Latency:** {latency_ms}ms"
                ),
                inline=False
            )
            
            # System information
            embed.add_field(
                name="💻 System Information",
                value=(
                    f"**OS:** {platform.system()} {platform.release()}\n"
                    f"**Version:** {platform.version()}\n"
                    f"**Architecture:** {platform.machine()}\n"
                    f"**Python:** {platform.python_version()}\n"
                    f"**Discord.py:** {discord.__version__}\n"
                    f"**Memory Usage:** {memory_usage}\n"
                    f"**Log Level:** {LOG_LEVEL}"
                ),
                inline=False
            )
            
            # Current directory and files
            try:
                current_dir = os.getcwd()
                dir_size = sum(os.path.getsize(os.path.join(current_dir, f)) for f in os.listdir(current_dir) if os.path.isfile(os.path.join(current_dir, f)))
                dir_size_mb = dir_size / (1024 * 1024)
                file_count = len([f for f in os.listdir(current_dir) if os.path.isfile(os.path.join(current_dir, f))])
                
                embed.add_field(
                    name="📂 Working Directory",
                    value=(
                        f"**Path:** {current_dir}\n"
                        f"**Files:** {file_count}\n"
                        f"**Size:** {dir_size_mb:.2f} MB"
                    ),
                    inline=False
                )
            except Exception as e:
                embed.add_field(
                    name="📂 Working Directory",
                    value=f"Error: {str(e)}",
                    inline=False
                )
            
            # Database information
            tasks_count = db_stats.get('tasks_count', 'Unknown')
            
            embed.add_field(
                name="🗄️ Database",
                value=(
                    f"**Path:** {os.path.abspath(db.DB_PATH)}\n"
                    f"**Size:** {os.path.getsize(db.DB_PATH) / 1024:.2f} KB\n"
                    f"**Tasks:** {tasks_count}\n"
                    f"**Queries Executed:** {db_stats.get('queries_executed', 'Unknown')}\n"
                    f"**Longest Query:** {db_stats.get('longest_query', {}).get('time', 0):.6f}s\n"
                ),
                inline=False
            )
            
            # Network information
            try:
                hostname = platform.node()
                embed.add_field(
                    name="🌐 Network",
                    value=(
                        f"**Hostname:** {hostname}\n"
                        f"**Bot WebSocket Ping:** {latency_ms}ms\n"
                        f"**Processing Time:** {(time.time() - start_time) * 1000:.2f}ms\n"
                    ),
                    inline=False
                )
            except Exception as e:
                embed.add_field(
                    name="🌐 Network",
                    value=f"Error retrieving network info: {str(e)}",
                    inline=False
                )
            
            # Send the embed
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error in debug command: {e}")
            await interaction.followup.send(
                f"⚠️ Error collecting debug information: {str(e)}\n\n{traceback.format_exc()}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(DebugCommands(bot)) 