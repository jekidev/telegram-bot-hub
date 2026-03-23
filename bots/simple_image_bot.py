import os
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("VALKYRIESELLERBUYER_BOT_TOKEN")

def start(update: Update, context: CallbackContext):
    update.message.reply_text("📸 Valkyrie Image Bot Online\nSend me images to process!")

def handle_image(update: Update, context: CallbackContext):
    if update.message.photo:
        update.message.reply_text("🖼️ Image received and processed!")
    elif update.message.document and update.message.document.mime_type.startswith('image/'):
        update.message.reply_text("📁 Image document received!")

def main():
    if not TOKEN:
        print("Missing VALKYRIESELLERBUYER_BOT_TOKEN")
        return
    
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.photo | Filters.document, handle_image))
    
    print("Image bot started")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
