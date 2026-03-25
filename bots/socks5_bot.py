"""
Valkyrie Socks5 Bot - Tor Privacy Panel
Helps users connect to Tor via SOCKS5 proxy in Telegram.
Bot: @valkyriesocks5_bot
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Add parent to path for importing common
sys.path.insert(0, str(Path(__file__).parent))
from common import is_private_chat, make_alive_command, make_post_init, run_polling

load_dotenv()
TOKEN = os.getenv("VALKYRIESOCKS5_BOT_TOKEN")

# Tor SOCKS5 settings (for local Tor / Orbot)
PROXY_SERVER = "127.0.0.1"
PROXY_PORT = 9050  # Use 9150 if you run Tor Browser

MAIN_MESSAGE = (
    "<b>🔒 Valkyrie Socks5 - Tor Privacy Panel</b>\n\n"
    "Choose an action below to manage your Tor connection:"
)


def _get_tor_proxy_link():
    return f"https://t.me/socks?server={PROXY_SERVER}&port={PROXY_PORT}"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if not update.message:
        return

    keyboard = [
        [InlineKeyboardButton("🌐 Connect to Tor", url=_get_tor_proxy_link())],
        [InlineKeyboardButton("❌ Disable Proxy", callback_data="disable")],
        [InlineKeyboardButton("🔄 New Tor Identity", callback_data="new_identity")],
        [InlineKeyboardButton("❓ What is Tor?", callback_data="what_is_tor")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        MAIN_MESSAGE,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if query.data == "disable":
        await query.edit_message_text(
            text=(
                "<b>✅ Proxy Disabled</b>\n\n"
                "Go to Telegram Settings → Data and Storage → Proxy → Turn OFF the proxy."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("← Back to Menu", callback_data="back")]]
            ),
        )

    elif query.data == "what_is_tor":
        await query.edit_message_text(
            text=(
                "<b>🧠 What is Tor?</b>\n\n"
                "Tor routes your Telegram traffic through multiple relays around the world, "
                "hiding your real IP address and providing strong privacy.\n\n"
                "Perfect when you want maximum anonymity."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("← Back", callback_data="back")]]
            ),
        )

    elif query.data == "new_identity":
        await query.edit_message_text(
            text=(
                "<b>🔄 New Tor Identity Requested</b>\n\n"
                "To get a fresh exit node:\n\n"
                "• On Android → Open Orbot → tap the shield icon → New Identity\n"
                "• On Desktop → In Tor Browser → Click the onion menu → New Identity\n\n"
                "Your IP will change in a few seconds.\n\n"
                "You can press this button again anytime."
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🌐 Connect to Tor", url=_get_tor_proxy_link())],
                    [
                        InlineKeyboardButton(
                            "🔄 New Identity Again", callback_data="new_identity"
                        )
                    ],
                    [InlineKeyboardButton("← Back to Menu", callback_data="back")],
                ]
            ),
        )

    elif query.data == "back":
        keyboard = [
            [InlineKeyboardButton("🌐 Connect to Tor", url=_get_tor_proxy_link())],
            [InlineKeyboardButton("❌ Disable Proxy", callback_data="disable")],
            [InlineKeyboardButton("🔄 New Tor Identity", callback_data="new_identity")],
            [InlineKeyboardButton("❓ What is Tor?", callback_data="what_is_tor")],
        ]
        await query.edit_message_text(
            MAIN_MESSAGE,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True,
        )


def main():
    if not TOKEN:
        print("Missing VALKYRIESOCKS5_BOT_TOKEN")
        return

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(make_post_init("Valkyrie Socks5 Bot"))
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("tor", start_command))
    app.add_handler(CommandHandler("alive", make_alive_command("Valkyrie Socks5 Bot")))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🚀 Valkyrie Socks5 Bot is running...")
    print("Bot username: @valkyriesocks5_bot")
    run_polling(app)


if __name__ == "__main__":
    main()
