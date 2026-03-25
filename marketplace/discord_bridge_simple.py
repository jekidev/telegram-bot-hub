"""
Discord → Telegram LLM Bridge (Standalone)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Runs a Discord bot that forwards messages to/from Telegram LLM Bot.
No Admin API required - works directly with Telegram bots.

Required secrets:
  DISCORD_BOT_TOKEN      — your Discord bot token
  VALKYRIEMOTHER_BOT_TOKEN — Telegram bot token for @valkyriemother_bot

Optional:
  DISCORD_ADMIN_CHANNEL  — channel ID(s) the bot will accept commands in
  GROK_API_KEY           — for LLM responses
  OPENROUTER_API_KEY     — for LLM fallback

Setup
─────
1. Go to https://discord.com/developers/applications
2. Create a new application → Bot → copy the token
3. Bot permissions: Send Messages, Embed Links, Read Message History
4. Invite URL: https://discord.com/api/oauth2/authorize?client_id=<APP_ID>&permissions=67584&scope=bot
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
import requests

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "bots"))
from common import ensure_event_loop

# Try to import LLM engine
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "Telegram-LLM-Bridge" / "artifacts" / "telegram-bot"))
    from llm_engine import query_llm, clear_conversation
except ImportError:
    query_llm = None
    clear_conversation = None

logging.basicConfig(
    format="%(asctime)s [DISCORD] %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.environ.get("VALKYRIEMOTHER_BOT_TOKEN", "")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

_raw_channels = os.environ.get("DISCORD_ADMIN_CHANNEL", "")
ADMIN_CHANNELS = {int(c.strip()) for c in _raw_channels.split(",") if c.strip()}

# In-memory conversation storage for Discord users
_discord_conversations: dict[int, list] = {}

# Inline LLM fallback
import time
GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SYSTEM_PROMPT = "You are Valkyrie, a helpful AI assistant. Respond naturally and conversationally."
TEMPERATURE = 0.85
MAX_TOKENS = 2048


def _try_grok(messages: list) -> str:
    if not GROK_API_KEY:
        return ""
    for model in ["grok-3-mini", "grok-2", "grok-2-mini"]:
        try:
            resp = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS},
                timeout=60,
            )
            if resp.status_code == 200:
                reply = (resp.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if reply:
                    return reply
        except Exception:
            continue
    return ""


def _try_openrouter(messages: list) -> str:
    if not OPENROUTER_KEY:
        return ""
    for model in [
        "cognitivecomputations/dolphin3.0-mistral-24b:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "mistralai/mistral-small-3.1-24b-instruct:free",
    ]:
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://valkyrie.replit.app",
                    "X-Title": "Valkyrie AI",
                },
                json={"model": model, "messages": messages, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS},
                timeout=60,
            )
            if resp.status_code == 200:
                reply = (resp.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if reply:
                    return reply
        except Exception:
            continue
    return ""


def _try_pollinations(messages: list) -> str:
    for model in ["openai", "mistral-large"]:
        try:
            resp = requests.post(
                "https://text.pollinations.ai/openai",
                json={"model": model, "messages": messages, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS},
                timeout=45,
            )
            if resp.status_code == 200:
                reply = (resp.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
                if reply:
                    return reply
        except Exception:
            continue
    return ""


def _build_messages(discord_user_id: int, user_message: str) -> list[dict]:
    if discord_user_id not in _discord_conversations:
        _discord_conversations[discord_user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    else:
        _discord_conversations[discord_user_id][0] = {"role": "system", "content": SYSTEM_PROMPT}
    _discord_conversations[discord_user_id].append({"role": "user", "content": user_message})
    messages = _discord_conversations[discord_user_id][-21:]  # HISTORY_LIMIT
    if messages[0]["role"] != "system":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    return messages


async def _query_llm_local(discord_user_id: int, user_message: str) -> str:
    if query_llm:
        return await query_llm(discord_user_id, user_message)

    messages = _build_messages(discord_user_id, user_message)
    loop = asyncio.get_event_loop()

    reply = await loop.run_in_executor(None, _try_grok, messages)
    if not reply:
        reply = await loop.run_in_executor(None, _try_openrouter, messages)
    if not reply:
        reply = await loop.run_in_executor(None, _try_pollinations, messages)
    if not reply:
        reply = "All AI providers are currently unreachable. Please try again shortly."

    _discord_conversations[discord_user_id].append({"role": "assistant", "content": reply})
    return reply


intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


def is_authorised(message: discord.Message) -> bool:
    if not ADMIN_CHANNELS:
        return True
    return message.channel.id in ADMIN_CHANNELS


async def send_chunks(message: discord.Message, text: str):
    """Discord has a 2000-char limit; split if needed."""
    for i in range(0, len(text), 1990):
        chunk = text[i:i+1990]
        await message.channel.send(chunk)


async def handle_chat_command(message: discord.Message, parts: list[str]):
    """Handle /chat command for LLM conversation."""
    sub = parts[1] if len(parts) > 1 else ""
    session_id = message.author.id

    if sub.lower() == "clear":
        _discord_conversations.pop(session_id, None)
        await message.channel.send("🗑️ Chat history cleared.")
        return

    user_message = " ".join(parts[1:]).strip()
    if not user_message:
        await message.channel.send("Usage: /chat <your message>\n       /chat clear — reset conversation")
        return

    async with message.channel.typing():
        reply = await _query_llm_local(session_id, user_message)

    await send_chunks(message, reply)


@bot.event
async def on_ready():
    logger.info(f"Discord bridge logged in as {bot.user} (ID: {bot.user.id})")
    if ADMIN_CHANNELS:
        logger.info(f"Restricted to channels: {ADMIN_CHANNELS}")
    else:
        logger.info("No channel restriction — responding in any channel.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not is_authorised(message):
        return

    # Handle /chat commands
    if message.content.startswith("/chat"):
        parts = message.content.strip().split()
        await handle_chat_command(message, parts)
        return

    # Handle direct mentions or DMs
    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        user_message = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if user_message:
            async with message.channel.typing():
                reply = await _query_llm_local(message.author.id, user_message)
            await send_chunks(message, reply)


async def run_async():
    if not BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN is not set — Discord bridge will not start.")
        return
    await bot.start(BOT_TOKEN)


def run():
    if not BOT_TOKEN:
        logger.warning("DISCORD_BOT_TOKEN not set, skipping Discord bridge.")
        return
    ensure_event_loop()
    asyncio.run(run_async())


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: Set DISCORD_BOT_TOKEN in your environment.")
        sys.exit(1)
    run()
