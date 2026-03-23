import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from common import is_private_chat, make_alive_command, make_post_init, run_polling

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")

# Static catalog of the six bots that are actually deployed.
BOT_LINKS = [
    ("Group Guard", "valkyriegroupmod_bot", "Anti-raid / spam guard for groups"),
    ("Image Bot", "valkyriesellerbuyer_bot", "Send an image for OSINT-style analysis"),
    ("LLM Bridge", "valkyrieposter1249_bot", "Chat with Valkyrie AI in DM"),
    ("Maigret OSINT", "valkyriemother_bot", "Username / email / phone OSINT"),
    ("Welcome Bot", "valkyriewelcome_bot", "Greets new members in groups"),
]


def build_main_keyboard():
    rows = []
    for label, username, _desc in BOT_LINKS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    url=f"https://t.me/{username}?start=start",
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def build_help_text():
    lines = [
        "Valkyrie Menu Bot online.",
        "",
        "Try the buttons below, or use commands:",
        "/menu – Show buttons",
        "/bots – List bots with descriptions",
        "/alive – Health check",
    ]
    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        await update.message.reply_text(build_help_text(), reply_markup=build_main_keyboard())


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        await update.message.reply_text("Choose a Valkyrie bot:", reply_markup=build_main_keyboard())


async def bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        lines = ["Active bots:"]
        for label, username, desc in BOT_LINKS:
            lines.append(f"- {label} (@{username}) — {desc}")
        lines.append("- Menu Bot (this one)")
        await update.message.reply_text("\n".join(lines))


def main():
    if not TOKEN:
        print("Missing VALKYRIEMENU_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Menu Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("bots", bots_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Menu Bot")))

    print("Menu bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
