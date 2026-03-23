import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import is_private_chat, make_alive_command, make_post_init, run_polling

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
    del context
    if not is_private_chat(update):
        return
    message = update.message
    if not message:
        return

    if message.photo:
        await message.reply_text("Photo received and queued for processing.")
        return

    if message.document and message.document.mime_type:
        if message.document.mime_type.startswith("image/"):
            await message.reply_text("Image document received.")


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
