import os
import time
from collections import defaultdict

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import make_alive_command, make_post_init, run_polling

load_dotenv()
TOKEN = os.getenv("VALKYRIEGROUPMOD_BOT_TOKEN")

RAID_JOIN_THRESHOLD = 5
RAID_TIME_WINDOW = 10
SPAM_THRESHOLD = 6
SPAM_WINDOW = 5

join_tracker = defaultdict(list)
message_tracker = defaultdict(list)


async def block_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    message = update.message
    if not message:
        return

    if any(
        [
            message.photo,
            message.video,
            message.document,
            message.animation,
            message.voice,
            message.sticker,
        ]
    ):
        try:
            await message.delete()
        except Exception:
            pass


async def block_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.new_chat_members:
        return

    for user in message.new_chat_members:
        if user.is_bot:
            try:
                await context.bot.ban_chat_member(update.effective_chat.id, user.id)
            except Exception:
                pass


async def detect_raid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    message = update.message
    if not message or not message.new_chat_members:
        return

    chat_id = update.effective_chat.id
    now = time.time()

    for _user in message.new_chat_members:
        join_tracker[chat_id].append(now)

    join_tracker[chat_id] = [
        joined_at
        for joined_at in join_tracker[chat_id]
        if now - joined_at < RAID_TIME_WINDOW
    ]

    if len(join_tracker[chat_id]) >= RAID_JOIN_THRESHOLD:
        try:
            await message.reply_text("Raid activity detected. Review recent joins.")
        except Exception:
            pass


async def detect_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text or not message.from_user:
        return

    key = (update.effective_chat.id, message.from_user.id)
    now = time.time()

    message_tracker[key].append(now)
    message_tracker[key] = [
        sent_at for sent_at in message_tracker[key] if now - sent_at < SPAM_WINDOW
    ]

    if len(message_tracker[key]) >= SPAM_THRESHOLD:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, message.from_user.id)
            await message.reply_text("Spam detected. User banned.")
        except Exception:
            pass


async def block_custom_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    message = update.message
    if not message or not message.entities:
        return

    for entity in message.entities:
        if entity.type == "custom_emoji":
            try:
                await message.delete()
            except Exception:
                pass
            return


async def detect_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text or not message.from_user:
        return

    text = message.text.lower()
    if "report" not in text and "scam" not in text and "admin" not in text:
        return

    try:
        await context.bot.send_message(
            chat_id=message.chat.id,
            text=f"Possible report detected from {message.from_user.first_name}.",
        )
    except Exception:
        pass


def main():
    if not TOKEN:
        print("Missing VALKYRIEGROUPMOD_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Group Guard Bot")).build()
    app.add_handler(CommandHandler("alive", make_alive_command("Group Guard Bot")))
    app.add_handler(MessageHandler(filters.ALL, block_media))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, block_bots))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, detect_raid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, detect_spam))
    app.add_handler(MessageHandler(filters.ALL, block_custom_emoji))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, detect_reports))

    print("Group Guard bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
