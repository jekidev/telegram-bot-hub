import os
import tempfile

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import is_private_chat, make_alive_command, make_post_init, run_polling
from runtime.image_osint import run_image_search

load_dotenv()
TOKEN = os.getenv("VALKYRIESELLERBUYER_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        await update.message.reply_text(
            "Image Bot online.\n\nSend a photo or image document here in DM.\nUse /alive for a health check."
        )


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    message = update.message
    if not message:
        return
    if not message.photo and not (message.document and message.document.mime_type and message.document.mime_type.startswith("image/")):
        return

    await message.reply_text("Running image analysis. This can take a little while.")

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
        user_context = message.caption or ""
        report = await run_image_search(temp_path, user_context)
        chunks = [report[i:i + 3500] for i in range(0, len(report), 3500)] or [report]
        for chunk in chunks:
            await message.reply_text(chunk)
    except Exception as exc:
        await message.reply_text(f"Image analysis failed: {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def main():
    if not TOKEN:
        print("Missing VALKYRIESELLERBUYER_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Image Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Image Bot")))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image))

    print("Image bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
