import os
import time
import asyncio
from collections import defaultdict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

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
async def block_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo or msg.video or msg.document or msg.animation or msg.voice or msg.sticker:
        try:
            await msg.delete()
        except:
            pass

# ---- BOT BLOCK ----
async def block_bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.new_chat_members:
        for user in update.message.new_chat_members:
            if user.is_bot:
                try:
                    await context.bot.ban_chat_member(update.effective_chat.id, user.id)
                except:
                    pass

# ---- RAID DETECTION ----
async def detect_raid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.new_chat_members:
        now = time.time()
        chat_id = update.effective_chat.id
        
        for user in update.message.new_chat_members:
            join_tracker[chat_id].append(now)
        
        # clean old joins
        join_tracker[chat_id] = [t for t in join_tracker[chat_id] if now - t < RAID_TIME_WINDOW]
        
        if len(join_tracker[chat_id]) >= RAID_JOIN_THRESHOLD:
            try:
                await context.bot.set_chat_permissions(chat_id, permissions={"can_send_messages": False})
                await update.message.reply_text("🚨 Raid detected! Chat temporarily locked.")
            except:
                pass

# ---- SPAM DETECTION ----
async def detect_spam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text:
        now = time.time()
        user_id = update.message.from_user.id
        
        message_tracker[user_id].append(now)
        message_tracker[user_id] = [t for t in message_tracker[user_id] if now - t < SPAM_WINDOW]
        
        if len(message_tracker[user_id]) >= SPAM_THRESHOLD:
            try:
                await context.bot.ban_chat_member(update.effective_chat.id, user_id)
                await update.message.reply_text("🚨 Spam detected! User banned.")
            except:
                pass

# ---- CUSTOM EMOJI BLOCK ----
async def block_custom_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.entities:
        for entity in msg.entities:
            if entity.type == "custom_emoji":
                try:
                    await msg.delete()
                except:
                    pass

# ---- REPORT DETECTION ----
async def detect_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.text:
        text = msg.text.lower()

        if "report" in text or "scam" in text or "admin" in text:
            try:
                await context.bot.send_message(
                    msg.chat.id,
                    f"⚠️ Possible report detected from {msg.from_user.first_name}"
                )
            except:
                pass

def start():
    if not TOKEN:
        print("Missing VALKYRIE_GROUP_TOKEN")
        return
    
    async def run_bot():
        app = Application.builder().token(TOKEN).build()
        
        # Add handlers with correct filter names
        app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ATTACHMENT | filters.ANIMATION | filters.VOICE | filters.STICKER, block_media))
        app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, block_bots))
        app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, detect_raid))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, detect_spam))
        
        print("Group Guard bot started")
        await app.run_polling()
    
    # Run in async context
    asyncio.run(run_bot())

if __name__ == "__main__":
    start()
