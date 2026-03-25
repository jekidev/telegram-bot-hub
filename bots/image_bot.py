"""
Image Bot - @valkyrieimagegen_bot
Based on Telegram-Image-Bot from https://github.com/jekidev/Telegram-Image-Bot
Features: upscale, glowup, roast
NO VPN/PROXY - Direct connection
"""
import logging
import os
from io import BytesIO

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from runtime.image_enhancement import upscale_image, glow_up_image, roast_image_text

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Token: 8606792990:AAH_VjejWrgzv_VDWVafcgw4p8w0NMy7DTk
BOT_TOKEN = os.getenv("VALKYRIEIMAGE_BOT_TOKEN", "8606792990:AAH_VjejWrgzv_VDWVafcgw4p8w0NMy7DTk")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"Hej {user.first_name}! 📸\n\n"
        "Send mig et billede, og jeg forbedrer det for dig.\n\n"
        "Vælg hvad du vil:\n\n"
        "/upscale — Upscaler billedet 2x (gratis)\n"
        "/glowup — Giver billedet et glow-up (større + skarpere + bedre farver)\n"
        "/roast — AI roaster dit billede 🔥\n\n"
        "Eller send bare et billede direkte, så upscaler jeg det automatisk."
    )
    await update.message.reply_text(text)


async def upscale_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["image_mode"] = "upscale"
    await update.message.reply_text(
        "📸 Upscale klar!\n\nSend mig nu et billede, og jeg upscaler det 2x gratis."
    )


async def glowup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["image_mode"] = "glowup"
    await update.message.reply_text(
        "✨ Glow-Up klar!\n\nSend mig et billede — jeg giver det 2x størrelse + bedre farver + skarphed."
    )


async def roast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["image_mode"] = "roast"
    await update.message.reply_text(
        "🔥 Roast Mode!\n\nSend mig et billede, og AI roaster det. Advarsel: Det kan gøre lidt ondt 😅"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo:
        return

    mode = context.user_data.get("image_mode", "upscale")

    await update.message.reply_text("⏳ Behandler dit billede, vent et øjeblik...")

    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        image_bytes = bytes(await file.download_as_bytearray())

        if mode == "roast":
            roast_text = await roast_image_text(image_bytes)
            await update.message.reply_text(f"🔥 AI Roast:\n\n{roast_text}")
            context.user_data["image_mode"] = "upscale"
            return

        if mode == "glowup":
            result, method = await glow_up_image(image_bytes)
            label = "Glow Up"
        else:
            result, method = await upscale_image(image_bytes)
            label = "Upscale"

        if result:
            bio = BytesIO(result)
            bio.name = "enhanced.jpg"
            keyboard = [[
                InlineKeyboardButton("✨ Glow-Up", callback_data="mode_glowup"),
                InlineKeyboardButton("📸 Upscale", callback_data="mode_upscale"),
                InlineKeyboardButton("🔥 Roast", callback_data="mode_roast"),
            ]]
            await update.message.reply_photo(
                photo=bio,
                caption=f"✅ {label} færdig!\nMetode: {method}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text("❌ Billedbehandlingen fejlede. Prøv et andet billede.")

    except Exception as e:
        logger.error(f"Photo handling error: {e}")
        await update.message.reply_text("❌ Der opstod en fejl. Prøv igen!")

    context.user_data["image_mode"] = "upscale"


async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "mode_glowup":
        context.user_data["image_mode"] = "glowup"
        await query.message.reply_text("✨ Glow-Up valgt! Send mig nu et billede.")
    elif data == "mode_upscale":
        context.user_data["image_mode"] = "upscale"
        await query.message.reply_text("📸 Upscale valgt! Send mig nu et billede.")
    elif data == "mode_roast":
        context.user_data["image_mode"] = "roast"
        await query.message.reply_text("🔥 Roast valgt! Send mig nu et billede.")


def main():
    if not BOT_TOKEN:
        print("Missing VALKYRIEIMAGE_BOT_TOKEN")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("upscale", upscale_command))
    app.add_handler(CommandHandler("glowup", glowup_command))
    app.add_handler(CommandHandler("roast", roast_command))
    app.add_handler(CallbackQueryHandler(mode_callback, pattern="^mode_"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logger.info("Image Bot (@valkyrieimagegen_bot) starting...")
    print("🤖 Image Bot (@valkyrieimagegen_bot) started - NO VPN/PROXY")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
