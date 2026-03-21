import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.environ.get("ADMIN_BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Hosting Control Panel Online")

async def bots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = []
    for root, dirs, fs in os.walk("bots"):
        for f in fs:
            if f.endswith(".py"):
                files.append(f)
    await update.message.reply_text("Running bots:\n" + "\n".join(files))

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Restarting bots (monitor will handle)")


def main():
    if not TOKEN:
        print("Missing ADMIN_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bots", bots))
    app.add_handler(CommandHandler("restart", restart))

    app.run_polling()

if __name__ == "__main__":
    main()
