import os
import time
from collections import defaultdict

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import is_private_chat, make_alive_command, make_post_init, run_polling

load_dotenv()
TOKEN = os.getenv("VALKYRIEGROUPMOD_BOT_TOKEN")
_owner_chat_id_raw = os.getenv("BOT_OWNER_CHAT_ID", "").strip()
OWNER_CHAT_ID = int(_owner_chat_id_raw) if _owner_chat_id_raw.isdigit() else None

RAID_JOIN_THRESHOLD = 5
RAID_TIME_WINDOW = 10
SPAM_THRESHOLD = 6
SPAM_WINDOW = 5

# Basic media spam heuristics (fallback mode when the full admin bot is not configured).
MEDIA_SPAM_THRESHOLD = 4
MEDIA_SPAM_WINDOW = 10
NEW_MEMBER_MEDIA_BLOCK_SECONDS = 120

join_tracker = defaultdict(list)
message_tracker = defaultdict(list)
media_tracker = defaultdict(list)
recent_joiners = {}  # (chat_id, user_id) -> joined_at


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        await update.message.reply_text(
            "Group Guard Bot online.\n\n"
            "Add this bot to a group to help block media spam, bot joins, raid patterns, and repeated spam.\n"
            "Use /alive here in DM for a health check."
        )


async def _notify_owner(context: ContextTypes.DEFAULT_TYPE, text: str):
    if OWNER_CHAT_ID is None:
        return
    try:
        await context.bot.send_message(chat_id=OWNER_CHAT_ID, text=text)
    except Exception:
        pass


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    chat = update.effective_chat
    user = message.from_user
    if not chat or chat.type == "private" or not user:
        return

    chat_id = chat.id
    user_id = user.id
    now = time.time()

    # Block media for very new members (common raid pattern)
    joined_at = recent_joiners.get((chat_id, user_id))
    if joined_at and (now - joined_at) < NEW_MEMBER_MEDIA_BLOCK_SECONDS:
        try:
            await message.delete()
        except Exception:
            pass
        await _notify_owner(context, f"🛡️ Deleted media from new member {user_id} in {chat.title or chat_id}")
        return

    # Track media rate and delete if spammy
    key = (chat_id, user_id)
    media_tracker[key].append(now)
    media_tracker[key] = [t for t in media_tracker[key] if now - t < MEDIA_SPAM_WINDOW]

    if len(media_tracker[key]) >= MEDIA_SPAM_THRESHOLD:
        try:
            await message.delete()
        except Exception:
            pass
        await _notify_owner(
            context,
            f"🛡️ Media spam detected: deleted media from {user_id} in {chat.title or chat_id}",
        )


async def block_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.new_chat_members:
        return

    for user in message.new_chat_members:
        recent_joiners[(update.effective_chat.id, user.id)] = time.time()
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
        await _notify_owner(
            context,
            f"🛡️ Raid activity detected in {update.effective_chat.title or chat_id} (>= {RAID_JOIN_THRESHOLD} joins/{RAID_TIME_WINDOW}s).",
        )


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
        except Exception:
            pass
        await _notify_owner(
            context,
            f"🛡️ Spam detected: banned {message.from_user.id} in {update.effective_chat.title or update.effective_chat.id}.",
        )


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
        await _notify_owner(context, f"🛡️ Possible report detected in {message.chat.title or message.chat.id} from {message.from_user.first_name}.")
    except Exception:
        pass


def main():
    if not TOKEN:
        print("Missing VALKYRIEGROUPMOD_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Group Guard Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Group Guard Bot")))
    app.add_handler(
        MessageHandler(
            filters.PHOTO
            | filters.VIDEO
            | filters.ANIMATION
            | filters.VOICE
            | filters.Sticker.ALL
            | filters.Document.ALL,
            handle_media,
        )
    )
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, block_bots))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, detect_raid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, detect_spam))
    app.add_handler(MessageHandler(filters.ALL, block_custom_emoji))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, detect_reports))

    print("Group Guard bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
