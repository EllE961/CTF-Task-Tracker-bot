#!/usr/bin/env python3
"""
Web Server Module for CTF Task-Tracker Bot

This provides a simple Flask web server to keep the bot alive
on platforms like Render.com by giving UptimeRobot an endpoint to ping.
"""
import os
import logging
import threading
import time
from flask import Flask, jsonify

# Configure logger
logger = logging.getLogger('bot.web')

# Initialize Flask app
app = Flask(__name__)

# Bot startup time
startup_time = time.time()

# Store bot reference
bot_instance = None

@app.route('/')
def home():
    """Root endpoint - simple health check."""
    uptime = time.time() - startup_time
    
    # Format uptime as days, hours, minutes, seconds
    days, remainder = divmod(uptime, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    uptime_str = f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"
    
    # Get user and guild count if bot is available
    users = 0
    guilds = 0
    active_ctf = "Unknown"
    
    if bot_instance:
        guilds = len(bot_instance.guilds)
        users = sum(g.member_count for g in bot_instance.guilds)
        
        # Try to get active CTF
        if hasattr(bot_instance, "active_ctf_name") and hasattr(bot_instance, "active_ctf_year"):
            if bot_instance.active_ctf_name and bot_instance.active_ctf_year:
                active_ctf = f"{bot_instance.active_ctf_name}-{bot_instance.active_ctf_year}"
            else:
                active_ctf = "None"
    
    return jsonify({
        "status": "ok",
        "message": "CTF Task-Tracker Bot is running",
        "uptime": uptime_str,
        "guilds": guilds,
        "users": users,
        "active_ctf": active_ctf
    })

@app.route('/health')
def health():
    """Simple health check endpoint for monitoring services."""
    return jsonify({
        "status": "ok",
        "uptime_seconds": time.time() - startup_time
    })

@app.route('/ping')
def ping():
    """Simple ping endpoint for UptimeRobot."""
    return "pong"

def run_web_server(host='0.0.0.0', port=None, bot=None):
    """
    Run the Flask web server in a separate thread.
    
    Args:
        host: Host to bind to (default: '0.0.0.0')
        port: Port to listen on (default: from PORT env var or 8080)
        bot: Reference to the bot instance
    """
    global bot_instance
    bot_instance = bot
    
    # Get port from environment or use default
    if port is None:
        port = int(os.environ.get('PORT', 8080))
    
    logger.info(f"Starting web server on {host}:{port}")
    
    # Run Flask in a separate thread
    thread = threading.Thread(
        target=lambda: app.run(host=host, port=port, debug=False),
        daemon=True
    )
    thread.start()
    logger.info("Web server started in background thread")
    
    return thread 