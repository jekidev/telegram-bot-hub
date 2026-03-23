import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import make_alive_command, make_post_init, run_polling

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

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("LLM Bridge Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("alive", make_alive_command("LLM Bridge Bot")))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("LLM Bridge bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
