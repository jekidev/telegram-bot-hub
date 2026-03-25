"""
Valkyrie LLM Bot - Render Entry Point
Starts the minimal LLM bot and Discord bridge.
"""

import os
import sys
import threading
import time
from pathlib import Path

from flask import Flask
from bot_manager import BotManager

app = Flask(__name__)
manager = BotManager()


@app.route("/health")
def health():
    bots = manager.list_bots()
    running = [b for b in bots if b["running"]]
    return {
        "status": "ok",
        "bots_total": len(bots),
        "bots_running": len(running),
        "bots": [{"name": b["name"], "running": b["running"]} for b in bots]
    }, 200


@app.route("/")
def index():
    return {
        "service": "Valkyrie LLM Bot",
        "status": "running",
        "endpoints": ["/health"]
    }


def start_bots():
    """Start the LLM bot and Discord bridge."""
    time.sleep(2)  # Wait for Flask to start

    # Start the minimal LLM bot (maigret_bot config now points to minimal_llm_bot.py)
    print("Starting Minimal LLM Bot...")
    ok, msg = manager.start("maigret_bot")
    print(f"maigret_bot: {msg}")

    # Start Discord bridge if token is set
    if os.environ.get("DISCORD_BOT_TOKEN"):
        print("Starting Discord Bridge...")
        ok, msg = manager.start("discord_bridge")
        print(f"discord_bridge: {msg}")
    else:
        print("DISCORD_BOT_TOKEN not set, skipping Discord bridge")

    # Keep monitoring
    while True:
        time.sleep(30)
        for name in ["maigret_bot", "discord_bridge"]:
            bot = manager.bots.get(name)
            if bot and not manager._process_status(bot):
                print(f"{name} not running, attempting restart...")
                ok, msg = manager.start(name)
                print(f"{name}: {msg}")


def main():
    # Start bots in background thread
    bot_thread = threading.Thread(target=start_bots, daemon=True)
    bot_thread.start()

    # Start Flask server (Render requires a web service)
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting web server on port {port}")
    app.run(host="0.0.0.0", port=port, threaded=True)


if __name__ == "__main__":
    main()
