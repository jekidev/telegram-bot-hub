import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("VALKYRIESELLERBUYER_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Valkyrie Image Bot Online\nSend me images to process!")

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        await update.message.reply_text("🖼️ Image received and processed!")
    elif update.message.document and update.message.document.mime_type.startswith('image/'):
        await update.message.reply_text("📁 Image document received!")

def start():
    if not TOKEN:
        print("Missing VALKYRIE_IMAGE_TOKEN")
        return
    
    async def run_bot():
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.PHOTO | filters.ATTACHMENT, handle_image))
        
        print("Image bot started")
        await app.run_polling()
    
    asyncio.run(run_bot())

if __name__ == "__main__":
    start()
