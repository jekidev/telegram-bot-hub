import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("VALKYRIE_MENU_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Test Bot Online!")

def main():
    if not TOKEN:
        print("Missing VALKYRIE_MENU_TOKEN")
        return
    
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    
    print("Test bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
