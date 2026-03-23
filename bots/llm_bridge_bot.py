import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("VALKYRIEPOSTER1249_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Valkyrie LLM Bridge Online\nSend messages to connect to AI!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    response = f"AI Response to: {user_message[:50]}..."
    await update.message.reply_text(response)

def start():
    if not TOKEN:
        print("Missing VALKYRIE_LLM_TOKEN")
        return
    
    async def run_bot():
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        print("LLM Bridge bot started")
        await app.run_polling()
    
    asyncio.run(run_bot())

if __name__ == "__main__":
    start()
