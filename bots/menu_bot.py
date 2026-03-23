import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from common import make_alive_command, make_post_init, run_polling

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

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Menu Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Menu Bot")))

    print("Menu bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
