import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("VALKYRIEWELCOME_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Valkyrie LLM Bot Online\nPowered by AI!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    # Simulate AI response
    await update.message.reply_text(f"Valkyrie AI: Processing '{user_message[:30]}...'")

def start():
    if not TOKEN:
        print("Missing VALKYRIE_LLM_TOKEN")
        return
    
    async def run_bot():
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        print("Valkyrie LLM bot started")
        await app.run_polling()
    
    asyncio.run(run_bot())

if __name__ == "__main__":
    start()
