import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.environ.get("ADMIN_BOT_TOKEN")

BOTS = {
    "guard": "Anti‑raid and report protection bot",
    "formatter": "Menu formatting bot",
    "imagebot": "Image generation / media helper",
    "osint": "Username investigation bot",
    "llm": "AI chat bridge",
    "valkyrie": "Advanced AI assistant"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Marketplace Ready\nUse /store to see available bots.")

async def store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📦 Available Bots:\n\n"
    for name, desc in BOTS.items():
        msg += f"/{name} – {desc}\n"
    await update.message.reply_text(msg)

async def install_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡 Guard bot installation triggered (server will start it automatically if present).")

async def install_formatter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧾 Formatter bot installation triggered.")

async def install_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🖼 Image bot installation triggered.")

async def install_osint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 OSINT bot installation triggered.")

async def install_llm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 LLM bot installation triggered.")

async def install_valk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Valkyrie AI bot installation triggered.")


def main():

    if not TOKEN:
        print("Missing ADMIN_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("store", store))
    app.add_handler(CommandHandler("guard", install_guard))
    app.add_handler(CommandHandler("formatter", install_formatter))
    app.add_handler(CommandHandler("imagebot", install_image))
    app.add_handler(CommandHandler("osint", install_osint))
    app.add_handler(CommandHandler("llm", install_llm))
    app.add_handler(CommandHandler("valkyrie", install_valk))

    app.run_polling()


if __name__ == "__main__":
    main()
