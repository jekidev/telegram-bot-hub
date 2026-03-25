"""
Valkyrie Tor Deployer Bot
Controls deployment of all framework bots through Tor network
"""

import os
import subprocess
import sys
from typing import Dict, List

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

load_dotenv()

# Bot token from user
TOKEN = "8685454358:AAF3uAkvzOaJqVVwuVPXd8CdLzC3CFXNtlI"
OWNER_CHAT_ID = int(os.getenv("BOT_OWNER_CHAT_ID", "8505253720"))

# Bot registry - all bots in the framework
BOTS: List[Dict] = [
    {
        "name": "Menu Bot",
        "username": "@valkyriemenu_bot",
        "file": "bots/menu_bot.py",
        "token_env": "VALKYRIEMENU_BOT_TOKEN",
        "status": "stopped",
    },
    {
        "name": "Group Guard",
        "username": "@valkyriegroupmod_bot",
        "file": "bots/group_guard_bot.py",
        "token_env": "VALKYRIEGROUPMOD_BOT_TOKEN",
        "status": "stopped",
    },
    {
        "name": "LLM Bridge",
        "username": "@valkyrieposter1249_bot",
        "file": "bots/llm_bridge_bot.py",
        "token_env": "VALKYRIEPOSTER1249_BOT_TOKEN",
        "status": "stopped",
    },
    {
        "name": "Maigret OSINT",
        "username": "@valkyriemother_bot",
        "file": "bots/maigret_bot.py",
        "token_env": "VALKYRIEMOTHER_BOT_TOKEN",
        "status": "stopped",
    },
    {
        "name": "Welcome/Lounge",
        "username": "@valkyriewelcome_bot",
        "file": "bots/welcome_bot.py",
        "token_env": "VALKYRIEWELCOME_BOT_TOKEN",
        "status": "stopped",
    },
    {
        "name": "Image Bot",
        "username": "@valkyrieimagegen_bot",
        "file": "bots/image_bot.py",
        "token_env": "VALKYRIEIMAGE_BOT_TOKEN",
        "status": "stopped",
    },
]

# Track running processes
running_processes: Dict[str, subprocess.Popen] = {}


def build_control_keyboard():
    """Build the main control panel keyboard"""
    buttons = []

    # Individual bot controls
    for bot in BOTS:
        status = "🟢" if bot["file"] in running_processes else "🔴"
        warning = bot.get("warning", "")
        buttons.append([
            InlineKeyboardButton(
                f"{status} {bot['name']}",
                callback_data=f"status_{bot['file']}"
            ),
            InlineKeyboardButton(
                "▶️ Start",
                callback_data=f"start_{bot['file']}"
            ),
            InlineKeyboardButton(
                "⏹ Stop",
                callback_data=f"stop_{bot['file']}"
            ),
        ])

    # Mass control buttons
    buttons.append([
        InlineKeyboardButton("🚀 START ALL", callback_data="start_all"),
        InlineKeyboardButton("🛑 STOP ALL", callback_data="stop_all"),
    ])

    buttons.append([
        InlineKeyboardButton("🧅 Start Tor Proxy", callback_data="start_tor"),
        InlineKeyboardButton("📊 Status Check", callback_data="status_all"),
    ])

    return InlineKeyboardMarkup(buttons)


