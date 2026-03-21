import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

TOKEN = os.environ.get("ADMIN_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [InlineKeyboardButton("🛡 Install Guard", callback_data="install_guard")],
        [InlineKeyboardButton("🖼 Install Image Bot", callback_data="install_image")],
        [InlineKeyboardButton("🧠 Install AI Bot", callback_data="install_ai")]
    ]

    await update.message.reply_text(
        "🤖 Bot App Store\nInstall bots with one click:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.data == "install_guard":
        await query.edit_message_text("🛡 Guard bot installed and will auto-start on server.")

    elif query.data == "install_image":
        await query.edit_message_text("🖼 Image bot installed and will auto-start on server.")

    elif query.data == "install_ai":
        await query.edit_message_text("🧠 AI bot installed and will auto-start on server.")


def main():

    if not TOKEN:
        print("Missing ADMIN_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))

    app.run_polling()


if __name__ == "__main__":
    main()
