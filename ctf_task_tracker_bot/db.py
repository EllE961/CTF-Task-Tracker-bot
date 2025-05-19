#!/usr/bin/env python3
"""
Database Module for CTF Task-Tracker Bot

This module provides an async SQLite database interface for the CTF Task-Tracker bot.
It handles all database operations including:
- Challenge/task tracking (add, claim, solve, delete)
- Active CTF management
- Board message tracking
- Database statistics and performance monitoring

Database Schema:
- tasks: Tracks challenges, their state, and who claimed them
  - id: Auto-incrementing primary key
  - category: Challenge category (e.g., web, pwn, crypto)
  - name: Challenge name
  - claimed_by: Discord user ID of claimer (NULL if unclaimed)
  - solved: Boolean flag (0 = unsolved, 1 = solved)

- active_ctf: Stores the currently active CTF
  - name: CTF name
  - year: CTF year

- board_msg: Tracks the message ID for the board in each channel
  - channel_id: Discord channel ID
  - message_id: Discord message ID of the board

- db_stats: Statistics for monitoring and debugging
  - queries_executed: Running count of queries
  - last_query_timestamp: Timestamp of the last query

All database operations are protected by a global lock to prevent concurrent
access issues, and each operation is logged for debugging purposes.
"""
import os
import logging
import asyncio
import aiosqlite
import traceback
import time
from pathlib import Path

# Configure logger
logger = logging.getLogger('bot.db')

# Database file path
DB_PATH = 'ctf_tasks.db'

# Global mutex for database operations
_db_lock = asyncio.Lock()

# Statistics
_db_stats = {
    "queries_executed": 0,
    "last_query_time": 0,
    "total_execution_time": 0,
    "longest_query": {
        "sql": "",
        "time": 0,
        "params": None
    }
}

async def init():
    """Initialize the database tables if they don't exist."""
    logger.info(f"Initializing database at {os.path.abspath(DB_PATH)}")
    
    start_time = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        # Create tasks table
        logger.debug("Creating tasks table if it doesn't exist")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                claimed_by INTEGER DEFAULT NULL,
                solved INTEGER DEFAULT 0
            )
        ''')
        
        # Create active_ctf table
        logger.debug("Creating active_ctf table if it doesn't exist")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS active_ctf (
                name TEXT,
                year INTEGER
            )
        ''')
        
        # Create board_msg table
        logger.debug("Creating board_msg table if it doesn't exist")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS board_msg (
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            )
        ''')
        
        # Create stats table for tracking database operations
        logger.debug("Creating db_stats table if it doesn't exist")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS db_stats (
                queries_executed INTEGER DEFAULT 0,
                last_query_timestamp TEXT
            )
        ''')
        
        # Initialize stats if not present
        stats_row = await db.execute("SELECT COUNT(*) FROM db_stats")
        count = await stats_row.fetchone()
        if count[0] == 0:
            logger.debug("Initializing db_stats table")
            await db.execute(
                "INSERT INTO db_stats (queries_executed, last_query_timestamp) VALUES (0, datetime('now'))"
            )
        
        await db.commit()
    
    init_time = time.time() - start_time
    logger.info(f"Database initialized in {init_time:.6f} seconds")

