"""
CryptoAuth Bot for Valkyrie - Betalingsbaseret gruppeadgang med kryptovaluta

Denne bot håndterer:
- Betaling for gruppeadgang via BTC/ETH/XMR
- Admin godkendelse af betalinger
- Captcha/verifikation før gruppeadgang
- Blacklist håndtering
- Admin panel til styring
"""

import logging
import sqlite3
import time
import os
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ChatJoinRequestHandler, ContextTypes, MessageHandler, filters
)
from telegram.constants import ParseMode

# ================== CONFIG ==================
TOKEN = os.environ.get("VALKYRIECRYPTOAUTH_BOT_TOKEN")

DEFAULT_WEBHOOK = os.environ.get("CRYPTOAUTH_DEFAULT_WEBHOOK", 
    "https://discord.com/api/webhooks/1486202935724474468/LCVoG2IkNjUc0ir1M-CBd0ctvjdxNJ0SYz75jZRe_b_ePr8e_bmOV8wE0LYM7XBjvlfr")
CAPTCHA_WEBHOOK = os.environ.get("CRYPTOAUTH_CAPTCHA_WEBHOOK",
    "https://discord.com/api/webhooks/1486205683740311562/b2_27RA41x95lYLPPhJdVOFrylUX5fpiZ2RLoO-icrdzOgnhs9mpZk3mB6pNCgcVqidr")

AMOUNT_EUR = int(os.environ.get("CRYPTOAUTH_AMOUNT_EUR", "13"))
GRACE_PERIOD_HOURS = int(os.environ.get("CRYPTOAUTH_GRACE_PERIOD_HOURS", "2"))
CAPTCHA_TIMEOUT_HOURS = int(os.environ.get("CRYPTOAUTH_CAPTCHA_TIMEOUT_HOURS", "24"))

# Admin ID fra miljøvariabel, fallback til hardcoded
ADMIN_ID = int(os.environ.get("CRYPTOAUTH_ADMIN_ID", "8505253720"))

WALLETS_DEFAULT = {
    "BTC": os.environ.get("CRYPTOAUTH_BTC_WALLET", "bc1qxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"),
    "ETH": os.environ.get("CRYPTOAUTH_ETH_WALLET", "0xXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
    "XMR": os.environ.get("CRYPTOAUTH_XMR_WALLET", "88xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
}

# Database path
DB_PATH = os.environ.get("CRYPTOAUTH_DB_PATH", "valkyrie_auth.db")

# ===========================================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)

conn.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
conn.execute('''CREATE TABLE IF NOT EXISTS pending (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                join_time REAL,
                coin TEXT,
                paid_time REAL DEFAULT 0,
                status TEXT DEFAULT 'pending')''')  # pending, paid_waiting_approval, paid_approved, verified
conn.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
conn.execute('''CREATE TABLE IF NOT EXISTS blacklist (user_id INTEGER PRIMARY KEY, reason TEXT)''')
conn.commit()

# Indsæt default wallets hvis ikke findes
for coin, addr in WALLETS_DEFAULT.items():
    conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (f'wallet_{coin}', addr))
conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (ADMIN_ID,))
conn.commit()

def get_setting(key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default

def set_setting(key, value):
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

def get_wallet(coin: str) -> str:
    return get_setting(f'wallet_{coin}', 'Ikke sat endnu')

CURRENT_GROUP_ID = int(get_setting('group_id', os.environ.get("CRYPTOAUTH_GROUP_ID", '3837410272')))
WEBHOOK_URL = get_setting('webhook_url', DEFAULT_WEBHOOK)

def is_admin(user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,)).fetchone() is not None

def send_to_discord(webhook: str, title: str, fields: list, color=0x00ff00):
    data = {
        "embeds": [{
            "title": title,
            "color": color,
            "fields": fields,
            "timestamp": datetime.utcnow().isoformat()
        }]
    }
    try:
        requests.post(webhook, json=data, timeout=10)
    except:
        pass

def is_blacklisted(user_id):
    return conn.execute("SELECT 1 FROM blacklist WHERE user_id=?", (user_id,)).fetchone() is not None

def add_to_blacklist(user_id, reason):
    conn.execute("INSERT OR REPLACE INTO blacklist (user_id, reason) VALUES (?, ?)", (user_id, reason))
    conn.commit()

RULES_TEXT = (
    "⚠️ **Vigtige regler for Valkyrie grupper:**\n\n"
    "• Scam, snyd, doxxing, NSFW, våben, hacking og vold er **strengt forbudt**.\n"
    "• Overtrædelse = **instant ban + blacklist** i alle vores grupper.\n\n"
    "Velkommen – opfør dig ordentligt! 🚀"
)

