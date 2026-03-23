import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message:
        await update.message.reply_text(
            "Valkyrie Menu Bot online.\n\n"
            "Commands:\n"
            "/start - health check\n"
            "/menu - show active bots"
        )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message:
        await update.message.reply_text(
            "Valkyrie bots:\n"
            "- Group Guard\n"
            "- Menu Bot\n"
            "- Image Bot\n"
            "- LLM Bridge\n"
            "- Maigret\n"
            "- Welcome Bot"
        )


def main():
    if not TOKEN:
        print("Missing VALKYRIEMENU_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))

    print("Menu bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