async def run(sql, *params, fetchone=False, fetchall=False):
    """
    Execute an SQL statement with parameters and optional fetch operations.
    
    Args:
        sql: SQL statement to execute
        *params: Parameters to bind to the SQL statement
        fetchone: If True, fetch one row
        fetchall: If True, fetch all rows
        
    Returns:
        Query result if fetchone or fetchall is True, otherwise None
    """
    global _db_stats
    
    # Start execution timer
    start_time = time.time()
    
    # Clean up SQL for logging (remove extra whitespace)
    log_sql = " ".join(sql.strip().split())
    
    # Log the first word of the SQL statement (usually the command type)
    operation = sql.strip().split()[0].upper()
    
    # Format parameters for logging, truncate if too long
    param_str = str(params)
    if len(param_str) > 100:
        param_str = param_str[:97] + "..."
    
    log_message = f"DB {operation}: {log_sql} | Params: {param_str}"
    logger.debug(log_message)
    
    async with _db_lock:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Increase queries executed counter
                _db_stats["queries_executed"] += 1
                
                # Start cursor context
                async with db.execute(sql, params) as cursor:
                    # Calculate execution time
                    execution_time = time.time() - start_time
                    _db_stats["last_query_time"] = execution_time
                    _db_stats["total_execution_time"] += execution_time
                    
                    # Update longest query if applicable
                    if execution_time > _db_stats["longest_query"]["time"]:
                        _db_stats["longest_query"]["sql"] = log_sql
                        _db_stats["longest_query"]["time"] = execution_time
                        _db_stats["longest_query"]["params"] = params
                    
                    # Log slow queries for performance debugging
                    if execution_time > 0.1:  # More than 100ms
                        logger.warning(f"Slow DB query detected: {log_sql} | Time: {execution_time:.6f}s")
                    
                    # Process the result based on the requested fetch type
                    if fetchone:
                        result = await cursor.fetchone()
                        logger.debug(f"DB Result (fetchone): {result}")
                        return result
                    elif fetchall:
                        result = await cursor.fetchall()
                        result_count = len(result) if result else 0
                        logger.debug(f"DB Result (fetchall): {result_count} rows")
                        return result
                    else:
                        # Update stats in database periodically (for long-running instances)
                        if _db_stats["queries_executed"] % 100 == 0:
                            try:
                                await db.execute(
                                    "UPDATE db_stats SET queries_executed = ?, last_query_timestamp = datetime('now')",
                                    (_db_stats["queries_executed"],)
                                )
                            except Exception as e:
                                logger.warning(f"Failed to update db_stats: {e}")
                        
                        await db.commit()
                        
                        # For INSERT, return lastrowid
                        if operation == "INSERT":
                            return cursor
                        return None
        except Exception as e:
            # Log full error details for database issues
            logger.error(f"Database error executing: {log_sql}")
            logger.error(f"Parameters: {params}")
            logger.error(f"Error: {e}")
            logger.error(traceback.format_exc())
            raise

async def get_db_stats():
    """Get database statistics for monitoring."""
    stats = dict(_db_stats)  # Make a copy to avoid modification during access
    
    # Get row counts for each table
    try:
        tables = ["tasks", "active_ctf", "board_msg", "db_stats"]
        for table in tables:
            row = await run(f"SELECT COUNT(*) FROM {table}", fetchone=True)
            if row:
                stats[f"{table}_count"] = row[0]
    except Exception as e:
        logger.error(f"Error getting table counts: {e}")
    
    return stats

# Helper functions for common operations

async def get_active_ctf():
    """Get the active CTF (name, year) or (None, None) if none is active."""
    row = await run(
        "SELECT name, year FROM active_ctf LIMIT 1", 
        fetchone=True
    )
    
    if row:
        logger.debug(f"Active CTF: {row[0]}-{row[1]}")
        return row
    
    logger.debug("No active CTF found")
    return (None, None)

async def set_active_ctf(name, year):
    """Set the active CTF, replacing any existing one."""
    logger.info(f"Setting active CTF: {name}-{year}")
    
    # Clear any existing active CTF
    await clear_active_ctf()
    
    # Set the new active CTF
    await run(
        "INSERT INTO active_ctf (name, year) VALUES (?, ?)",
        name, year
    )
    
    logger.debug(f"Active CTF set to {name}-{year}")

async def clear_active_ctf():
    """Clear the active CTF."""
    logger.info("Clearing active CTF")
    await run("DELETE FROM active_ctf")

async def add_task(category, name):
    """Add a new task to the database."""
    logger.info(f"Adding task: {category}/{name}")
    cursor = await run(
        "INSERT INTO tasks (category, name) VALUES (?, ?)",
        category.lower(), name
    )
    task_id = cursor.lastrowid if cursor else None
    logger.debug(f"Task added with ID #{task_id}")
    return task_id

async def delete_task(task_id):
    """Delete a task by ID."""
    logger.info(f"Deleting task #{task_id}")
    await run("DELETE FROM tasks WHERE id = ?", task_id)
    logger.debug(f"Task #{task_id} deleted")