# ====================== ADMIN MENU ======================
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Du har ikke adgang til admin panelet.")
        return

    wallets = {c: get_wallet(c) for c in ['BTC', 'ETH', 'XMR']}
    pending = conn.execute("SELECT user_id, username, coin, status FROM pending ORDER BY join_time DESC").fetchall()

    text = f"⚙️ <b>Valkyrie Auth Admin Panel</b>\n\n"
    text += f"📍 Gruppe ID: <code>{CURRENT_GROUP_ID}</code>\n"
    text += f"💰 Wallets (kan ændres):\n"
    text += f"BTC: <code>{wallets['BTC'][:15]}...</code>\n"
    text += f"ETH: <code>{wallets['ETH'][:15]}...</code>\n"
    text += f"XMR: <code>{wallets['XMR'][:15]}...</code>\n\n"
    text += "📋 <b>Ventende brugere:</b>\n\n"

    keyboard = []
    if not pending:
        text += "Ingen ventende.\n"
    else:
        for p in pending[:20]:
            uid, uname, coin, status = p
            text += f"• <code>{uid}</code> (@{uname or 'ukendt'}) — {coin} — {status}\n"
            keyboard.append([InlineKeyboardButton(f"🗑️ Slet {uid}", callback_data=f"delete_{uid}")])

    keyboard.extend([
        [InlineKeyboardButton("🔄 Opdater", callback_data="admin_refresh")],
        [InlineKeyboardButton("🗑️ Slet ALLE pending", callback_data="admin_delete_all")],
        [InlineKeyboardButton("➕ Tilføj ny Admin", callback_data="add_admin")],
        [InlineKeyboardButton("✏️ Ændre BTC Wallet", callback_data="edit_wallet_BTC")],
        [InlineKeyboardButton("✏️ Ændre ETH Wallet", callback_data="edit_wallet_ETH")],
        [InlineKeyboardButton("✏️ Ændre XMR Wallet", callback_data="edit_wallet_XMR")],
        [InlineKeyboardButton("✏️ Skift Gruppe ID", callback_data="change_group")],
    ])

    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

# ====================== WALLET EDIT ======================
async def edit_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    coin = query.data.split("_")[-1]
    context.user_data['editing_wallet'] = coin
    await query.edit_message_text(f"Send den **nye {coin} wallet adresse** som besked:")

async def handle_wallet_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'editing_wallet' not in context.user_data:
        return
    coin = context.user_data.pop('editing_wallet')
    new_address = update.message.text.strip()

    set_setting(f'wallet_{coin}', new_address)
    await update.message.reply_text(f"✅ {coin} wallet opdateret til:\n<code>{new_address}</code>", parse_mode=ParseMode.HTML)