def is_owner(update: Update) -> bool:
    """Check if user is the owner"""
    return bool(update.effective_user and update.effective_user.id == OWNER_CHAT_ID)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main entry point - show control panel"""
    if not is_owner(update):
        if update.message:
            await update.message.reply_text("🚫 Unauthorized access.")
        return

    text = (
        "🧅 *Valkyrie Tor Deployer*\n\n"
        "Control panel for all framework bots.\n"
        "All traffic routes through Tor when enabled.\n\n"
        "🟢 = Running  |  🔴 = Stopped\n\n"
        f"Owner ID: `{OWNER_CHAT_ID}`"
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=build_control_keyboard(),
            parse_mode="Markdown"
        )


async def start_bot(bot_file: str, use_tor: bool = True) -> str:
    """Start a single bot process"""
    if bot_file in running_processes:
        return f"⚠️ {bot_file} already running"

    try:
        env = os.environ.copy()
        if use_tor:
            env["USE_TOR_PROXY"] = "true"
            env["TOR_SOCKS5_PROXY"] = "socks5://127.0.0.1:9050"

        process = subprocess.Popen(
            [sys.executable, bot_file],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        running_processes[bot_file] = process
        return f"✅ Started {bot_file} {'with Tor' if use_tor else 'direct'}"

    except Exception as e:
        return f"❌ Failed to start {bot_file}: {e}"


async def stop_bot(bot_file: str) -> str:
    """Stop a single bot process"""
    if bot_file not in running_processes:
        return f"⚠️ {bot_file} not running"

    try:
        process = running_processes[bot_file]
        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

        del running_processes[bot_file]
        return f"⏹ Stopped {bot_file}"

    except Exception as e:
        return f"❌ Error stopping {bot_file}: {e}"


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button presses"""
    query = update.callback_query
    if not query:
        return

    await query.answer()

    if not is_owner(update):
        await query.edit_message_text("🚫 Unauthorized access.")
        return

    data = query.data or ""

    # Handle individual bot start/stop
    if data.startswith("start_") and data != "start_all":
        bot_file = data.replace("start_", "")
        result = await start_bot(bot_file, use_tor=True)
        await query.edit_message_text(
            f"{result}\n\nClick /start to refresh control panel.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Control Panel", callback_data="back_to_panel")
            ]])
        )

    elif data.startswith("stop_") and data != "stop_all":
        bot_file = data.replace("stop_", "")
        result = await stop_bot(bot_file)
        await query.edit_message_text(
            f"{result}\n\nClick /start to refresh control panel.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Control Panel", callback_data="back_to_panel")
            ]])
        )

    elif data.startswith("status_"):
        bot_file = data.replace("status_", "")
        is_running = bot_file in running_processes
        bot_info = next((b for b in BOTS if b["file"] == bot_file), None)

        status_text = "🟢 RUNNING" if is_running else "🔴 STOPPED"
        warning = bot_info.get("warning", "") if bot_info else ""

        await query.edit_message_text(
            f"📊 {bot_file}\nStatus: {status_text}\n{warning}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Control Panel", callback_data="back_to_panel")
            ]])
        )

    elif data == "start_all":
        results = []
        for bot in BOTS:
            result = await start_bot(bot["file"], use_tor=True)
            results.append(result)

        await query.edit_message_text(
            "🚀 START ALL RESULTS:\n\n" + "\n".join(results),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Control Panel", callback_data="back_to_panel")
            ]])
        )

    elif data == "stop_all":
        results = []
        for bot_file in list(running_processes.keys()):
            result = await stop_bot(bot_file)
            results.append(result)

        await query.edit_message_text(
            "🛑 STOP ALL RESULTS:\n\n" + "\n".join(results) if results else "No bots were running.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Control Panel", callback_data="back_to_panel")
            ]])
        )

    elif data == "status_all":
        lines = ["📊 BOT STATUS CHECK:\n"]
        for bot in BOTS:
            is_running = bot["file"] in running_processes
            status = "🟢 RUNNING" if is_running else "🔴 STOPPED"
            lines.append(f"{status} {bot['name']} ({bot['username']})")

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Control Panel", callback_data="back_to_panel")
            ]])
        )

    elif data == "start_tor":
        await query.edit_message_text(
            "🧅 Starting Tor proxy...\n\n"
            "To start Tor manually:\n"
            "```\n"
            "tor --SocksPort 9050\n"
            "```\n\n"
            "Or install Tor Browser and run it.\n\n"
            "Once Tor is running on port 9050, all bots will route through it.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Control Panel", callback_data="back_to_panel")
            ]])
        )

    elif data == "back_to_panel":
        await query.edit_message_text(
            "🧅 *Valkyrie Tor Deployer*\n\n"
            "Control panel for all framework bots.\n"
            "All traffic routes through Tor when enabled.\n\n"
            "🟢 = Running  |  🔴 = Stopped\n\n"
            f"Owner ID: `{OWNER_CHAT_ID}`",
            reply_markup=build_control_keyboard(),
            parse_mode="Markdown"
        )


async def list_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all bots with their details"""
    if not is_owner(update):
        return

    lines = ["🤖 *VALKYRIE BOT FRAMEWORK*\n"]

    for bot in BOTS:
        lines.append(
            f"\n*{bot['name']}*\n"
            f"Username: `{bot['username']}`\n"
            f"File: `{bot['file']}`\n"
            f"Env: `{bot['token_env']}`"
        )
        if bot.get("warning"):
            lines.append(f"⚠️ {bot['warning']}")

    text = "\n".join(lines)

    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown")


async def apis_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all API keys (masked)"""
    if not is_owner(update):
        return

    apis = [
        ("Grok/xAI", "GROK_API_KEY"),
        ("OpenRouter", "OPENROUTER_API_KEY"),
        ("Venice/Ollama", "OLLAMA_API_KEY"),
        ("Admin API ID", "ADMIN_API"),
        ("Admin API Hash", "ADMIN_HASH"),
    ]

    lines = ["🔑 *CONFIGURED APIs:*\n"]

    for name, env_var in apis:
        value = os.getenv(env_var, "")
        masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "NOT SET"
        lines.append(f"{name}: `{masked}`")

    lines.append(f"\nOwner Chat ID: `{OWNER_CHAT_ID}`")

    if update.message:
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def main():
    if not TOKEN:
        print("Missing bot token")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("bots", list_bots_command))
    app.add_handler(CommandHandler("apis", apis_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🧅 Valkyrie Tor Deployer Bot started")
    print(f"Owner Chat ID: {OWNER_CHAT_ID}")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
