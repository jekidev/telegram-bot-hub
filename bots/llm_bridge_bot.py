import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
TOKEN = os.getenv("VALKYRIEPOSTER1249_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message:
        await update.message.reply_text(
            "LLM Bridge Bot online. Send a message and I will acknowledge it."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message and update.message.text:
        preview = update.message.text[:80]
        await update.message.reply_text(f"Bridge received: {preview}")


def main():
    if not TOKEN:
        print("Missing VALKYRIEPOSTER1249_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("LLM Bridge bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
