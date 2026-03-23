import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from common import is_private_chat, make_alive_command, make_post_init, run_polling

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")
_owner_chat_id_raw = os.getenv("BOT_OWNER_CHAT_ID", "").strip()
OWNER_CHAT_ID = int(_owner_chat_id_raw) if _owner_chat_id_raw.isdigit() else None

# Static catalog of the six bots that are actually deployed.
BOT_LINKS = [
    ("Group Guard", "valkyriegroupmod_bot", "Anti-raid / spam guard for groups"),
    ("Marketplace", "valkyriesellerbuyer_bot", "Buyer/seller flow, referrals, lottery, Stars payments"),
    ("LLM Bridge", "valkyrieposter1249_bot", "Chat with Valkyrie AI in DM"),
    ("Maigret OSINT", "valkyriemother_bot", "Username / email / phone OSINT"),
    ("The Lounge", "valkyriewelcome_bot", "Group games, polls, confessions, alter ego"),
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
        "/postmenu – Post menu into a group (owner only)",
        "/alive – Health check",
    ]
    return "\n".join(lines)


def is_owner(update: Update) -> bool:
    return bool(OWNER_CHAT_ID and update.effective_user and update.effective_user.id == OWNER_CHAT_ID)


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


async def postmenu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_chat:
        return

    if not is_owner(update):
        return

    chat = update.effective_chat
    target_chat_id = None

    # If run in a group, post the menu into that group.
    if chat.type in ("group", "supergroup"):
        target_chat_id = chat.id
    else:
        # In DM: allow specifying a target chat id, e.g. /postmenu -1001234567890
        if context.args and context.args[0].lstrip("-").isdigit():
            target_chat_id = int(context.args[0])
        else:
            await update.message.reply_text("Usage: /postmenu <chat_id> (or run /postmenu inside the group).")
            return

    try:
        await context.bot.send_message(
            chat_id=target_chat_id,
            text="Valkyrie bots:",
            reply_markup=build_main_keyboard(),
        )
        await update.message.reply_text("Menu posted.")
    except Exception as exc:
        await update.message.reply_text(f"Failed to post menu: {exc}")


def main():
    if not TOKEN:
        print("Missing VALKYRIEMENU_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Menu Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("bots", bots_command))
    app.add_handler(CommandHandler("postmenu", postmenu_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Menu Bot")))

    print("Menu bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
