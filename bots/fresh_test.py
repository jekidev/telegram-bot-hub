import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import asyncio

# PASTE YOUR NEW BOT TOKEN HERE
TOKEN = "PASTE_NEW_BOT_TOKEN_HERE"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ FRESH BOT WORKS!")
    print("✅ Fresh bot responded to /start!")

async def test_bot():
    if TOKEN == "PASTE_NEW_BOT_TOKEN_HERE":
        print("❌ Please paste your new bot token first!")
        return
    
    try:
        app = Application.builder().token(TOKEN).build()
        print("🔗 Connecting to Telegram...")
        
        bot_info = await app.bot.get_me()
        print(f"✅ Connected as: @{bot_info.username}")
        
        app.add_handler(CommandHandler("start", start))
        
        print("🚀 Fresh bot running! Send /start to test...")
        print("⏹️  Auto-stops in 10 seconds...")
        
        await app.initialize()
        await app.start()
        await asyncio.sleep(10)
        await app.stop()
        print("✅ Test completed!")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_bot())
