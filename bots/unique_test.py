import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import asyncio

load_dotenv()

# Use a different token for testing
TOKEN = os.getenv("VALKYRIEGOODPERSON01_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ UNIQUE BOT WORKS!")
    print("✅ Unique bot successfully responded!")

async def test_connection():
    if not TOKEN:
        print("❌ Missing VALKYRIEGOODPERSON01_BOT_TOKEN")
        return False
    
    try:
        app = Application.builder().token(TOKEN).build()
        print("🔗 Connecting to Telegram...")
        
        # Test bot info
        bot_info = await app.bot.get_me()
        print(f"✅ Connected as: @{bot_info.username}")
        
        # Add handler
        app.add_handler(CommandHandler("start", start))
        
        print("🚀 Unique bot is running! Send /start to test...")
        print("⏹️  Will auto-stop in 5 seconds...")
        
        # Run for 5 seconds then exit
        await app.initialize()
        await app.start()
        await asyncio.sleep(5)
        await app.stop()
        print("✅ Unique test completed!")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_connection())
