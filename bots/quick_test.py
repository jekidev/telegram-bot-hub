import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import asyncio

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ BOT WORKS!")
    print("✅ Bot successfully responded to /start!")

async def test_connection():
    if not TOKEN:
        print("❌ Missing VALKYRIEMENU_BOT_TOKEN")
        return False
    
    try:
        app = Application.builder().token(TOKEN).build()
        print("🔗 Connecting to Telegram...")
        
        # Test bot info
        bot_info = await app.bot.get_me()
        print(f"✅ Connected as: @{bot_info.username}")
        
        # Add handler
        app.add_handler(CommandHandler("start", start))
        
        print("🚀 Bot is running! Send /start to test...")
        print("⏹️  Press Ctrl+C to stop")
        
        # Run for 10 seconds then exit
        await app.initialize()
        await app.start()
        await asyncio.sleep(10)
        await app.stop()
        print("✅ Test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_connection())