async def claim_task(task_id, user_id):
    """Claim a task for a user."""
    logger.info(f"User {user_id} claiming task #{task_id}")
    await run(
        "UPDATE tasks SET claimed_by = ? WHERE id = ?",
        user_id, task_id
    )
    logger.debug(f"Task #{task_id} claimed by user {user_id}")

async def unclaim_task(task_id):
    """Unclaim a task."""
    logger.info(f"Unclaiming task #{task_id}")
    await run(
        "UPDATE tasks SET claimed_by = NULL WHERE id = ?",
        task_id
    )
    logger.debug(f"Task #{task_id} unclaimed")

async def mark_solved(task_id):
    """Mark a task as solved."""
    logger.info(f"Marking task #{task_id} as solved")
    await run(
        "UPDATE tasks SET solved = 1 WHERE id = ?",
        task_id
    )
    logger.debug(f"Task #{task_id} marked as solved")

async def get_tasks_by_ctf(ctf_name, ctf_year):
    """Get all tasks for a specific CTF."""
    logger.debug(f"Getting tasks for CTF: {ctf_name}-{ctf_year}")
    return await run(
        "SELECT id, category, name, claimed_by, solved FROM tasks WHERE ctf_name = ? AND ctf_year = ?",
        ctf_name, ctf_year,
        fetchall=True
    )

async def get_board_message(channel_id):
    """Get the board message ID for a channel, or None if not set."""
    logger.debug(f"Getting board message for channel {channel_id}")
    row = await run(
        "SELECT message_id FROM board_msg WHERE channel_id = ?",
        channel_id,
        fetchone=True
    )
    message_id = row[0] if row else None
    logger.debug(f"Board message for channel {channel_id}: {message_id}")
    return message_id

async def set_board_message(channel_id, message_id):
    """Set or update the board message ID for a channel."""
    logger.info(f"Setting board message for channel {channel_id} to {message_id}")
    # Delete any existing entries for this channel
    await run("DELETE FROM board_msg WHERE channel_id = ?", channel_id)
    # Insert the new message ID
    await run(
        "INSERT INTO board_msg (channel_id, message_id) VALUES (?, ?)",
        channel_id, message_id
    )
    logger.debug(f"Board message updated: channel={channel_id}, message={message_id}")

async def get_all_tasks():
    """Get all tasks from the database."""
    logger.debug("Getting all tasks")
    tasks = await run(
        "SELECT id, category, name, claimed_by, solved FROM tasks ORDER BY category, id",
        fetchall=True
    )
    task_count = len(tasks) if tasks else 0
    logger.debug(f"Retrieved {task_count} tasks")
    return tasks

async def get_user_claimed_unsolved_task(user_id):
    """Get a user's claimed but unsolved task, if any."""
    logger.debug(f"Checking if user {user_id} has any claimed unsolved tasks")
    task = await run(
        "SELECT id FROM tasks WHERE claimed_by = ? AND solved = 0",
        user_id,
        fetchone=True
    )
    if task:
        logger.debug(f"User {user_id} has claimed unsolved task #{task[0]}")
    else:
        logger.debug(f"User {user_id} has no claimed unsolved tasks")
    return task

async def delete_all_tasks():
    """Delete all tasks from the database and reset ID counter."""
    logger.warning("Deleting ALL tasks from the database")
    
    # Get count before deletion for logging
    count_row = await run("SELECT COUNT(*) FROM tasks", fetchone=True)
    count = count_row[0] if count_row else 0
    
    # Delete all tasks
    await run("DELETE FROM tasks")
    
    # Reset the AUTOINCREMENT counter by recreating the table
    await run("DELETE FROM sqlite_sequence WHERE name = 'tasks'")
    
    logger.info(f"All {count} tasks deleted from database and ID counter reset")

async def reset_db():
    """Reset the database to a fresh state for a new session."""
    logger.warning("Resetting database to fresh state")
    
    # Clear active CTF
    await clear_active_ctf()
    
    # Delete all tasks
    await delete_all_tasks()
    
    # Keep board message IDs intact to avoid recreation
    
    logger.info("Database reset complete - fresh state with no active CTF or challenges") 