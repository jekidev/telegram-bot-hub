import os
import time
from collections import defaultdict
from telegram.ext import ApplicationBuilder, MessageHandler, ChatMemberHandler, filters

TOKEN = os.environ.get("GUARD_BOT_TOKEN")

join_tracker = defaultdict(list)
message_tracker = defaultdict(list)

RAID_JOIN_LIMIT = 5
RAID_TIME = 10
SPAM_LIMIT = 6
SPAM_TIME = 5

async def detect_spam(update, context):
    user = update.effective_user.id
    now = time.time()

    message_tracker[user] = [t for t in message_tracker[user] if now - t < SPAM_TIME]
    message_tracker[user].append(now)

    if len(message_tracker[user]) > SPAM_LIMIT:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, user)
            await update.message.reply_text("🚫 User auto-banned for spam (anti-raid)")
        except Exception:
            pass

async def detect_joins(update, context):
    chat = update.chat_member.chat.id
    now = time.time()

    join_tracker[chat] = [t for t in join_tracker[chat] if now - t < RAID_TIME]
    join_tracker[chat].append(now)

    if len(join_tracker[chat]) > RAID_JOIN_LIMIT:
        try:
            await context.bot.send_message(chat, "⚠️ Possible raid detected. Enabling slow mode.")
        except Exception:
            pass

async def ai_moderation(update, context):
    text = update.message.text

    if not text:
        return

    banned_words = ["scam", "free crypto", "report bot"]

    for w in banned_words:
        if w in text.lower():
            try:
                await context.bot.delete_message(update.effective_chat.id, update.message.message_id)
                await update.message.reply_text("🧠 AI moderation removed suspicious message")
            except Exception:
                pass


def main():

    if not TOKEN:
        print("Missing GUARD_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT, detect_spam))
    app.add_handler(MessageHandler(filters.TEXT, ai_moderation))
    app.add_handler(ChatMemberHandler(detect_joins, ChatMemberHandler.CHAT_MEMBER))

    app.run_polling()


if __name__ == "__main__":
    main()
