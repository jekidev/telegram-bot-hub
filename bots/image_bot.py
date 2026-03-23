import os
import tempfile
from pathlib import Path
from io import BytesIO

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from common import is_private_chat, make_alive_command, make_post_init, run_polling
from runtime.image_enhancement import glow_up_image, roast_image_text, upscale_image
from runtime.image_osint import run_image_search

load_dotenv()
TOKEN = os.getenv("VALKYRIESELLERBUYER_BOT_TOKEN")

MODES = ["upscale", "glowup", "roast", "osint"]


def build_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✨ Glow-Up", callback_data="mode_glowup"),
                InlineKeyboardButton("🖼️ Upscale", callback_data="mode_upscale"),
                InlineKeyboardButton("🔥 Roast", callback_data="mode_roast"),
            ],
            [InlineKeyboardButton("🕵️ Image OSINT", callback_data="mode_osint")],
        ]
    )


def set_mode(context: ContextTypes.DEFAULT_TYPE, mode: str):
    if mode not in MODES:
        mode = "upscale"
    context.user_data["image_mode"] = mode


def get_mode(context: ContextTypes.DEFAULT_TYPE) -> str:
    mode = context.user_data.get("image_mode", "upscale")
    return mode if mode in MODES else "upscale"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not is_private_chat(update):
        return
    if update.message:
        await update.message.reply_text(
            "Image Bot online.\n\n"
            "Send et billede og vælg:\n"
            "• /upscale – 2x forstørrelse\n"
            "• /glowup – farver + skarphed\n"
            "• /roast – AI roast af billedet\n"
            "• /osint – reverse/EXIF + sociale spor\n",
            reply_markup=build_keyboard(),
        )


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    if not is_private_chat(update):
        return
    set_mode(context, mode)
    if update.message:
        labels = {
            "upscale": "🖼️ Upscale valgt. Send et billede.",
            "glowup": "✨ Glow-Up valgt. Send et billede.",
            "roast": "🔥 Roast valgt. Send et billede.",
            "osint": "🕵️ OSINT valgt. Send et billede (jeg laver reverse/EXIF).",
        }
        await update.message.reply_text(labels[mode], reply_markup=build_keyboard())


async def upscale_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mode_command(update, context, "upscale")


async def glowup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mode_command(update, context, "glowup")


async def roast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mode_command(update, context, "roast")


async def osint_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mode_command(update, context, "osint")


async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("mode_"):
        mode = data.split("_", 1)[1]
        await mode_command(update, context, mode)


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private_chat(update):
        return
    message = update.message
    if not message or not (message.photo or (message.document and message.document.mime_type and message.document.mime_type.startswith("image/"))):
        return

    mode = get_mode(context)
    await message.reply_text("⏳ Behandler billedet, vent et øjeblik...")

    telegram_file = None
    suffix = ".jpg"
    if message.photo:
        telegram_file = await context.bot.get_file(message.photo[-1].file_id)
    elif message.document:
        telegram_file = await context.bot.get_file(message.document.file_id)
        if message.document.file_name and "." in message.document.file_name:
            suffix = os.path.splitext(message.document.file_name)[1] or suffix

    if telegram_file is None:
        await message.reply_text("Kunne ikke hente billedet.")
        return

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name

        await telegram_file.download_to_drive(temp_path)
        image_bytes = Path(temp_path).read_bytes()

        if mode == "roast":
            roast_text = await roast_image_text(image_bytes)
            await message.reply_text(f"🔥 AI Roast:\n\n{roast_text}", reply_markup=build_keyboard())
        elif mode == "glowup":
            result, method = await glow_up_image(image_bytes)
            await _send_result(message, result, method, label="Glow-Up")
        elif mode == "osint":
            report = await run_image_search(temp_path, message.caption or "")
            await _send_chunks(message, report)
        else:
            result, method = await upscale_image(image_bytes)
            await _send_result(message, result, method, label="Upscale")
    except Exception as exc:
        await message.reply_text(f"🚫 Billedbehandlingen fejlede: {exc}")
    finally:
        set_mode(context, "upscale")
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


async def _send_result(message, result: bytes | None, method: str, label: str):
    if not result:
        await message.reply_text("🚫 Billedbehandlingen fejlede. Prøv et andet billede.", reply_markup=build_keyboard())
        return
    bio = BytesIO(result)
    bio.name = "enhanced.jpg"
    await message.reply_photo(
        photo=bio,
        caption=f"✅ {label} klar!\nMetode: {method}",
        reply_markup=build_keyboard(),
    )


async def _send_chunks(message, text: str, chunk_size: int = 3500):
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)] or [text]
    for chunk in chunks:
        await message.reply_text(chunk, reply_markup=build_keyboard())


def main():
    if not TOKEN:
        print("Missing VALKYRIESELLERBUYER_BOT_TOKEN")
        return

    app = ApplicationBuilder().token(TOKEN).post_init(make_post_init("Image Bot")).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("upscale", upscale_command))
    app.add_handler(CommandHandler("glowup", glowup_command))
    app.add_handler(CommandHandler("roast", roast_command))
    app.add_handler(CommandHandler("osint", osint_command))
    app.add_handler(CallbackQueryHandler(mode_callback, pattern="^mode_"))
    app.add_handler(CommandHandler("alive", make_alive_command("Image Bot")))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image))

    print("Image bot started")
    run_polling(app)


if __name__ == "__main__":
    main()
