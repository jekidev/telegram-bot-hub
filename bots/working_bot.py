import os
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")

def start(update: Update, context: CallbackContext):
    update.message.reply_text("⚡ BOT IS WORKING!")
    print("✅ Bot responded to /start")

def main():
    if not TOKEN:
        print("❌ Missing VALKYRIEMENU_BOT_TOKEN")
        return
    
    try:
        updater = Updater(TOKEN, use_context=True)
        dp = updater.dispatcher
        
        dp.add_handler(CommandHandler("start", start))
        
        print("🚀 Working bot started...")
        updater.start_polling()
        updater.idle()
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
