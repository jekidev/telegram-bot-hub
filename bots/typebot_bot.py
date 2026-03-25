"""
Typebot Integration Bot for Telegram Bot Hub

This bot provides a Telegram interface to Typebot.io chatbots.
Users can interact with Typebot flows directly through Telegram messages.
"""

import os
import asyncio
import aiohttp
import json
from typing import Optional, Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Configuration
BOT_TOKEN = os.environ.get("VALKYRIETYPEBOT_BOT_TOKEN")
TYPEBOT_VIEWER_URL = os.environ.get("TYPEBOT_VIEWER_URL", "http://localhost:8081")
TYPEBOT_API_URL = os.environ.get("TYPEBOT_API_URL", "http://localhost:3000")
DEFAULT_TYPEBOT_ID = os.environ.get("DEFAULT_TYPEBOT_ID", "")

# Session storage for active conversations
user_sessions: Dict[int, Dict[str, Any]] = {}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command - begin a Typebot session."""
    user_id = update.effective_user.id
    
    # Clear any existing session
    if user_id in user_sessions:
        del user_sessions[user_id]
    
    # Get typebot ID from command args or use default
    args = context.args
    typebot_id = args[0] if args else DEFAULT_TYPEBOT_ID
    
    if not typebot_id:
        await update.message.reply_text(
            "Welcome to Typebot! 🚀\n\n"
            "Usage:\n"
            "/start [typebot_id] - Start a chatbot session\n"
            "/session - Show current session info\n"
            "/reset - Reset current session\n\n"
            "Please provide a typebot ID to start."
        )
        return
    
    # Initialize session
    user_sessions[user_id] = {
        "typebot_id": typebot_id,
        "session_id": None,
        "messages": [],
    }
    
    # Start the conversation
    await start_typebot_session(update, user_id, typebot_id)


async def start_typebot_session(update: Update, user_id: int, typebot_id: str) -> None:
    """Initialize a new Typebot chat session."""
    try:
        async with aiohttp.ClientSession() as session:
            # Start chat session via Typebot API
            url = f"{TYPEBOT_VIEWER_URL}/api/v1/typebots/{typebot_id}/startChat"
            payload = {
                "isOnlyRegistering": False,
                "user": {
                    "id": str(user_id),
                    "name": update.effective_user.first_name or "User",
                    "email": update.effective_user.username or f"user_{user_id}@telegram.bot"
                }
            }
            
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Store session ID
                    user_sessions[user_id]["session_id"] = data.get("sessionId")
                    
                    # Process and display messages
                    messages = data.get("messages", [])
                    await display_typebot_messages(update, messages)
                else:
                    await update.message.reply_text(
                        f"❌ Failed to start Typebot session. Status: {response.status}"
                    )
    except Exception as e:
        await update.message.reply_text(f"❌ Error starting session: {str(e)}")


async def display_typebot_messages(update: Update, messages: list) -> None:
    """Display Typebot messages in Telegram."""
    for msg in messages:
        msg_type = msg.get("type")
        
        if msg_type == "text":
            content = msg.get("content", {})
            text = content.get("richText", [{}])[0].get("children", [{}])[0].get("text", "")
            if text:
                await update.message.reply_text(text)
                
        elif msg_type == "image":
            url = msg.get("content", {}).get("url")
            if url:
                await update.message.reply_photo(url)
                
        elif msg_type == "video":
            url = msg.get("content", {}).get("url")
            if url:
                await update.message.reply_video(url)
                
        elif msg_type == "embed":
            url = msg.get("content", {}).get("url", "")
            await update.message.reply_text(f"🔗 Embed: {url}")
            
        elif msg_type == "choice input":
            # Handle button choices
            items = msg.get("items", [])
            if items:
                keyboard = [
                    [InlineKeyboardButton(item.get("content", "Option"), callback_data=f"choice:{item.get('id')}")]
                    for item in items
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("Please choose:", reply_markup=reply_markup)


async def continue_session(update: Update, user_id: int, message: str) -> None:
    """Continue an existing Typebot session with user input."""
    session_data = user_sessions.get(user_id)
    if not session_data or not session_data.get("session_id"):
        await update.message.reply_text("No active session. Start with /start [typebot_id]")
        return
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{TYPEBOT_VIEWER_URL}/api/v1/sessions/{session_data['session_id']}/continueChat"
            payload = {
                "message": {
                    "type": "text",
                    "text": message
                }
            }
            
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Check if session ended
                    if data.get("type") == "Session ended":
                        await update.message.reply_text("✅ Session ended. Start a new one with /start")
                        del user_sessions[user_id]
                        return
                    
                    # Display new messages
                    messages = data.get("messages", [])
                    await display_typebot_messages(update, messages)
                else:
                    await update.message.reply_text("❌ Error continuing session")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular text messages."""
    user_id = update.effective_user.id
    
    if user_id not in user_sessions:
        await update.message.reply_text(
            "No active session. Start one with /start [typebot_id]"
        )
        return
    
    message_text = update.message.text
    await continue_session(update, user_id, message_text)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    callback_data = query.data
    
    if callback_data.startswith("choice:"):
        choice_id = callback_data.replace("choice:", "")
        # Send the choice as a message
        await continue_session(update, user_id, choice_id)


async def session_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current session information."""
    user_id = update.effective_user.id
    
    if user_id not in user_sessions:
        await update.message.reply_text("No active session")
        return
    
    session_data = user_sessions[user_id]
    info = (
        f"📊 Session Info:\n\n"
        f"Typebot ID: {session_data.get('typebot_id', 'N/A')}\n"
        f"Session ID: {session_data.get('session_id', 'N/A')[:20]}...\n"
        f"Messages exchanged: {len(session_data.get('messages', []))}"
    )
    await update.message.reply_text(info)


async def reset_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset the current session."""
    user_id = update.effective_user.id
    
    if user_id in user_sessions:
        del user_sessions[user_id]
        await update.message.reply_text("✅ Session reset. Start a new one with /start [typebot_id]")
    else:
        await update.message.reply_text("No active session to reset")


async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check Typebot service health."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{TYPEBOT_VIEWER_URL}/health") as response:
                if response.status == 200:
                    await update.message.reply_text("✅ Typebot viewer is healthy")
                else:
                    await update.message.reply_text(f"⚠️ Typebot viewer status: {response.status}")
    except Exception as e:
        await update.message.reply_text(f"❌ Typebot viewer unreachable: {str(e)}")


def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        print("Error: VALKYRIETYPEBOT_BOT_TOKEN environment variable not set")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("session", session_info))
    application.add_handler(CommandHandler("reset", reset_session))
    application.add_handler(CommandHandler("health", health_check))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Typebot Integration Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
