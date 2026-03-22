import os
import time
from collections import defaultdict
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

TOKEN = os.getenv("VALKYRIE_GROUP_TOKEN")

# raid tracking
join_tracker = defaultdict(list)

RAID_JOIN_THRESHOLD = 5
RAID_TIME_WINDOW = 10

# spam tracking
message_tracker = defaultdict(list)
SPAM_THRESHOLD = 6
SPAM_WINDOW = 5

# ---- MEDIA BLOCK ----

def block_media(update: Update, context: CallbackContext):
    msg = update.message

    if msg.photo or msg.video or msg.document or msg.animation or msg.voice or msg.sticker:
        try:
            msg.delete()
        except:
            pass

# ---- BOT BLOCK ----

def block_bots(update: Update, context: CallbackContext):
    msg = update.message

    if msg.new_chat_members:
        for user in msg.new_chat_members:
            if user.is_bot:
                try:
                    context.bot.kick_chat_member(msg.chat.id, user.id)
                except:
                    pass

# ---- RAID DETECTION ----

def detect_raid(update: Update, context: CallbackContext):
    msg = update.message

    if msg.new_chat_members:
        now = time.time()

        join_tracker[msg.chat.id].append(now)
        join_tracker[msg.chat.id] = [t for t in join_tracker[msg.chat.id] if now - t < RAID_TIME_WINDOW]

        if len(join_tracker[msg.chat.id]) >= RAID_JOIN_THRESHOLD:
            for member in msg.new_chat_members:
                try:
                    context.bot.kick_chat_member(msg.chat.id, member.id)
                except:
                    pass

# ---- SPAM DETECTION ----

def detect_spam(update: Update, context: CallbackContext):
    msg = update.message

    user = msg.from_user.id
    now = time.time()

    message_tracker[user].append(now)
    message_tracker[user] = [t for t in message_tracker[user] if now - t < SPAM_WINDOW]

    if len(message_tracker[user]) > SPAM_THRESHOLD:
        try:
            context.bot.restrict_chat_member(
                msg.chat.id,
                user,
                permissions=None
            )
        except:
            pass

# ---- CUSTOM EMOJI BLOCK ----

def block_custom_emoji(update: Update, context: CallbackContext):
    msg = update.message

    if msg.entities:
        for entity in msg.entities:
            if entity.type == "custom_emoji":
                try:
                    msg.delete()
                except:
                    pass

# ---- REPORT DETECTION ----

def detect_reports(update: Update, context: CallbackContext):
    msg = update.message

    if msg.text:
        text = msg.text.lower()

        if "report" in text or "scam" in text or "admin" in text:
            try:
                context.bot.send_message(
                    msg.chat.id,
                    f"⚠️ Possible report detected from {msg.from_user.first_name}"
                )
            except:
                pass



def main():

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(MessageHandler(
        Filters.photo | Filters.video | Filters.document | Filters.animation | Filters.voice | Filters.sticker,
        block_media
    ))

    dp.add_handler(MessageHandler(
        Filters.status_update.new_chat_members,
        block_bots
    ))

    dp.add_handler(MessageHandler(
        Filters.status_update.new_chat_members,
        detect_raid
    ))

    dp.add_handler(MessageHandler(
        Filters.all,
        detect_spam
    ))

    dp.add_handler(MessageHandler(
        Filters.entity("custom_emoji"),
        block_custom_emoji
    ))

    dp.add_handler(MessageHandler(
        Filters.text,
        detect_reports
    ))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
