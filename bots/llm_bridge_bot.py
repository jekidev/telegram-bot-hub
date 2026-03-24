import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from common import is_private_chat, make_alive_command, make_post_init, run_polling
from runtime.llm_engine import clear_conversation, query_llm

load_dotenv()
TOKEN = os.getenv("VALKYRIEPOSTER1249_BOT_TOKEN")


def _extract_prompt_from_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """
    In groups/supergroups, only respond when mentioned or when the user replies to the bot.
    In DMs, respond normally.

    Returns the cleaned user prompt (with @bot mentions removed) or "" if we should ignore.
    """

    if not update.message or not update.message.text:
        return ""

    text = update.message.text.strip()
    chat = update.effective_chat
    if not chat:
        return ""

    if chat.type == "private":
        return text

    if chat.type not in ("group", "supergroup"):
        return ""

    bot_username = getattr(context.bot, "username", "") or ""
    bot_id = getattr(context.bot, "id", None)

    is_mentioned = bool(bot_username) and f"@{bot_username}".lower() in text.lower()
    is_reply_to_bot = False
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        from_user = update.message.reply_to_message.from_user
        if bot_id is not None and from_user.id == bot_id:
            is_reply_to_bot = True
        elif bot_username and (from_user.username or "").lower() == bot_username.lower():
            is_reply_to_bot = True

    if not is_mentioned and not is_reply_to_bot:
        return ""

    if bot_username:
        text = text.replace(f"@{bot_username}", "").replace(f"@{bot_username}".lower(), "").strip()
    return text


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # In groups, don't spam on every message; just guide the user when they explicitly run /start.
    if not is_private_chat(update):
        username = getattr(context.bot, "username", "") or "this bot"
        await update.message.reply_text(
            f"LLM Bridge is active.\n\n"
            f"DM me to chat, or mention @{username} / reply to me in the group to get a response."
        )
        return

    await update.message.reply_text(
        "LLM Bridge Bot online.\n\n"
        "Send me a message here in DM and I will answer with the live Valkyrie AI flow.\n"
        "Use /clear to reset the conversation.\n"
        "Use /alive for a health check."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = _extract_prompt_from_update(update, context)
    if not prompt:
        return

    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    reply = await query_llm(user_id, prompt)
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
