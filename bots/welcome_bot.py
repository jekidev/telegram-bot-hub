import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

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

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_members))

    print("Welcome bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
