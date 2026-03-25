import asyncio
import base64
import os
import sqlite3
import time
from pathlib import Path

import requests
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from dotenv import load_dotenv

from runtime.llm_engine import clear_conversation, query_llm


load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "poster_bot.db"
PROMPT_PATH = BASE_DIR / "runtime" / "llm_system_prompt.txt"
BANNER_JPG = BASE_DIR / "runtime" / "banner.jpg"
BANNER_PNG = BASE_DIR / "runtime" / "banner.png"

TOKEN = os.getenv("VALKYRIEPOSTER1249_BOT_TOKEN", "").strip()
OWNER_CHAT_ID_RAW = os.getenv("BOT_OWNER_CHAT_ID", "").strip()
OWNER_CHAT_ID = int(OWNER_CHAT_ID_RAW) if OWNER_CHAT_ID_RAW.isdigit() else None
GROUP_ID_RAW = os.getenv("VALKYRIE_GROUP_ID", "").strip()
GROUP_ID = int(GROUP_ID_RAW) if GROUP_ID_RAW.lstrip("-").isdigit() else None
GROUP_LINK = os.getenv("VALKYRIE_GROUP_LINK", "").strip() or "https://t.me/yourgroup"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
STARS_PRICE = int(os.getenv("VALKYRIE_STARS_PRICE", "10"))
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("VALKYRIE_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
if OWNER_CHAT_ID is not None:
    ADMIN_IDS.add(OWNER_CHAT_ID)

BADGE_VERIFIED = "verified"
BADGE_EXCLUSIVE = "exclusive member"
INACTIVITY_TIMEOUT = 30

bot = Bot(TOKEN) if TOKEN else None
dp = Dispatcher()

waiting_for_query: set[int] = set()
pending_invoice: set[int] = set()
pending_decrypts: dict[int, str] = {}
inactivity_tasks: dict[int, asyncio.Task] = {}
admin_sessions: set[int] = set()
admin_awaiting_prompt: set[int] = set()
user_conversations: dict[int, list[dict[str, str]]] = {}


def _connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            rounds INTEGER DEFAULT 0,
            joined INTEGER DEFAULT 0,
            daily_uses INTEGER DEFAULT 0,
            last_use_date TEXT DEFAULT ''
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
            user_id INTEGER,
            query TEXT,
            timestamp INTEGER,
            api_used TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def load_system_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8").strip()
    return "You are Valkyrie AI. Answer directly, clearly, and helpfully."


def add_user_if_new(user_id: int):
    conn = _connect_db()
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def set_joined(user_id: int):
    conn = _connect_db()
    conn.execute("UPDATE users SET joined = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def has_joined(user_id: int) -> bool:
    conn = _connect_db()
    row = conn.execute("SELECT joined FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return bool(row and row["joined"] == 1)


def get_rounds(user_id: int) -> int:
    conn = _connect_db()
    row = conn.execute("SELECT rounds FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return int(row["rounds"]) if row else 0


def increment_round(user_id: int):
    conn = _connect_db()
    conn.execute("UPDATE users SET rounds = rounds + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_daily_uses(user_id: int) -> int:
    today = time.strftime("%Y-%m-%d")
    conn = _connect_db()
    row = conn.execute(
        "SELECT daily_uses, last_use_date FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        conn.close()
        return 0
    uses = int(row["daily_uses"] or 0)
    last_date = row["last_use_date"] or ""
    if last_date != today:
        conn.execute(
            "UPDATE users SET daily_uses = 0, last_use_date = ? WHERE user_id = ?",
            (today, user_id),
        )
        conn.commit()
        conn.close()
        return 0
    conn.close()
    return uses


def increment_daily_uses(user_id: int):
    today = time.strftime("%Y-%m-%d")
    conn = _connect_db()
    conn.execute(
        "UPDATE users SET daily_uses = daily_uses + 1, last_use_date = ? WHERE user_id = ?",
        (today, user_id),
    )
    conn.commit()
    conn.close()


def log_query(user_id: int, query: str, api_used: str):
    conn = _connect_db()
    conn.execute(
        "INSERT INTO logs (user_id, query, timestamp, api_used) VALUES (?, ?, ?, ?)",
        (user_id, query, int(time.time()), api_used),
    )
    conn.commit()
    conn.close()


def encode_teaser(text: str) -> tuple[str, str]:
    split = max(1, len(text) // 4)
    visible = text[:split]
    hidden = text[split:]
    encoded = base64.b64encode(hidden.encode("utf-8")).decode("ascii")
    return visible, encoded


def decode_response(encoded: str) -> str:
    return base64.b64decode(encoded.encode("ascii")).decode("utf-8")


def join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Join Valkyrie Group", url=GROUP_LINK)],
            [InlineKeyboardButton(text="I Joined", callback_data="check_join")],
        ]
    )


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Use Valkyrie AI", callback_data="use")],
            [InlineKeyboardButton(text="Buy Stars (10 Stars = 1 Round)", callback_data="buy_stars")],
            [InlineKeyboardButton(text="Join Valkyrie Group", url=GROUP_LINK)],
        ]
    )


def conversation_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="End Conversation", callback_data="end_conversation")]
        ]
    )


