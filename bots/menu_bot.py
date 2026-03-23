import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Valkyrie Menu Bot Online\n\nCommands:\n/start - Show this menu\n/menu - Show main menu")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_text = """
🚀 VALKYRIE MENU
━━━━━━━━━━━━━━
• Group Guard - Active
• Menu Bot - Active  
• Image Bot - Active
• LLM Bridge - Active
• Valkyrie LLM - Active
• Maigret OSINT - Active

━━━━━━━━━━━━━━
Admin controls available.
    """
    await update.message.reply_text(menu_text)

def start():
    if not TOKEN:
        print("Missing VALKYRIE_MENU_TOKEN")
        return
    
    async def run_bot():
        app = Application.builder().token(TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("menu", menu))
        
        print("Menu bot started")
        await app.run_polling()
    
    asyncio.run(run_bot())

if __name__ == "__main__":
    start()
