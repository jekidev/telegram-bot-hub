import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv()
TOKEN = os.getenv("VALKYRIESELLERBUYER_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.message:
        await update.message.reply_text("Image Bot online. Send a photo or image document.")


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
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

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image))

    print("Image bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