def after_round_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Start New Round", callback_data="use")],
            [InlineKeyboardButton(text="Back to Menu", callback_data="back_menu")],
        ]
    )


def decrypt_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Decrypt Full Response", callback_data=f"decrypt_{user_id}")],
            [InlineKeyboardButton(text="End Conversation", callback_data="end_conversation")],
        ]
    )


INTRO_TEXT = (
    "Welcome to Valkyrie AI\n"
    "Your AI Assistant\n\n"
    "Press 'Use Valkyrie AI' to start.\n"
    "First round FREE. Then 10 Stars per round."
)

JOIN_TEXT = (
    "Welcome to Valkyrie AI!\n\n"
    "Join the group first to use the bot.\n"
    "Tap below, join, then press 'I Joined'."
)


async def send_welcome(chat_id: int):
    if BANNER_JPG.exists():
        await bot.send_photo(chat_id, types.FSInputFile(BANNER_JPG), caption=INTRO_TEXT, reply_markup=main_menu())
        return
    if BANNER_PNG.exists():
        await bot.send_photo(chat_id, types.FSInputFile(BANNER_PNG), caption=INTRO_TEXT, reply_markup=main_menu())
        return
    await bot.send_message(chat_id, INTRO_TEXT, reply_markup=main_menu())


async def get_user_badge(user_id: int) -> str:
    if GROUP_ID is None:
        return ""
    try:
        member = await bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        title = getattr(member, "custom_title", "") or ""
        return title.strip().lower()
    except Exception:
        return ""


async def check_membership(user_id: int) -> bool:
    if GROUP_ID is None:
        set_joined(user_id)
        return True
    try:
        member = await bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        if getattr(member, "status", "") in ("member", "creator", "administrator"):
            set_joined(user_id)
            return True
    except Exception:
        pass
    return has_joined(user_id)


def _cancel_inactivity(user_id: int):
    task = inactivity_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()


def _clear_session(user_id: int):
    waiting_for_query.discard(user_id)
    user_conversations.pop(user_id, None)
    pending_decrypts.pop(user_id, None)
    pending_invoice.discard(user_id)
    clear_conversation(user_id)


async def _inactivity_expire(user_id: int):
    await asyncio.sleep(INACTIVITY_TIMEOUT)
    _clear_session(user_id)
    inactivity_tasks.pop(user_id, None)
    try:
        await bot.send_message(
            user_id,
            "Session ended due to inactivity (30 seconds).\n\nPress Use Valkyrie AI to start a new round.",
            reply_markup=main_menu(),
        )
    except Exception:
        pass


def _schedule_inactivity(user_id: int):
    _cancel_inactivity(user_id)
    inactivity_tasks[user_id] = asyncio.create_task(_inactivity_expire(user_id))


def _start_session(user_id: int):
    waiting_for_query.add(user_id)
    user_conversations[user_id] = [{"role": "system", "content": load_system_prompt()}]
    clear_conversation(user_id)
    _schedule_inactivity(user_id)


