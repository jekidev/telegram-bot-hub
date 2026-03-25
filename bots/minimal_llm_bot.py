"""
Minimal LLM Bot - Natural language communication via Telegram
Uses multi-provider LLM engine with fallback chain.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# Add parent to path for importing common
sys.path.insert(0, str(Path(__file__).parent))
from common import is_private_chat, make_alive_command, make_post_init, run_polling

# Load LLM engine from Telegram-LLM-Bridge
LLM_ENGINE_PATH = Path(__file__).parent.parent.parent / "Telegram-LLM-Bridge" / "artifacts" / "telegram-bot"
if LLM_ENGINE_PATH.exists():
    sys.path.insert(0, str(LLM_ENGINE_PATH))
    try:
        from llm_engine import query_llm, clear_conversation, set_system_prompt
    except ImportError:
        # Fallback: define minimal LLM engine inline
        query_llm = None
else:
    query_llm = None

load_dotenv()
TOKEN = os.getenv("VALKYRIEMOTHER_BOT_TOKEN")

# Inline minimal LLM engine if import fails
import asyncio
import requests
import time

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SYSTEM_PROMPT = (
    "You are Valkyrie, a helpful AI assistant. "
    "Respond naturally and conversationally. Be concise but thorough."
)
TEMPERATURE = 0.85
MAX_TOKENS = 2048
HISTORY_LIMIT = 21
_conversations: dict[int, list[dict]] = {}


def _build_messages(user_id: int, user_message: str) -> list[dict]:
    if user_id not in _conversations:
        _conversations[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    else:
        _conversations[user_id][0] = {"role": "system", "content": SYSTEM_PROMPT}
    _conversations[user_id].append({"role": "user", "content": user_message})
    messages = _conversations[user_id][-HISTORY_LIMIT:]
    if messages[0]["role"] != "system":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    return messages


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


async def _query_llm_fallback(user_id: int, user_message: str) -> str:
    messages = _build_messages(user_id, user_message)
    loop = asyncio.get_event_loop()

    reply = await loop.run_in_executor(None, _try_grok, messages)
    if not reply:
        reply = await loop.run_in_executor(None, _try_openrouter, messages)
    if not reply:
        reply = await loop.run_in_executor(None, _try_pollinations, messages)
    if not reply:
        reply = "All AI providers are currently unreachable. Please try again shortly."

    _conversations[user_id].append({"role": "assistant", "content": reply})
    return reply


# Use imported or fallback
_query_llm = query_llm if query_llm else _query_llm_fallback


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        await update.message.reply_text(
            "Valkyrie LLM Bot online.\n\n"
            "I am an AI assistant that can help you with anything.\n"
            "Just send me a message and I'll respond naturally.\n\n"
            "Commands:\n"
            "/start - Show this message\n"
            "/alive - Check if I'm running\n"
            "/clear - Clear our conversation history\n"
            "/system <prompt> - Set a custom system prompt"
        )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if not update.message:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if user_id:
        _conversations.pop(user_id, None)
    await update.message.reply_text("Conversation history cleared.")


async def system_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    if not update.message:
        return
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("Usage: /system <custom system prompt>")
        return
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = prompt
    await update.message.reply_text(f"System prompt updated to: {prompt[:100]}...")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if not update.message or not update.message.text:
        return

    user_message = update.message.text.strip()
    user_id = update.effective_user.id if update.effective_user else 0

    # Show typing indicator
    await update.message.chat.send_action(action="typing")

    try:
        reply = await _query_llm(user_id, user_message)
        # Split long messages
        if len(reply) > 4000:
            chunks = [reply[i:i + 4000] for i in range(0, len(reply), 4000)]
            for chunk in chunks:
                await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)[:200]}")


def main():
    if not TOKEN:
        print("Missing VALKYRIEMOTHER_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Valkyrie LLM Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Valkyrie LLM Bot")))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("system", system_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Minimal LLM bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
