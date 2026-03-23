import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import is_private_chat, make_alive_command, make_post_init, run_polling
from runtime.llm_engine import clear_conversation, query_llm

load_dotenv()
TOKEN = os.getenv("VALKYRIEPOSTER1249_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        await update.message.reply_text(
            "LLM Bridge Bot online.\n\n"
            "Send me a message here in DM and I will answer with the live Valkyrie AI flow.\n"
            "Use /clear to reset the conversation.\n"
            "Use /alive for a health check."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    if update.message and update.message.text:
        user_id = update.effective_user.id if update.effective_user else 0
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is None:
            return

        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

        reply = await query_llm(user_id, update.message.text)
        chunks = [reply[i:i + 3500] for i in range(0, len(reply), 3500)] or [reply]
        for chunk in chunks:
            await update.message.reply_text(chunk)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.effective_user and update.message:
        clear_conversation(update.effective_user.id)
        await update.message.reply_text("Conversation cleared.")


def main():
    if not TOKEN:
        print("Missing VALKYRIEPOSTER1249_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("LLM Bridge Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("alive", make_alive_command("LLM Bridge Bot")))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("LLM Bridge bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
