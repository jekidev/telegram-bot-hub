import asyncio
import os

from telegram import Update
from telegram.ext import ContextTypes


OWNER_CHAT_ID_ENV = "BOT_OWNER_CHAT_ID"


def ensure_event_loop():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def make_alive_command(bot_name):
    async def alive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        del context
        if update.message:
            await update.message.reply_text(f"{bot_name} is alive.")

    return alive_command


def make_post_init(bot_name):
    async def post_init(application):
        owner_chat_id = os.getenv(OWNER_CHAT_ID_ENV)
        if not owner_chat_id:
            return

        try:
            await application.bot.send_message(
                chat_id=int(owner_chat_id),
                text=f"{bot_name} /alive",
            )
        except Exception as exc:
            print(f"Failed to send /alive for {bot_name}: {exc}")

    return post_init


def run_polling(app):
    ensure_event_loop()
    app.run_polling()
