import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import make_alive_command, make_post_init, run_polling

load_dotenv()
TOKEN = os.getenv("VALKYRIEWELCOME_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message:
        await update.message.reply_text("Welcome Bot online and ready to greet new members.")


async def welcome_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    message = update.message
    if not message or not message.new_chat_members:
        return

    for user in message.new_chat_members:
        await message.reply_text(f"Welcome to the chat, {user.first_name}.")


def main():
    if not TOKEN:
        print("Missing VALKYRIEWELCOME_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Welcome Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Welcome Bot")))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_members))

    print("Welcome bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
