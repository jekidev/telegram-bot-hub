import logging
import random
import os
from datetime import date, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from lounge_database import (
    load_data, save_data, get_user, update_points,
    DAILY_POLLS, SPIN_OUTCOMES, ALTER_EGO_NAMES,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────────────
# Put your lounge bot token here (get one from @BotFather)
BOT_TOKEN = os.environ.get("LOUNGE_BOT_TOKEN", "").strip()
if not BOT_TOKEN or BOT_TOKEN == "YOUR_LOUNGE_BOT_TOKEN_HERE":
    raise RuntimeError("Missing LOUNGE_BOT_TOKEN.")

# Your group's chat ID — use /setgroup inside the group to set it automatically
GROUP_CHAT_ID = os.environ.get("LOUNGE_GROUP_CHAT_ID", "")
_owner_chat_id_raw = os.environ.get("BOT_OWNER_CHAT_ID", "").strip()
OWNER_CHAT_ID = int(_owner_chat_id_raw) if _owner_chat_id_raw.isdigit() else None
# ─────────────────────────────────────────────────────────────────────────────

data = load_data()


# ══════════════════════════════════════════════════════════════════════════════
# START / HELP
# ══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(data, user.id)
    save_data(data)
    text = (
        f"🌑 Velkommen til The Lounge, {user.first_name}!\n\n"
        "📊 DAGLIGE POLLS\n"
        "Automatisk poll i gruppen kl. 18:00 hver dag.\n\n"
        "🎲 GAMBLING (ingen penge)\n"
        "/spin — Spin the wheel\n"
        "/roll [antal] — Risiker dine points (50/50)\n"
        "/lotto — Tilmeld dig dagens lotto (trækning kl. 20:00)\n\n"
        "🕵️ ANONYMT DRAMA\n"
        "/confess [tekst] — Post anonym confession til gruppen\n\n"
        "🎭 ALTER EGO\n"
        "/alterego — Få et hemmeligt navn og chat anonymt med en anden\n"
        "/end — Afslut din alter ego chat\n\n"
        "📈 STATS\n"
        "/profil — Se dine points og titel\n"
        "/toplist — Gruppens top 10\n\n"
        "⚙️ ADMIN\n"
        "/setgroup — Sæt denne gruppe som Lounge-gruppe (brug inde i gruppen)\n"
        "/poll — Send en poll nu med det samme\n"
        "/drawlotto — Træk lotto nu (til test)"
    )
    await update.message.reply_text(text)


# ══════════════════════════════════════════════════════════════════════════════
# PROFIL & TOPLIST
# ══════════════════════════════════════════════════════════════════════════════

async def profil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = get_user(data, user.id)
    save_data(data)
    text = (
        f"👤 {user.first_name}'s Profil\n\n"
        f"🏆 Titel: {u['title']}\n"
        f"💰 Points: {u['points']}\n"
        f"🌀 Chaos Score: {u.get('chaos_score', 0)}\n"
        f"🧠 Wisdom Score: {u.get('wisdom_score', 0)}\n"
        f"🕵️ Confessions sendt: {u.get('confession_count', 0)}\n"
        f"🎰 Lotto wins: {u.get('lotto_wins', 0)}\n"
        f"📅 Joined: {u['joined']}\n\n"
        f"Titler: Ghost → Broke Boy → Lurker → Climber → Hustler → Villain → King → Overlord"
    )
    await update.message.reply_text(text)


async def toplist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_users = sorted(
        data["users"].items(),
        key=lambda x: x[1]["points"],
        reverse=True
    )[:10]

    if not sorted_users:
        await update.message.reply_text("Ingen brugere endnu!")
        return

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    text = "🏆 Top 10 — The Lounge\n\n"
    for i, (uid, u) in enumerate(sorted_users):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        text += f"{medal} {u['title']} — {u['points']} pts\n"

    await update.message.reply_text(text)


# ══════════════════════════════════════════════════════════════════════════════
# GAMBLING
# ══════════════════════════════════════════════════════════════════════════════

async def spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = get_user(data, user.id)

    outcome_type, message, point_change = random.choice(SPIN_OUTCOMES)
    new_points = update_points(data, user.id, point_change)

    emoji = "🎉" if outcome_type == "win" else ("💀" if outcome_type == "lose" else "🎭")
    keyboard = [[InlineKeyboardButton("🎰 Spin igen!", callback_data="spin_again")]]

    await update.message.reply_text(
        f"{emoji} Spin Resultat\n\n"
        f"{message}\n\n"
        f"💰 Dine points: {new_points}\n"
        f"🏆 Titel: {u['title']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def spin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    u = get_user(data, user.id)

    outcome_type, message, point_change = random.choice(SPIN_OUTCOMES)
    new_points = update_points(data, user.id, point_change)

    emoji = "🎉" if outcome_type == "win" else ("💀" if outcome_type == "lose" else "🎭")
    keyboard = [[InlineKeyboardButton("🎰 Spin igen!", callback_data="spin_again")]]

    await query.edit_message_text(
        f"{emoji} Spin Resultat — {user.first_name}\n\n"
        f"{message}\n\n"
        f"💰 Points: {new_points}\n"
        f"🏆 Titel: {u['title']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = get_user(data, user.id)

    if not context.args:
        await update.message.reply_text(
            f"🎲 Roll kommando\n\n"
            f"Brug: /roll [antal points]\n"
            f"Eks: /roll 50\n\n"
            f"Du har {u['points']} points."
        )
        return

    try:
        bet = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Skriv et tal. Eks: /roll 50")
        return

    if bet <= 0:
        await update.message.reply_text("Du skal satse mindst 1 point!")
        return
    if bet > u["points"]:
        await update.message.reply_text(
            f"Du har kun {u['points']} points — du kan ikke satse {bet}."
        )
        return

    won = random.random() < 0.5
    if won:
        new_points = update_points(data, user.id, bet)
        u["chaos_score"] = u.get("chaos_score", 0) + 1
        save_data(data)
        text = (
            f"🎲 Du VANDT!\n\n"
            f"Du satsede {bet} points og vandt!\n"
            f"💰 Nye points: {new_points}\n"
            f"🏆 Titel: {u['title']}\n\n"
            f"Du er et gambling geni... eller bare heldig 😏"
        )
    else:
        new_points = update_points(data, user.id, -bet)
        u["chaos_score"] = u.get("chaos_score", 0) + 1
        save_data(data)
        text = (
            f"🎲 Du tabte...\n\n"
            f"Du satsede {bet} points og tabte dem alle.\n"
            f"💰 Tilbageværende points: {new_points}\n"
            f"🏆 Titel: {u['title']}\n\n"
            f"Bedre held næste gang 💀"
        )

    await update.message.reply_text(text)


async def lotto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    today = str(date.today())

    if data.get("last_lotto_date") != today:
        data["lotto_participants"] = []
        data["last_lotto_date"] = today
        save_data(data)

    if uid in data["lotto_participants"]:
        count = len(data["lotto_participants"])
        await update.message.reply_text(
            f"🎰 Du er allerede tilmeldt!\n\n"
            f"👥 Deltagere: {count}\n"
            f"🏆 Vinder trækkes kl. 20:00 og får 500 points."
        )
        return

    data["lotto_participants"].append(uid)
    get_user(data, user.id)
    save_data(data)
    count = len(data["lotto_participants"])

    await update.message.reply_text(
        f"🎰 Du er tilmeldt dagens lotto!\n\n"
        f"👥 Deltagere: {count}\n"
        f"🏆 Vinder trækkes kl. 20:00 og får 500 points!\n\n"
        f"Held og lykke, {user.first_name}! 🍀"
    )


async def draw_lotto(context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_CHAT_ID:
        logger.warning("LOUNGE_GROUP_CHAT_ID ikke sat — springer lotto over")
        return

    participants = data.get("lotto_participants", [])
    if not participants:
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text="🎰 Ingen tilmeldte til dagens lotto.\n\nBrug /lotto i morgen for at deltage!"
        )
        return

    winner_id = random.choice(participants)
    u = get_user(data, int(winner_id))
    u["lotto_wins"] = u.get("lotto_wins", 0) + 1
    new_points = update_points(data, int(winner_id), 500)
    data["lotto_participants"] = []
    data["last_lotto_date"] = str(date.today())
    save_data(data)

    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=(
            f"🎰 DAGENS LOTTO VINDER! 🎰\n\n"
            f"{len(participants)} deltagere — og vinderen er...\n\n"
            f"🏆 Bruger #{winner_id[-4:]} vinder 500 points!\n\n"
            f"Ny saldo: {new_points} points 💰\n\n"
            f"Brug /lotto i morgen for at prøve igen!"
        )
    )


async def draw_lotto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await draw_lotto(context)
    if not GROUP_CHAT_ID:
        await update.message.reply_text("Sæt LOUNGE_GROUP_CHAT_ID eller brug /setgroup i gruppen først.")


# ══════════════════════════════════════════════════════════════════════════════
# CONFESSION
# ══════════════════════════════════════════════════════════════════════════════

async def confess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not context.args:
        await update.message.reply_text(
            "🕵️ Confession Bot\n\n"
            "Send en anonym confession til gruppen:\n"
            "/confess [din confession]\n\n"
            "Eksempel:\n"
            "/confess Jeg stalker stadig min ex på Instagram..."
        )
        return

    if not GROUP_CHAT_ID:
        await update.message.reply_text(
            "Boten er ikke koblet til en gruppe endnu.\n"
            "Gå ind i din gruppe og skriv /setgroup."
        )
        return

    confession_text = " ".join(context.args)

    if len(confession_text) < 10:
        await update.message.reply_text("Din confession er for kort. Vær mere kreativ! 😏")
        return
    if len(confession_text) > 500:
        await update.message.reply_text("Max 500 tegn.")
        return

    u = get_user(data, user.id)
    u["confession_count"] = u.get("confession_count", 0) + 1
    u["wisdom_score"] = u.get("wisdom_score", 0) + 1
    data["confession_count"] = data.get("confession_count", 0) + 1
    confession_id = data["confession_count"]

    data["confessions"].append({
        "id": confession_id,
        "text": confession_text,
        "date": str(date.today()),
    })
    update_points(data, user.id, 10)

    keyboard = [[
        InlineKeyboardButton("😏 Real", callback_data=f"vote_real_{confession_id}"),
        InlineKeyboardButton("🤡 Fake", callback_data=f"vote_fake_{confession_id}"),
    ]]

    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text=(
            f"🕵️ Anonym Confession #{confession_id}\n\n"
            f"{confession_text}\n\n"
            f"Real eller fake?"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await update.message.reply_text(
        f"✅ Din confession er postet anonymt!\n\n"
        f"Du fik +10 points 😏\n"
        f"💰 Nye points: {u['points']}"
    )


async def confession_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Stemme registreret! 🗳️")


# ══════════════════════════════════════════════════════════════════════════════
# ALTER EGO
# ══════════════════════════════════════════════════════════════════════════════

async def alterego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)

    matches = data.setdefault("alter_ego_matches", {})
    queue = data.setdefault("alter_ego_queue", [])
    names = data.setdefault("alter_ego_names", {})

    if uid in matches:
        await update.message.reply_text(
            "🎭 Du er allerede i en alter ego chat!\n\n"
            "Skriv dine beskeder direkte — de videresendes anonymt.\n"
            "Brug /end for at afslutte."
        )
        return

    if uid in queue:
        await update.message.reply_text(
            "⏳ Du er i køen og venter på en match...\n\n"
            "Når en anden bruger starter /alterego, matches I automatisk."
        )
        return

    ego_name = random.choice(ALTER_EGO_NAMES)
    names[uid] = ego_name

    if queue and queue[0] != uid:
        partner_id = queue.pop(0)
        partner_ego = names.get(partner_id, "Den Ukendte")

        matches[uid] = partner_id
        matches[partner_id] = uid
        save_data(data)

        await update.message.reply_text(
            f"🎭 Alter Ego Aktiveret!\n\n"
            f"Du er nu: {ego_name}\n"
            f"Du er matchet med: {partner_ego}\n\n"
            f"Skriv bare — beskeder videresendes anonymt.\n"
            f"Brug /end for at afslutte."
        )
        await context.bot.send_message(
            chat_id=int(partner_id),
            text=(
                f"🎭 Din match er fundet!\n\n"
                f"Du er matchet med: {ego_name}\n\n"
                f"Skriv bare — dine beskeder videresendes anonymt.\n"
                f"Brug /end for at afslutte."
            )
        )
    else:
        if uid not in queue:
            queue.append(uid)
        save_data(data)
        await update.message.reply_text(
            f"🎭 Alter Ego Klar!\n\n"
            f"Du er nu: {ego_name}\n\n"
            f"⏳ Venter på en match...\n"
            f"Når en anden bruger starter /alterego, matches I.\n\n"
            f"Brug /end for at annullere."
        )


async def end_alterego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)

    matches = data.get("alter_ego_matches", {})
    queue = data.get("alter_ego_queue", [])

    if uid in matches:
        partner_id = matches.pop(uid, None)
        matches.pop(partner_id, None)
        save_data(data)

        await update.message.reply_text(
            "🎭 Alter Ego Chat Afsluttet\n\n"
            "Din identitet forbliver skjult. 🕵️\n\n"
            "Brug /alterego for at starte en ny chat."
        )
        try:
            await context.bot.send_message(
                chat_id=int(partner_id),
                text=(
                    "🎭 Alter Ego Chat Afsluttet\n\n"
                    "Den anden person forlod chatten. 👋\n\n"
                    "Brug /alterego for at finde en ny match."
                )
            )
        except Exception:
            pass

    elif uid in queue:
        queue.remove(uid)
        save_data(data)
        await update.message.reply_text("❌ Du er fjernet fra køen.")
    else:
        await update.message.reply_text(
            "Du er ikke i en alter ego chat.\n"
            "Brug /alterego for at starte."
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    uid = str(update.effective_user.id)
    matches = data.get("alter_ego_matches", {})

    if uid in matches:
        partner_id = matches[uid]
        ego_name = data.get("alter_ego_names", {}).get(uid, "Den Anonyme")
        try:
            await context.bot.send_message(
                chat_id=int(partner_id),
                text=f"🎭 {ego_name}:\n\n{update.message.text}"
            )
        except Exception as e:
            logger.error(f"Alter ego relay error: {e}")
            await update.message.reply_text("❌ Kunne ikke sende besked til din match.")


# ══════════════════════════════════════════════════════════════════════════════
# DAILY POLL
# ══════════════════════════════════════════════════════════════════════════════

async def send_daily_poll(context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_CHAT_ID:
        logger.warning("LOUNGE_GROUP_CHAT_ID ikke sat — springer poll over")
        return

    today = str(date.today())
    if data.get("last_poll_date") == today:
        return

    poll_index = hash(today) % len(DAILY_POLLS)
    question, options = DAILY_POLLS[poll_index]

    data["last_poll_date"] = today
    save_data(data)

    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text="📊 Dagens Lounge Poll\n\nHvad mener The Lounge?"
    )
    await context.bot.send_poll(
        chat_id=GROUP_CHAT_ID,
        question=question,
        options=options,
        is_anonymous=False,
        allows_multiple_answers=False,
    )


async def poll_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_daily_poll(context)
    if not GROUP_CHAT_ID:
        await update.message.reply_text("Sæt LOUNGE_GROUP_CHAT_ID eller brug /setgroup i gruppen først.")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN / SETUP
# ══════════════════════════════════════════════════════════════════════════════

async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GROUP_CHAT_ID
    chat = update.effective_chat

    if chat.type in ["group", "supergroup"]:
        GROUP_CHAT_ID = str(chat.id)
        os.environ["LOUNGE_GROUP_CHAT_ID"] = GROUP_CHAT_ID
        await update.message.reply_text(
            f"✅ Gruppe sat!\n\n"
            f"Gruppe ID: {GROUP_CHAT_ID}\n\n"
            f"Gem dette ID og sæt det som LOUNGE_GROUP_CHAT_ID i miljøvariablerne\n"
            f"for at polls og lotto også virker efter genstart."
        )
    else:
        await update.message.reply_text(
            f"ℹ️ Din chat ID: {chat.id}\n\n"
            f"Brug /setgroup inde i din gruppe."
        )


async def alive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.effective_chat and update.effective_chat.type != "private":
        return
    if update.message:
        await update.message.reply_text("The Lounge Bot is alive.")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if BOT_TOKEN == "YOUR_LOUNGE_BOT_TOKEN_HERE":
        logger.error("Sæt LOUNGE_BOT_TOKEN miljøvariablen eller rediger BOT_TOKEN i lounge_bot.py")
        return

    async def post_init(application: Application):
        if OWNER_CHAT_ID is None:
            return
        try:
            me = await application.bot.get_me()
            username = me.username or "unknown"
            await application.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=f"The Lounge Bot is alive on Render as @{username}.",
            )
        except Exception as exc:
            logger.warning(f"Startup alive ping failed: {exc}")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("alive", alive_cmd, filters=filters.ChatType.PRIVATE))
    app.add_handler(CommandHandler("profil", profil))
    app.add_handler(CommandHandler("toplist", toplist))
    app.add_handler(CommandHandler("spin", spin))
    app.add_handler(CommandHandler("roll", roll))
    app.add_handler(CommandHandler("lotto", lotto))
    app.add_handler(CommandHandler("drawlotto", draw_lotto_command))
    app.add_handler(CommandHandler("confess", confess))
    app.add_handler(CommandHandler("alterego", alterego))
    app.add_handler(CommandHandler("end", end_alterego))
    app.add_handler(CommandHandler("poll", poll_command))
    app.add_handler(CommandHandler("setgroup", setgroup))

    app.add_handler(CallbackQueryHandler(spin_callback, pattern="^spin_again$"))
    app.add_handler(CallbackQueryHandler(confession_vote_callback, pattern="^vote_(real|fake)_"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    job_queue = app.job_queue
    job_queue.run_daily(send_daily_poll, time=time(hour=18, minute=0), name="daily_poll")
    job_queue.run_daily(draw_lotto, time=time(hour=20, minute=0), name="daily_lotto")

    logger.info("Lounge Bot starter...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
