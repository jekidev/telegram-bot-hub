import os
import re
import tempfile

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import is_private_chat, make_alive_command, make_post_init, run_polling
from runtime.image_osint import run_image_search
from runtime.osint import run_search_full

load_dotenv()
TOKEN = os.getenv("VALKYRIEMOTHER_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        await update.message.reply_text(
            "Maigret Bot online.\n\n"
            "Send a username, email, or phone number here in DM and I will run an OSINT lookup.\n"
            "You can also send a photo for image OSINT.\n"
            "Use /username <name>, /email <address>, or /phone <number> for explicit searches.\n"
            "Use /alive for a health check."
        )


def detect_search_type(text: str):
    if re.search(r"^[+]?\d[\d\s()-]{5,}$", text):
        return "phone"
    if re.search(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text):
        return "email"
    return "username"


async def run_text_search(update: Update, query: str, search_type: str):
    if not is_private_chat(update):
        return
    if not update.message:
        return
    await update.message.reply_text(f"Running {search_type} OSINT for: {query}")
    report, _raw_data = await run_search_full(search_type, query)
    chunks = [report[i:i + 3500] for i in range(0, len(report), 3500)] or [report]
    for chunk in chunks:
        await update.message.reply_text(chunk)


async def username_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    query = " ".join(context.args).strip()
    if not query and update.message:
        await update.message.reply_text("Usage: /username <name>")
        return
    await run_text_search(update, query, "username")


async def email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    query = " ".join(context.args).strip()
    if not query and update.message:
        await update.message.reply_text("Usage: /email <address>")
        return
    await run_text_search(update, query, "email")


async def phone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    query = " ".join(context.args).strip()
    if not query and update.message:
        await update.message.reply_text("Usage: /phone <number>")
        return
    await run_text_search(update, query, "phone")


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message and update.message.text:
        query = update.message.text.strip()
        await run_text_search(update, query, detect_search_type(query))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    message = update.message
    if not message:
        return
    if not message.photo and not (message.document and message.document.mime_type and message.document.mime_type.startswith("image/")):
        return

    await message.reply_text("Running image OSINT. This can take a little while.")

    telegram_file = None
    suffix = ".jpg"
    if message.photo:
        telegram_file = await context.bot.get_file(message.photo[-1].file_id)
    elif message.document:
        telegram_file = await context.bot.get_file(message.document.file_id)
        if message.document.file_name and "." in message.document.file_name:
            suffix = os.path.splitext(message.document.file_name)[1] or suffix

    if telegram_file is None:
        await message.reply_text("Could not load that image.")
        return

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name

        await telegram_file.download_to_drive(temp_path)
        report = await run_image_search(temp_path, message.caption or "")
        chunks = [report[i:i + 3500] for i in range(0, len(report), 3500)] or [report]
        for chunk in chunks:
            await message.reply_text(chunk)
    except Exception as exc:
        await message.reply_text(f"Image OSINT failed: {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def main():
    if not TOKEN:
        print("Missing VALKYRIEMOTHER_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Maigret Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("username", username_command))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("phone", phone_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Maigret Bot")))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search))

    print("Maigret bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
