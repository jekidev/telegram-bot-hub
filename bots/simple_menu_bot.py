import os
import time
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

TOKEN = os.getenv("VALKYRIE_MENU_TOKEN")

def start(update: Update, context: CallbackContext):
    update.message.reply_text("⚡ Valkyrie Menu Bot Online\n\nCommands:\n/start - Show this menu\n/menu - Show main menu")

def menu(update: Update, context: CallbackContext):
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
    update.message.reply_text(menu_text)

def main():
    if not TOKEN:
        print("Missing VALKYRIE_MENU_TOKEN")
        return
    
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    
    print("Simple Menu bot started")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
