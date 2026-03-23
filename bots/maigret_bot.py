import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("VALKYRIE_MAIGRET_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Valkyrie Maigret OSINT Bot Online\nSend username to investigate!")

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    await update.message.reply_text(f"🔍 Searching for: {query}\n📊 OSINT analysis in progress...")

def start():
    if not TOKEN:
        print("Missing VALKYRIE_MAIGRET_TOKEN")
        return
    
    async def run_bot():
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))
        
        print("Maigret OSINT bot started")
        await app.run_polling()
    
    asyncio.run(run_bot())

if __name__ == "__main__":
    start()
