import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
TOKEN = os.getenv("VALKYRIEMOTHER_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message:
        await update.message.reply_text(
            "Maigret Bot online. Send a username to start an OSINT lookup."
        )


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message and update.message.text:
        await update.message.reply_text(
            f"Searching for '{update.message.text}' and preparing OSINT results."
        )


def main():
    if not TOKEN:
        print("Missing VALKYRIEMOTHER_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))

    print("Maigret bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