# ====================== MANUAL APPROVAL + SEND WALLET ======================
async def notify_admins_for_approval(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, coin: str):
    keyboard = [
        [InlineKeyboardButton("✅ Godkend", callback_data=f"approve_{user_id}")],
        [InlineKeyboardButton("❌ Afvis", callback_data=f"reject_{user_id}")]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    admin_ids = [row[0] for row in conn.execute("SELECT user_id FROM admins").fetchall()]

    for aid in admin_ids:
        try:
            await context.bot.send_message(
                aid,
                f"🔔 **Ny betaling klar til godkendelse**\n\n"
                f"Bruger: @{username or 'ukendt'} (ID: <code>{user_id}</code>)\n"
                f"Coin: {coin}\n\nTryk for at godkende eller afvise.",
                parse_mode=ParseMode.HTML,
                reply_markup=markup
            )
        except:
            pass

async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Kun admins kan godkende.")
        return

    action, target_id_str = query.data.split("_")
    target_id = int(target_id_str)

    if action == "approve":
        row = conn.execute("SELECT coin, username FROM pending WHERE user_id=?", (target_id,)).fetchone()
        if not row:
            await query.edit_message_text("Bruger ikke fundet.")
            return
        coin, username = row
        wallet = get_wallet(coin)

        wallet_text = (
            f"✅ Din betaling er **godkendt** af en admin!\n\n"
            f"Send præcis **{AMOUNT_EUR} EUR** i **{coin}** til denne adresse:\n\n"
            f"<code>{wallet}</code>\n\n"
            f"Når du har sendt pengene, gå tilbage til botten og tryk på 'Jeg har betalt'."
        )

        try:
            # Forsøg at sende i secret chat (Telegram starter secret chat automatisk ved første besked i mange tilfælde)
            await context.bot.send_message(
                chat_id=target_id,
                text=wallet_text,
                parse_mode=ParseMode.HTML
            )
            sent_type = " (forsøgt sendt i Secret Chat)"
        except Exception:
            # Fallback til normal DM
            await context.bot.send_message(target_id, wallet_text, parse_mode=ParseMode.HTML)
            sent_type = " (sendt i normal DM – aktiver Secret Chat hvis muligt)"

        await query.edit_message_text(f"✅ Bruger {target_id} godkendt! Wallet sendt{sent_type}.")
        conn.execute("UPDATE pending SET status='paid_approved', paid_time=? WHERE user_id=?", (time.time(), target_id))
        conn.commit()

        # Send captcha umiddelbart efter
        keyboard = [
            [InlineKeyboardButton("Ja, jeg kender nogen", callback_data=f"knows_yes_{target_id}")],
            [InlineKeyboardButton("Nej", callback_data=f"knows_no_{target_id}")]
        ]
        try:
            await context.bot.send_message(
                target_id,
                "For at blive tilføjet til gruppen:\n**Kender du nogen i gruppen?** (Ja / Nej)",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except:
            pass

    elif action == "reject":
        add_to_blacklist(target_id, "Afvist af admin")
        conn.execute("DELETE FROM pending WHERE user_id=?", (target_id,))
        conn.commit()
        await context.bot.send_message(target_id, "❌ Din ansøgning blev afvist af admin.")
        await query.edit_message_text(f"❌ Bruger {target_id} afvist og blacklistet.")

# ====================== USER FLOW ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Velkommen!\nAdgang koster **{AMOUNT_EUR} EUR**.\nSend /join for at starte.")

async def request_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_blacklisted(user.id):
        await update.message.reply_text("Du er blacklistet.")
        return

    keyboard = [
        [InlineKeyboardButton(f"💰 {c}", callback_data=f"pay_{c}") for c in ["BTC", "ETH", "XMR"]]
    ]
    await update.message.reply_text(
        f"Adgang til gruppen koster **{AMOUNT_EUR} EUR**.\nVælg betalingsmetode:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def payment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    coin = query.data.split("_")[1]
    user = query.from_user

    conn.execute("INSERT OR REPLACE INTO pending (user_id, username, join_time, coin, status) VALUES (?, ?, ?, ?, 'pending')",
                 (user.id, user.username, time.time(), coin))
    conn.commit()

    wallet = get_wallet(coin)
    text = f"Send **{AMOUNT_EUR} EUR** i **{coin}** til:\n\n<code>{wallet}</code>\n\nNår du har betalt, tryk på knappen nedenfor."
    keyboard = [[InlineKeyboardButton("✅ Jeg har betalt", callback_data=f"paid_{coin}")]]
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

async def paid_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    coin = query.data.split("_")[1]

    conn.execute("UPDATE pending SET paid_time=?, status='paid_waiting_approval' WHERE user_id=?", (time.time(), user_id))
    conn.commit()

    row = conn.execute("SELECT username FROM pending WHERE user_id=?", (user_id,)).fetchone()
    username = row[0] if row else "ukendt"

    await query.edit_message_text("✅ Tak! Din betaling venter på godkendelse af en admin.")
    await notify_admins_for_approval(context, user_id, username, coin)

async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = int(data.split("_")[-1])
    typ = "yes" if "knows_yes" in data else "no"

    text = "Skriv **username / ID / tlf.nr** på personen du kender:" if typ == "yes" else "Hvor fandt du invite-linket? (Hvem / kanal / gruppe?):"
    await query.edit_message_text(text)
    context.user_data['awaiting_captcha'] = (typ, user_id)

async def handle_captcha_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get('awaiting_captcha')
    if not awaiting:
        return
    typ, user_id = awaiting
    answer = update.message.text.strip()
    user = update.message.from_user

    send_to_discord(CAPTCHA_WEBHOOK, "Captcha svar modtaget", [
        {"name": "User", "value": f"@{user.username or user.first_name} ({user.id})"},
        {"name": "Type", "value": "Kender nogen" if typ == "yes" else "Fandt link via"},
        {"name": "Svar", "value": answer}
    ])

    try:
        await context.bot.approve_chat_join_request(chat_id=CURRENT_GROUP_ID, user_id=user_id)
        await context.bot.send_message(user_id, RULES_TEXT)
        conn.execute("UPDATE pending SET status='verified' WHERE user_id=?", (user_id,))
        conn.commit()
        await update.message.reply_text("✅ Du er nu godkendt og tilføjet til gruppen!")
    except:
        await update.message.reply_text("Fejl ved godkendelse – kontakt admin.")

    context.user_data.pop('awaiting_captcha', None)

async def check_timeouts(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    expired = conn.execute(
        "SELECT user_id FROM pending WHERE status IN ('paid_approved', 'paid_waiting_approval') AND paid_time + ? < ?",
        (CAPTCHA_TIMEOUT_HOURS * 3600, now)
    ).fetchall()

    for (uid,) in expired:
        try:
            await context.bot.send_message(uid, "⏰ Du svarede ikke inden for 24 timer → banned.")
            add_to_blacklist(uid, "Captcha timeout")
            await context.bot.ban_chat_member(CURRENT_GROUP_ID, uid)
        except:
            pass
        conn.execute("DELETE FROM pending WHERE user_id=?", (uid,))

async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    uid = req.from_user.id
    if is_blacklisted(uid):
        await context.bot.decline_chat_join_request(CURRENT_GROUP_ID, uid)
        return

    row = conn.execute("SELECT status FROM pending WHERE user_id=?", (uid,)).fetchone()
    if not row or row[0] not in ['paid_approved', 'verified']:
        await context.bot.decline_chat_join_request(CURRENT_GROUP_ID, uid)
        try:
            await context.bot.send_message(uid, "Du skal betale og vente på admin-godkendelse. Send /join.")
        except:
            pass

# ====================== ADMIN CALLBACKS ======================
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("⛔ Adgang nægtet.")
        return
    data = query.data

    if data == "admin_refresh":
        await query.delete_message()
        await admin_menu(update, context)
        return
    if data == "admin_delete_all":
        conn.execute("DELETE FROM pending")
        conn.commit()
        await query.edit_message_text("Alle pending slettet.")
        return
    if data.startswith("delete_"):
        uid = int(data.split("_")[1])
        conn.execute("DELETE FROM pending WHERE user_id=?", (uid,))
        conn.commit()
        await query.edit_message_text(f"Bruger {uid} slettet.")
        return
    if data == "add_admin":
        await query.edit_message_text("Send det nye admin user ID som besked:")
        context.user_data['awaiting_new_admin'] = True
        return
    if data == "change_group":
        await query.edit_message_text("Send det nye gruppe ID som besked:")
        context.user_data['awaiting_new_group'] = True
        return

async def handle_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_new_admin'):
        return
    try:
        new_id = int(update.message.text.strip())
        conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_id,))
        conn.commit()
        await update.message.reply_text(f"✅ User {new_id} tilføjet som admin.")
    except:
        await update.message.reply_text("Ugyldigt ID.")
    context.user_data.pop('awaiting_new_admin', None)

async def handle_new_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_new_group'):
        return
    try:
        new_group_id = int(update.message.text.strip())
        set_setting('group_id', str(new_group_id))
        global CURRENT_GROUP_ID
        CURRENT_GROUP_ID = new_group_id
        await update.message.reply_text(f"✅ Gruppe ID opdateret til {new_group_id}.")
    except:
        await update.message.reply_text("Ugyldigt gruppe ID.")
    context.user_data.pop('awaiting_new_group', None)

# ====================== HELP ======================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **CryptoAuth Bot Kommandoer**\n\n"
        "/start – Start botten\n"
        "/join – Anmod om gruppeadgang\n"
        "/admin – Admin panel (kun admins)\n"
        "/help – Denne hjælp\n\n"
        "**Sådan fungerer det:**\n"
        "1. Send /join for at starte\n"
        "2. Vælg betalingsmetode (BTC/ETH/XMR)\n"
        "3. Send betaling til wallet adressen\n"
        "4. Tryk 'Jeg har betalt'\n"
        "5. Vent på admin godkendelse\n"
        "6. Besvar captcha spørgsmål\n"
        "7. Du bliver tilføjet til gruppen!"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# ====================== MAIN ======================
def main():
    if not TOKEN:
        print("Error: VALKYRIECRYPTOAUTH_BOT_TOKEN environment variable not set")
        return
    
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("join", request_access))
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CallbackQueryHandler(payment_choice, pattern="^pay_"))
    app.add_handler(CallbackQueryHandler(paid_button, pattern="^paid_"))
    app.add_handler(CallbackQueryHandler(approval_callback, pattern="^(approve|reject)_"))
    app.add_handler(CallbackQueryHandler(captcha_callback, pattern="^knows_(yes|no)_"))
    app.add_handler(CallbackQueryHandler(edit_wallet_callback, pattern="^edit_wallet_"))
    app.add_handler(CallbackQueryHandler(admin_callback))

    app.add_handler(ChatJoinRequestHandler(handle_join_request))
    
    # Message handlers with state checking
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_update))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_group))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_captcha_answer))

    app.job_queue.run_repeating(check_timeouts, interval=60, first=10)

    print("🚀 Valkyrie CryptoAuth Bot kører – manuel godkendelse + wallet + admin panel!")
    app.run_polling(allowed_updates=Application.ALL_TYPES)

if __name__ == '__main__':
    main()