def _discord_post(content: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": content}, timeout=10)
    except Exception:
        pass


async def _animate_thinking(msg: types.Message, stop_event: asyncio.Event):
    frames = [
        "Valkyrie is thinking.",
        "Valkyrie is thinking..",
        "Valkyrie is thinking...",
        "Processing your request.",
        "Processing your request..",
        "Processing your request...",
    ]
    idx = 0
    while not stop_event.is_set():
        try:
            await msg.edit_text(frames[idx % len(frames)])
        except Exception:
            break
        idx += 1
        await asyncio.sleep(0.9)


@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    add_user_if_new(user_id)
    pending_invoice.discard(user_id)
    waiting_for_query.discard(user_id)
    if await check_membership(user_id):
        await send_welcome(message.chat.id)
        return
    await message.answer(JOIN_TEXT, reply_markup=join_keyboard())


@dp.message(Command("alive"))
async def alive(message: types.Message):
    if message.chat.type != "private":
        return
    await message.answer("Poster Bot is alive.")


@dp.message(Command("clear"))
async def clear(message: types.Message):
    user_id = message.from_user.id
    _clear_session(user_id)
    await message.answer("Conversation cleared.", reply_markup=main_menu())


@dp.message(Command("adminauth"))
async def admin_auth(message: types.Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        return
    admin_sessions.add(user_id)
    stuck_payments = list(pending_invoice)
    stuck_waiting = list(waiting_for_query)
    pending_invoice.clear()
    waiting_for_query.clear()
    admin_awaiting_prompt.discard(user_id)
    await message.answer(
        f"Admin session started.\n"
        f"Cleared {len(stuck_payments)} stuck payment(s).\n"
        f"Cleared {len(stuck_waiting)} stuck session(s).\n\n"
        "/chat - free AI chat session\n"
        "/stop - end admin session\n"
        "/showprompt - view current prompt\n"
        "/changeprompt - replace the prompt"
    )


@dp.message(Command("showprompt"))
async def show_prompt(message: types.Message):
    if message.from_user.id not in admin_sessions:
        return
    prompt = load_system_prompt()
    chunks = [prompt[i:i + 4000] for i in range(0, len(prompt), 4000)] or [prompt]
    await message.answer(f"Current system prompt ({len(prompt)} chars):")
    for chunk in chunks:
        await message.answer(f"```\n{chunk}\n```", parse_mode="Markdown")


@dp.message(Command("changeprompt"))
async def change_prompt_start(message: types.Message):
    if message.from_user.id not in admin_sessions:
        return
    admin_awaiting_prompt.add(message.from_user.id)
    await message.answer("Send the new system prompt as a plain message now.")


@dp.message(F.text, lambda message: message.from_user.id in admin_awaiting_prompt)
async def change_prompt_receive(message: types.Message):
    new_prompt = (message.text or "").strip()
    if not new_prompt:
        await message.answer("Empty prompt - not saved.")
        return
    PROMPT_PATH.write_text(new_prompt, encoding="utf-8")
    admin_awaiting_prompt.discard(message.from_user.id)
    await message.answer(f"System prompt updated ({len(new_prompt)} chars).")


@dp.message(Command("chat"))
async def admin_chat(message: types.Message):
    if message.from_user.id not in admin_sessions:
        return
    pending_invoice.discard(message.from_user.id)
    _start_session(message.from_user.id)
    await message.answer("Admin chat session started.\n\nSend your message now.")


@dp.message(Command("stop"))
async def admin_stop(message: types.Message):
    if message.from_user.id not in admin_sessions:
        return
    user_id = message.from_user.id
    _cancel_inactivity(user_id)
    waiting_for_query.discard(user_id)
    admin_sessions.discard(user_id)
    pending_invoice.discard(user_id)
    await message.answer("Admin session ended. Returning to normal mode.")
    await send_welcome(message.chat.id)


@dp.callback_query(F.data == "check_join")
async def on_check_join(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not await check_membership(user_id):
        await callback.answer("You haven't joined yet.", show_alert=True)
        return
    await callback.answer()
    await send_welcome(callback.message.chat.id)


@dp.callback_query(F.data == "back_menu")
async def on_back_menu(callback: types.CallbackQuery):
    await callback.answer()
    await send_welcome(callback.message.chat.id)


@dp.callback_query(F.data == "use")
async def on_use(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    add_user_if_new(user_id)

    if user_id in pending_invoice:
        await callback.answer("You already have a pending payment.", show_alert=True)
        return

    if not await check_membership(user_id):
        await callback.answer("Please join the group first.", show_alert=True)
        await callback.message.answer(JOIN_TEXT, reply_markup=join_keyboard())
        return

    badge = await get_user_badge(user_id)
    if badge == BADGE_EXCLUSIVE:
        _start_session(user_id)
        await callback.answer()
        await callback.message.answer("Exclusive Member access granted.\n\nSend your message:")
        return

    if badge == BADGE_VERIFIED:
        daily = get_daily_uses(user_id)
        if daily < 2:
            increment_daily_uses(user_id)
            _start_session(user_id)
            await callback.answer()
            await callback.message.answer(
                f"Verified access granted.\n\nYou have {2 - daily - 1} free session(s) remaining today.\nSend your message:"
            )
            return

    rounds = get_rounds(user_id)
    if rounds < 1:
        increment_round(user_id)
        _start_session(user_id)
        await callback.answer()
        await callback.message.answer(
            "First round FREE!\n\nSend MAX 1 message in the free round.\n\nSend your message:"
        )
        return

    pending_invoice.add(user_id)
    prices = [LabeledPrice(label="Extra Round - Valkyrie AI", amount=STARS_PRICE)]
    await bot.send_invoice(
        chat_id=user_id,
        title="Extra Round - Valkyrie AI",
        description="One more round for 10 Telegram Stars.",
        payload=f"extra_round_{user_id}_{int(time.time())}",
        provider_token="",
        currency="XTR",
        prices=prices,
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    user_id = message.from_user.id
    pending_invoice.discard(user_id)
    increment_round(user_id)
    _start_session(user_id)
    await message.answer("Payment successful! New round ready.\n\nSend your message:")


@dp.callback_query(F.data == "end_conversation")
async def on_end_conversation(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    _cancel_inactivity(user_id)
    waiting_for_query.discard(user_id)
    user_conversations.pop(user_id, None)
    pending_decrypts.pop(user_id, None)
    clear_conversation(user_id)
    await callback.answer()
    await callback.message.answer(
        f"Conversation ended.\nYou have used {get_rounds(user_id)} round(s) total.",
        reply_markup=after_round_menu(),
    )


@dp.callback_query(F.data.startswith("decrypt_"))
async def on_decrypt(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    target_id = int(callback.data.split("_", 1)[1])
    if user_id != target_id:
        await callback.answer("This button is not for you.", show_alert=True)
        return

    badge = await get_user_badge(user_id)
    if badge not in (BADGE_VERIFIED, BADGE_EXCLUSIVE):
        await callback.answer("You need a Verified or Exclusive Member badge to decrypt.", show_alert=True)
        return

    encoded = pending_decrypts.get(user_id)
    if not encoded:
        await callback.answer("No encrypted response found.", show_alert=True)
        return

    full_reply = decode_response(encoded)
    pending_decrypts.pop(user_id, None)
    await callback.answer("Decrypted!")
    try:
        await callback.message.edit_text(full_reply, reply_markup=conversation_menu())
    except Exception:
        await callback.message.answer(full_reply, reply_markup=conversation_menu())


@dp.callback_query(F.data == "buy_stars")
async def on_buy_stars(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Valkyrie Stars System\n\nFirst round always FREE.\nAdditional rounds: 10 Stars each.",
        reply_markup=main_menu(),
    )


@dp.message(F.text)
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    if user_id not in waiting_for_query:
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send a text message.")
        return

    rounds = get_rounds(user_id)
    if rounds == 1 and len(user_conversations.get(user_id, [])) > 2:
        await message.answer(
            "Free round allows MAX 1 message only.\nExtra message ignored.\nBuy a new round to continue."
        )
        return

    pending_invoice.discard(user_id)
    thinking_msg = await message.answer("Valkyrie is thinking.")
    stop_event = asyncio.Event()
    anim_task = asyncio.create_task(_animate_thinking(thinking_msg, stop_event))
    _cancel_inactivity(user_id)

    try:
        reply = await query_llm(user_id, text)
        log_query(user_id, text, "llm_engine")
    finally:
        stop_event.set()
        anim_task.cancel()
        try:
            await thinking_msg.delete()
        except Exception:
            pass

    badge = await get_user_badge(user_id)
    if badge == BADGE_EXCLUSIVE:
        await message.answer(reply, reply_markup=conversation_menu())
    else:
        visible, encoded = encode_teaser(reply)
        pending_decrypts[user_id] = encoded
        teaser_text = f"{visible}\n\n......\n\n`{encoded[:120]}...`"
        keyboard = decrypt_keyboard(user_id) if badge == BADGE_VERIFIED else InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Get Verified to Unlock", url=GROUP_LINK)],
                [InlineKeyboardButton(text="End Conversation", callback_data="end_conversation")],
            ]
        )
        await message.answer(teaser_text, reply_markup=keyboard, parse_mode="Markdown")

    _schedule_inactivity(user_id)


async def on_startup():
    init_db()
    if OWNER_CHAT_ID is not None:
        try:
            me = await bot.get_me()
            await bot.send_message(
                OWNER_CHAT_ID,
                f"Poster Bot is alive on Render as @{me.username}.",
            )
        except Exception:
            pass
    _discord_post("Poster Bot started.")


async def main():
    if not TOKEN:
        print("Missing VALKYRIEPOSTER1249_BOT_TOKEN")
        return
    await on_startup()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
