"""
@valkyriegroupmod_bot
Admin control panel + group report watcher.
- Panel only responds in ADMIN_GROUP_ID
- Report watcher monitors ANY group the bot is added to
"""
import os
import re
import time
import asyncio
import csv
import io
import logging
import importlib.util
import psycopg2
import psycopg2.extras
import psycopg2.pool
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

logging.basicConfig(
    format="%(asctime)s [ADMIN-BOT] %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("VALKYRIEGROUPMOD_BOT_TOKEN")
    or ""
)
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN (or VALKYRIEGROUPMOD_BOT_TOKEN).")

_raw_admin_group_id = os.environ.get("ADMIN_GROUP_ID", "").strip()
ADMIN_GROUP_ID = (
    -abs(int(_raw_admin_group_id))
    if _raw_admin_group_id.lstrip("-").isdigit()
    else None
)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL.")

# Set application_name so Postgres logs show which component is connecting.
# Can be overridden per-deploy with PG_APP_NAME.
_PG_APP_NAME = os.environ.get("PG_APP_NAME", "valkyrie_group_guard")

_owner_chat_id_raw = os.environ.get("BOT_OWNER_CHAT_ID", "").strip()
OWNER_CHAT_ID = int(_owner_chat_id_raw) if _owner_chat_id_raw.isdigit() else None
ADMIN_NOTIFY_CHAT_ID = ADMIN_GROUP_ID if ADMIN_GROUP_ID is not None else OWNER_CHAT_ID
SCRIPTS_DIR = Path(__file__).parent / "scripts"

# Comma-separated Telegram user IDs that can DM this admin bot with NL commands
# e.g. ADMIN_USER_IDS=123456789,987654321
_admin_user_ids_raw = os.environ.get("ADMIN_USER_IDS", "")
ADMIN_USER_IDS: set[int] = {
    int(x.strip()) for x in _admin_user_ids_raw.split(",") if x.strip().lstrip("-").isdigit()
}
if OWNER_CHAT_ID is not None:
    ADMIN_USER_IDS.add(OWNER_CHAT_ID)

# Optional: send periodic community "auto messages" to the admin notify chat.
# Defaults to off to avoid unexpected spam.
AUTO_MESSAGES_ENABLED = os.environ.get("ADMIN_AUTO_MESSAGES", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

AWAITING_BAN = "ban"
AWAITING_REMOVE = "remove"
AWAITING_BROADCAST = "broadcast"
AWAITING_WARN = "warn"
AWAITING_SEARCH = "search"
AWAITING_KEYWORD = "keyword"
AWAITING_SETTING = "setting"
AWAITING_SCRIPT = "await_script"

# How quickly a join+leave is flagged as suspicious (seconds)
REPORT_SUSPECT_WINDOW = 300  # 5 minutes

_pool: psycopg2.pool.SimpleConnectionPool | None = None


def _get_pool() -> psycopg2.pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL, application_name=_PG_APP_NAME)
    return _pool


@contextmanager
def get_db():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _ensure_report_tables():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_joins (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT NOT NULL,
                username   TEXT,
                full_name  TEXT,
                chat_id    BIGINT NOT NULL,
                chat_title TEXT,
                joined_at  TIMESTAMP DEFAULT NOW(),
                left_at    TIMESTAMP,
                flagged    BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lottery_entries (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT NOT NULL UNIQUE,
                username   TEXT,
                full_name  TEXT,
                entered_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS keyword_emojis (
                id         SERIAL PRIMARY KEY,
                keyword    TEXT NOT NULL UNIQUE,
                emoji      TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.close()


# ── Stats (3 queries instead of 6) ────────────────────────────────────────────

def get_stats():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE role='seller' AND status='approved') AS sellers,
                COUNT(*) FILTER (WHERE role='seller' AND status='pending')  AS pending_sellers,
                COUNT(*) FILTER (WHERE role='buyer')                        AS buyers
            FROM users
        """)
        sellers, pending, buyers = cur.fetchone()

        cur.execute("""
            SELECT
                COUNT(*)                                           AS total,
                COUNT(*) FILTER (WHERE status='accepted')         AS accepted
            FROM product_requests
        """)
        total_req, accepted = cur.fetchone()

        cur.execute("SELECT COUNT(*), ROUND(AVG(stars)::numeric,1) FROM ratings")
        rat_count, avg_stars = cur.fetchone()
        cur.close()

    return (
        int(sellers), int(pending), int(buyers),
        int(total_req), int(accepted),
        int(rat_count), float(avg_stars or 0),
    )


def stars_str(avg, count):
    if not count:
        return "☆☆☆☆☆ _(no ratings)_"
    filled = round(avg); empty = 5 - filled
    return "★" * filled + "☆" * empty + f" ({avg}/5 · {count})"


# ── Bot Settings (key-value store) ────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM bot_settings WHERE key=%s", (key,))
            row = cur.fetchone()
            cur.close()
        return row[0] if row else default
    except Exception:
        return default


def set_setting(key: str, value: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO bot_settings(key, value) VALUES(%s,%s)
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
        """, (key, value))
        cur.close()


# ── Keyword → Emoji engine ─────────────────────────────────────────────────────

_kw_cache: dict[str, str] = {}
_kw_cache_ts: float = 0.0
_KW_CACHE_TTL = 60  # seconds


def load_keywords(force: bool = False) -> dict[str, str]:
    """Return {keyword_lower: emoji} from DB, cached for 60 s."""
    global _kw_cache, _kw_cache_ts
    now = time.time()
    if not force and (now - _kw_cache_ts) < _KW_CACHE_TTL:
        return _kw_cache
    try:
        with get_db() as conn:
            cur = conn.cursor()
            # Longest keywords first so longer phrases take priority
            cur.execute("SELECT keyword, emoji FROM keyword_emojis ORDER BY LENGTH(keyword) DESC")
            _kw_cache = {r[0].lower(): r[1] for r in cur.fetchall()}
            _kw_cache_ts = now
            cur.close()
    except Exception as e:
        logger.warning(f"load_keywords error: {e}")
    return _kw_cache


def apply_keywords(text: str, keywords: dict[str, str]) -> tuple[str, bool]:
    """
    Replace every keyword occurrence in text with the corresponding emoji.
    Matching is case-insensitive substring (no word-boundary restriction so
    partial words like 'hash' inside 'hashish' are also matched).
    Returns (new_text, was_changed).
    """
    result = text
    changed = False
    for kw, emoji in keywords.items():
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        new = pattern.sub(emoji, result)
        if new != result:
            changed = True
            result = new
    return result, changed


# ── Panel ──────────────────────────────────────────────────────────────────────

AUTO_MESSAGES = [
    "🛍️ Active sellers are online! Use /request to find what you need.",
    "⭐ Rate your sellers after a deal — it helps the community!",
    "🎰 A lottery is open! Use /join in the marketplace bot to enter.",
    "📦 Sellers: add your products with /addproduct to get more buyers.",
    "🔗 Refer friends to the marketplace bot and earn bonus points!",
    "🏆 Check your rank in the marketplace with /rank!",
]


def panel_keyboard():
    return InlineKeyboardMarkup([
        # ── Analytics ───────────────────────────────────────────
        [
            InlineKeyboardButton("📊  Statistics",     callback_data="adm_stats"),
            InlineKeyboardButton("📜  Activity Log",   callback_data="adm_activity"),
        ],
        # ── Users ───────────────────────────────────────────────
        [
            InlineKeyboardButton("🏪  Sellers",        callback_data="adm_sellers"),
            InlineKeyboardButton("🛒  Buyers",         callback_data="adm_buyers"),
        ],
        [
            InlineKeyboardButton("✅  Approvals",      callback_data="adm_approvals"),
            InlineKeyboardButton("📋  Requests",       callback_data="adm_requests"),
        ],
        # ── Moderation ──────────────────────────────────────────
        [
            InlineKeyboardButton("🔍  Search User",    callback_data="adm_search"),
            InlineKeyboardButton("⚠️  Warn User",      callback_data="adm_warn"),
        ],
        [
            InlineKeyboardButton("🚫  Ban Seller",     callback_data="adm_ban"),
            InlineKeyboardButton("🗑️  Remove User",   callback_data="adm_remove"),
        ],
        [
            InlineKeyboardButton("🕵️  Suspect Log",   callback_data="adm_report_suspects"),
            InlineKeyboardButton("📤  Export Data",    callback_data="adm_export"),
        ],
        # ── Engagement ──────────────────────────────────────────
        [
            InlineKeyboardButton("📢  Broadcast",      callback_data="adm_broadcast"),
            InlineKeyboardButton("🔗  Referrals",      callback_data="adm_referrals"),
        ],
        [
            InlineKeyboardButton("🎰  Lottery",        callback_data="adm_lottery"),
            InlineKeyboardButton("🏆  Rankings",       callback_data="adm_rankings"),
        ],
        # ── System ──────────────────────────────────────────────
        [
            InlineKeyboardButton("🔤  Keywords",       callback_data="adm_keywords"),
            InlineKeyboardButton("⚙️  Settings",       callback_data="adm_settings"),
        ],
        [
            InlineKeyboardButton("🐍  Scripts",        callback_data="adm_scripts"),
            InlineKeyboardButton("♻️  Refresh",        callback_data="adm_panel"),
        ],
    ])


def panel_text():
    s, pending, b, tr, ac, rat, avg = get_stats()
    rate_pct = round(ac / tr * 100, 1) if tr else 0
    now = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
    alert = f"\n⚠️  *{pending} seller{'s' if pending != 1 else ''} awaiting approval*" if pending else ""
    return (
        f"🛡️  *Valkyrie Admin Panel*\n"
        f"_{now}_\n"
        f"{'─' * 28}\n"
        f"\n"
        f"👥  *Users*\n"
        f"   🏪 Sellers: *{s}*   🛒 Buyers: *{b}*{alert}\n"
        f"\n"
        f"📦  *Marketplace*\n"
        f"   Requests: *{tr}*   Accepted: *{ac}* ({rate_pct}%)\n"
        f"\n"
        f"⭐  *Ratings*\n"
        f"   Total: *{rat}*   Average: *{avg} / 5*\n"
        f"{'─' * 28}"
    )


# ── Script runner ──────────────────────────────────────────────────────────────

def _run_script_sync(script_path: Path, timeout: int = 30) -> str:
    """
    Execute a Python script as a subprocess, capturing stdout + stderr.
    Works for any script — no run() function required.
    Enforces a timeout and passes all current env vars (including DATABASE_URL).
    """
    import subprocess, sys
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
            cwd=str(script_path.parent),
        )
        parts = []
        if result.stdout.strip():
            parts.append(result.stdout.strip())
        if result.stderr.strip():
            parts.append(f"[stderr]\n{result.stderr.strip()}")
        if not parts:
            parts.append("✅ Script finished with no output.")
        if result.returncode != 0:
            parts.append(f"\n⚠️ Exit code: {result.returncode}")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"⏱️ Script timed out after {timeout}s."
    except Exception as e:
        return f"❌ Could not run script:\n{e}"


# ── Admin group check ──────────────────────────────────────────────────────────

def _admin_id_variants():
    if ADMIN_GROUP_ID is None:
        return set()
    raw = abs(ADMIN_GROUP_ID)
    return {-raw, -(int(f"100{raw}"))}


ADMIN_ID_VARIANTS = _admin_id_variants()


def is_admin_group(update: Update) -> bool:
    return update.effective_chat.id in ADMIN_ID_VARIANTS


# ── Handlers ───────────────────────────────────────────────────────────────────

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    uid = update.effective_user.id
    if (update.effective_chat.id not in ADMIN_ID_VARIANTS) and (uid not in ADMIN_USER_IDS):
        return

    chat = update.effective_chat
    user = update.effective_user
    await update.message.reply_text(
        f"🆔  *Chat ID:* `{chat.id}`\n"
        f"👤  *Your ID:* `{user.id}`\n"
        f"📂  *Type:* `{chat.type}`\n\n"
        f"_To use this as the admin group, set `ADMIN_GROUP_ID={chat.id}` in your secrets._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    # Allow from admin group OR admin user in DM
    if not is_admin_group(update) and uid not in ADMIN_USER_IDS:
        if not update.message or not update.effective_chat or update.effective_chat.type != "private":
            return
        chat_id = update.effective_chat.id
        await update.message.reply_text(
            f"❌  *Access denied.*\n\n"
            f"This chat ID is `{chat_id}`.\n"
            f"Admin group is configured as `{ADMIN_GROUP_ID}`.\n\n"
            f"_If this is your admin group, update `ADMIN_GROUP_ID` to `{chat_id}` in your secrets._",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        panel_text(), parse_mode=ParseMode.MARKDOWN, reply_markup=panel_keyboard()
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show a formatted cheat sheet of NL commands."""
    uid = update.effective_user.id if update.effective_user else None
    if not is_admin_group(update) and uid not in ADMIN_USER_IDS:
        return
    await update.message.reply_text(
        "🛡️  *Valkyrie Admin — Natural Language Guide*\n"
        "─────────────────────────────\n\n"
        "Just type naturally. Here are some examples:\n\n"
        "📊  *Analytics*\n"
        "   `stats`\n"
        "   `activity log`\n"
        "   `top users by points`\n\n"
        "👥  *Users*\n"
        "   `show all sellers`\n"
        "   `list buyers`\n"
        "   `pending approvals`\n"
        "   `lookup @username`\n\n"
        "🔧  *Moderation*\n"
        "   `warn @user they were rude`\n"
        "   `ban @user for scamming`\n"
        "   `approve @newuser`\n"
        "   `reject @seller`\n"
        "   `mute @user`\n"
        "   `remove @user`\n\n"
        "📢  *Communications*\n"
        "   `broadcast: market opens at 9am`\n"
        "   `show referral leaderboard`\n\n"
        "🎮  *Engagement*\n"
        "   `draw lottery winner`\n"
        "   `clear lottery entries`\n"
        "   `show open disputes`\n\n"
        "⚙️  *System*\n"
        "   `add keyword hash 🌿`\n"
        "   `remove keyword hash`\n"
        "   `list keywords`\n\n"
        "─────────────────────────────\n"
        "Or tap /panel for the button interface.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠  Open Panel", callback_data="adm_panel")
        ]])
    )


# ── Button handler ─────────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cid = q.message.chat.id
    uid = q.from_user.id if q.from_user else None
    is_admin = (cid in ADMIN_ID_VARIANTS) or (uid in ADMIN_USER_IDS)
    if not is_admin:
        # Handle approve/reject seller from any chat the notification landed in
        if q.data.startswith(("approve_seller:", "reject_seller:")):
            await _handle_seller_approval(q, context)
        return
    data = q.data
    back_btn = [[InlineKeyboardButton("◀️  Back to Panel", callback_data="adm_panel")]]

    if data == "adm_panel":
        await q.edit_message_text(panel_text(), parse_mode=ParseMode.MARKDOWN, reply_markup=panel_keyboard())

    elif data == "show_help":
        help_text = (
            "🛡️  *Valkyrie Admin — Command Guide*\n"
            "─────────────────────────────\n\n"
            "📊  *Analytics*\n"
            "   `stats`  ·  `activity log`  ·  `top users`\n\n"
            "👥  *Users*\n"
            "   `show all sellers`  ·  `list buyers`\n"
            "   `pending approvals`  ·  `lookup @user`\n\n"
            "🔧  *Moderation*\n"
            "   `warn @user reason`  ·  `ban @user reason`\n"
            "   `approve @user`  ·  `reject @user`\n"
            "   `mute @user`  ·  `remove @user`\n\n"
            "📢  *Communications*\n"
            "   `broadcast: your message here`\n"
            "   `show referral leaderboard`\n\n"
            "🎮  *Engagement*\n"
            "   `draw lottery winner`  ·  `clear lottery`\n"
            "   `show open disputes`\n\n"
            "⚙️  *System*\n"
            "   `add keyword word 🌿`  ·  `remove keyword word`\n"
            "   `list keywords`\n\n"
            "─────────────────────────────\n"
            "_Type any command above, or use the panel._"
        )
        await q.edit_message_text(
            help_text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠  Panel", callback_data="adm_panel")
            ]])
        )

    elif data == "adm_stats":
        s, pending, b, tr, ac, rat, avg = get_stats()
        rate_pct = round(ac / tr * 100, 1) if tr else 0
        now = datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC")
        text = (
            f"📊  *Statistics*\n"
            f"_{now}_\n"
            f"{'─' * 28}\n\n"
            f"👥  *Users*\n"
            f"   🏪 Sellers (active): *{s}*\n"
            f"   ⏳ Sellers (pending): *{pending}*\n"
            f"   🛒 Buyers: *{b}*\n\n"
            f"📦  *Marketplace*\n"
            f"   Total requests: *{tr}*\n"
            f"   Accepted: *{ac}* ({rate_pct}%)\n"
            f"   Open: *{tr - ac}*\n\n"
            f"⭐  *Ratings*\n"
            f"   Total reviews: *{rat}*\n"
            f"   Average score: *{avg} / 5.0*"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_approvals":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT telegram_id, username, full_name, registered_at
                FROM users WHERE role='seller' AND status='pending'
                ORDER BY registered_at
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await q.edit_message_text(
                "✅  *No pending applications.*\n\n_All sellers have been reviewed._",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(back_btn)
            )
            return
        lines = [f"✅  *Seller Approvals*\n_{len(rows)} pending review_\n{'─' * 24}\n"]
        buttons = []
        for r in rows:
            name = r["full_name"] or r["username"] or str(r["telegram_id"])
            uname = f"@{r['username']}" if r["username"] else f"ID: `{r['telegram_id']}`"
            dt = r["registered_at"].strftime("%d %b  %H:%M")
            lines.append(f"👤  *{name}*  ({uname})\n    Applied: {dt}")
            buttons.append([
                InlineKeyboardButton(f"✅  Approve",  callback_data=f"approve_seller:{r['telegram_id']}"),
                InlineKeyboardButton(f"❌  Reject",   callback_data=f"reject_seller:{r['telegram_id']}"),
            ])
        buttons.append(back_btn[0])
        await q.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("approve_seller:") or data.startswith("reject_seller:"):
        await _handle_seller_approval(q, context)

    elif data == "adm_sellers":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT u.telegram_id, u.username, u.full_name, u.status,
                       ROUND(AVG(r.stars)::numeric,1) as avg_r,
                       COUNT(DISTINCT r.id) as rcnt,
                       COALESCE(string_agg(DISTINCT sp.product_keyword, ', '), 'none') as products
                FROM users u
                LEFT JOIN ratings r ON r.seller_id=u.telegram_id
                LEFT JOIN seller_products sp ON sp.seller_id=u.telegram_id
                WHERE u.role='seller'
                GROUP BY u.telegram_id, u.username, u.full_name, u.status
                ORDER BY avg_r DESC NULLS LAST
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            text = "🏪 No sellers registered."
        else:
            lines = ["🏪 *All Sellers:*\n"]
            for r in rows:
                name = r["full_name"] or r["username"] or str(r["telegram_id"])
                uname = f"@{r['username']}" if r["username"] else f"ID:`{r['telegram_id']}`"
                avg = float(r["avg_r"]) if r["avg_r"] else 0
                cnt = r["rcnt"] or 0
                status = "⏳" if r["status"] == "pending" else ("🚫" if r["status"] == "banned" else "✅")
                lines.append(f"• {status} *{name}* ({uname})\n  {stars_str(avg, cnt)}\n  📦 {r['products']}")
            text = "\n".join(lines)
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))
        except Exception:
            await q.edit_message_text(text[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_buyers":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT u.telegram_id, u.username, u.full_name,
                       COUNT(pr.id) as req_count
                FROM users u
                LEFT JOIN product_requests pr ON pr.buyer_id=u.telegram_id
                WHERE u.role='buyer'
                GROUP BY u.telegram_id, u.username, u.full_name
                ORDER BY req_count DESC
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            text = "🛒 No buyers registered."
        else:
            lines = ["🛒 *All Buyers:*\n"]
            for r in rows:
                name = r["full_name"] or r["username"] or str(r["telegram_id"])
                uname = f"@{r['username']}" if r["username"] else f"ID:`{r['telegram_id']}`"
                lines.append(f"• *{name}* ({uname}) — {r['req_count']} requests")
            text = "\n".join(lines)
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))
        except Exception:
            await q.edit_message_text(text[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_requests":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT pr.id, pr.product_keyword, pr.status, pr.created_at,
                       u.username as buyer_username
                FROM product_requests pr
                JOIN users u ON u.telegram_id=pr.buyer_id
                ORDER BY pr.created_at DESC LIMIT 20
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            text = "📋 No requests yet."
        else:
            lines = ["📋 *Recent Requests (last 20):*\n"]
            for r in rows:
                buyer = f"@{r['buyer_username']}" if r["buyer_username"] else "unknown"
                icon = {"accepted": "✅", "expired": "⏰", "pending": "⏳"}.get(r["status"], "❓")
                dt = r["created_at"].strftime("%m/%d %H:%M")
                lines.append(f"{icon} `#{r['id']}` | *{r['product_keyword']}* | {buyer} | {dt}")
            text = "\n".join(lines)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_activity":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT event_type, user_id, description, created_at
                FROM activity_log ORDER BY created_at DESC LIMIT 25
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            text = "📜 No activity recorded yet."
        else:
            icons = {
                "seller_registered": "🏪", "buyer_registered": "🛒",
                "request_created": "📦", "request_accepted": "✅",
                "request_expired": "⏰", "dispute_opened": "🚨",
                "rating_given": "⭐",
            }
            lines = ["📜 *Recent Activity (last 25):*\n"]
            for r in rows:
                icon = icons.get(r["event_type"], "•")
                dt = r["created_at"].strftime("%m/%d %H:%M")
                lines.append(f"{icon} `{dt}` {r['description']}")
            text = "\n".join(lines)
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))
        except Exception:
            await q.edit_message_text(text[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_report_suspects":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT user_id, username, full_name, chat_title, joined_at, left_at
                FROM group_joins WHERE flagged=TRUE
                ORDER BY joined_at DESC LIMIT 20
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            text = "🕵️ No report suspects detected yet.\n\nAdd this bot to your marketplace groups to start monitoring."
        else:
            lines = ["🕵️ *Suspected Reporters (joined & left quickly):*\n"]
            for r in rows:
                name = r["full_name"] or r["username"] or str(r["user_id"])
                uname = f"@{r['username']}" if r["username"] else f"ID:`{r['user_id']}`"
                dt = r["joined_at"].strftime("%m/%d %H:%M")
                stayed = ""
                if r["left_at"]:
                    secs = int((r["left_at"] - r["joined_at"]).total_seconds())
                    stayed = f" · stayed {secs}s"
                lines.append(f"🚩 *{name}* ({uname})\n  Group: {r['chat_title']} · {dt}{stayed}")
            text = "\n".join(lines)
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))
        except Exception:
            await q.edit_message_text(text[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_export":
        await q.edit_message_text(
            "📤 *Export Data*\n\nChoose what to export:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Users CSV", callback_data="export_users")],
                [InlineKeyboardButton("📦 Requests CSV", callback_data="export_requests")],
                [InlineKeyboardButton("◀️ Back", callback_data="adm_panel")],
            ])
        )

    elif data == "export_users":
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT telegram_id, username, full_name, role, status, registered_at FROM users ORDER BY registered_at")
            rows = cur.fetchall()
            cur.close()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["telegram_id", "username", "full_name", "role", "status", "registered_at"])
        w.writerows(rows)
        buf.seek(0)
        await context.bot.send_document(
            chat_id=q.message.chat.id,
            document=buf.read().encode(),
            filename=f"users_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            caption="👥 Users export"
        )
        await q.edit_message_text("✅ Users CSV sent above.", reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "export_requests":
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT pr.id, pr.product_keyword, pr.status, pr.created_at,
                       u.username, u.full_name
                FROM product_requests pr JOIN users u ON u.telegram_id=pr.buyer_id
                ORDER BY pr.created_at DESC
            """)
            rows = cur.fetchall()
            cur.close()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "product", "status", "created_at", "buyer_username", "buyer_name"])
        w.writerows(rows)
        buf.seek(0)
        await context.bot.send_document(
            chat_id=q.message.chat.id,
            document=buf.read().encode(),
            filename=f"requests_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            caption="📦 Requests export"
        )
        await q.edit_message_text("✅ Requests CSV sent above.", reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_search":
        context.user_data["action"] = AWAITING_SEARCH
        await q.edit_message_text(
            "🔍 *User Search*\n\nReply with a @username or numeric ID:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_panel")]]),
        )

    elif data == "adm_warn":
        context.user_data["action"] = AWAITING_WARN
        await q.edit_message_text(
            "⚠️ *Warn User*\n\nReply with: `@username <reason>`\n_e.g. `@johndoe rule violation`_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_panel")]]),
        )

    elif data == "adm_ban":
        context.user_data["action"] = AWAITING_BAN
        await q.edit_message_text(
            "🚫 *Ban Seller*\n\nReply with the seller's @username or numeric ID:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_panel")]]),
        )

    elif data == "adm_remove":
        context.user_data["action"] = AWAITING_REMOVE
        await q.edit_message_text(
            "❌ *Remove User*\n\nReply with the user's @username or numeric ID:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_panel")]]),
        )

    elif data == "adm_broadcast":
        context.user_data["action"] = AWAITING_BROADCAST
        await q.edit_message_text(
            "📢 *Broadcast Message*\n\nType the message to send to ALL registered users:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_panel")]]),
        )

    elif data == "adm_lottery":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT user_id, username, full_name, entered_at FROM lottery_entries ORDER BY entered_at")
            entries = cur.fetchall()
            cur.close()
        count = len(entries)
        if count == 0:
            text = "🎰 *Lottery*\n\nNo entries yet.\nUsers can type `/join` in the marketplace bot to enter."
            buttons = [[InlineKeyboardButton("◀️ Back", callback_data="adm_panel")]]
        else:
            lines = [f"🎰 *Lottery — {count} entries:*\n"]
            for e in entries[:20]:
                name = e["full_name"] or e["username"] or str(e["user_id"])
                lines.append(f"• {name}")
            if count > 20:
                lines.append(f"_...and {count - 20} more_")
            text = "\n".join(lines)
            buttons = [
                [InlineKeyboardButton("🏆 Draw Winner", callback_data="lottery_draw")],
                [InlineKeyboardButton("🗑️ Clear All Entries", callback_data="lottery_clear")],
                [InlineKeyboardButton("◀️ Back", callback_data="adm_panel")],
            ]
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "lottery_draw":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT user_id, username, full_name FROM lottery_entries ORDER BY RANDOM() LIMIT 1")
            winner = cur.fetchone()
            cur.close()
        if not winner:
            await q.answer("No entries in the lottery!", show_alert=True)
            return
        name = winner["full_name"] or winner["username"] or str(winner["user_id"])
        uname = f"@{winner['username']}" if winner["username"] else f"ID: `{winner['user_id']}`"
        await q.edit_message_text(
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎉 *Lottery Winner!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏆 *{name}* ({uname})\n\n"
            "_Announce this in your group and notify the winner!_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Clear & Start New", callback_data="lottery_clear")],
                [InlineKeyboardButton("◀️ Back", callback_data="adm_lottery")],
            ])
        )
        try:
            await context.bot.send_message(
                chat_id=winner["user_id"],
                text=(
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🎉 *You Won the Lottery!*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "Congratulations! An admin will be in contact with your prize."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    elif data == "lottery_clear":
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM lottery_entries")
            cur.close()
        await q.edit_message_text(
            "✅ Lottery cleared. Users can enter a new round with `/join`.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎰 Lottery", callback_data="adm_lottery")]])
        )

    elif data == "adm_rankings":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT telegram_id, username, full_name, role, points
                FROM users WHERE points > 0 ORDER BY points DESC LIMIT 20
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            text = "🏆 No activity points recorded yet."
        else:
            medals = ["🥇","🥈","🥉"] + ["🏅"] * 17
            lines = ["🏆 *Activity Leaderboard (Top 20)*\n"]
            for i, r in enumerate(rows):
                name = r["full_name"] or r["username"] or str(r["telegram_id"])
                role_icon = "🏪" if r["role"] == "seller" else "🛒"
                lines.append(f"{medals[i]} {role_icon} *{name}* — {r['points']} pts")
            text = "\n".join(lines)
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))
        except Exception:
            await q.edit_message_text(text[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_referrals":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT r.telegram_id, r.username, r.full_name, r.points,
                       COUNT(u.telegram_id) as referral_count
                FROM users r JOIN users u ON u.referrer_id=r.telegram_id
                GROUP BY r.telegram_id, r.username, r.full_name, r.points
                ORDER BY referral_count DESC LIMIT 15
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            text = "🔗 No referrals recorded yet."
        else:
            lines = ["🔗 *Top Referrers*\n"]
            for r in rows:
                name = r["full_name"] or r["username"] or str(r["telegram_id"])
                uname = f"@{r['username']}" if r["username"] else ""
                lines.append(f"• *{name}* {uname} — {r['referral_count']} referrals · {r['points']} pts")
            text = "\n".join(lines)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(back_btn))

    elif data == "adm_keywords":
        kws = load_keywords(force=True)
        if not kws:
            text = (
                "🔤 *Keyword → Emoji Replacer*\n\n"
                "No keywords configured yet.\n\n"
                "_When a group member posts a message containing a keyword,\n"
                "it is replaced with the emoji and the corrected version is\n"
                "sent back, asking them to repost._"
            )
            buttons = [
                [InlineKeyboardButton("➕ Add Keyword", callback_data="kw_add")],
                [InlineKeyboardButton("◀️ Back", callback_data="adm_panel")],
            ]
        else:
            lines = [f"🔤 *Keyword → Emoji ({len(kws)} rules):*\n"]
            buttons = []
            with get_db() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT id, keyword, emoji FROM keyword_emojis ORDER BY keyword")
                rows = cur.fetchall()
                cur.close()
            for r in rows:
                lines.append(f"• `{r['keyword']}` → {r['emoji']}")
                buttons.append([
                    InlineKeyboardButton(
                        f"🗑️ {r['keyword']} {r['emoji']}",
                        callback_data=f"kw_del:{r['id']}"
                    )
                ])
            buttons.append([InlineKeyboardButton("➕ Add Keyword", callback_data="kw_add")])
            buttons.append([InlineKeyboardButton("◀️ Back", callback_data="adm_panel")])
            text = "\n".join(lines)
        await q.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data == "kw_add":
        context.user_data["action"] = AWAITING_KEYWORD
        await q.edit_message_text(
            "🔤 *Add Keyword Rule*\n\n"
            "Reply with the keyword and emoji separated by a space:\n\n"
            "*Examples:*\n"
            "`hash 🌿`\n"
            "`weed 🌿`\n"
            "`cocaine ❄️`\n"
            "`mdma 💊`\n"
            "`escort 💋`\n\n"
            "_The keyword is matched case-insensitively inside messages._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="adm_keywords")
            ]]),
        )

    elif data.startswith("kw_del:"):
        kw_id = int(data.split(":", 1)[1])
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM keyword_emojis WHERE id=%s RETURNING keyword, emoji", (kw_id,))
            deleted = cur.fetchone()
            cur.close()
        load_keywords(force=True)  # bust cache
        if deleted:
            await q.answer(f"Deleted: {deleted[0]} → {deleted[1]}", show_alert=False)
        # Reload the keywords page
        kws = load_keywords()
        if not kws:
            await q.edit_message_text(
                "🔤 *Keyword → Emoji Replacer*\n\nAll keywords removed.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add Keyword", callback_data="kw_add")],
                    [InlineKeyboardButton("◀️ Back", callback_data="adm_panel")],
                ])
            )
        else:
            with get_db() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT id, keyword, emoji FROM keyword_emojis ORDER BY keyword")
                rows = cur.fetchall()
                cur.close()
            lines = [f"🔤 *Keyword → Emoji ({len(rows)} rules):*\n"]
            btns = []
            for r in rows:
                lines.append(f"• `{r['keyword']}` → {r['emoji']}")
                btns.append([InlineKeyboardButton(f"🗑️ {r['keyword']} {r['emoji']}", callback_data=f"kw_del:{r['id']}")])
            btns.append([InlineKeyboardButton("➕ Add Keyword", callback_data="kw_add")])
            btns.append([InlineKeyboardButton("◀️ Back", callback_data="adm_panel")])
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(btns))

    elif data == "adm_settings":
        group_link     = get_setting("group_link", "_(not set)_")
        join_chat_id   = get_setting("force_join_chat_id", "_(not set — verification disabled)_")
        text = (
            "⚙️ *Bot Settings*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔗 *Group Invite Link*\n"
            f"`{group_link}`\n"
            "_The link shown in the 'Join Required' gate._\n\n"
            "🛡️ *Force-Join Channel ID*\n"
            f"`{join_chat_id}`\n"
            "_Numeric ID of the channel/group the bot verifies membership in._\n"
            "_Get it by sending /id in the group with @valkyriegroupmod\\_bot._\n"
            "_Leave empty to use trust-based joining (no real verification)._\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Set Group Link", callback_data="set_group_link")],
                [InlineKeyboardButton("🛡️ Set Channel ID", callback_data="set_join_chat_id")],
                [InlineKeyboardButton("🗑️ Clear Channel ID", callback_data="clear_join_chat_id")],
                [InlineKeyboardButton("◀️ Back", callback_data="adm_panel")],
            ])
        )

    elif data == "set_group_link":
        context.user_data["action"] = AWAITING_SETTING
        context.user_data["setting_key"] = "group_link"
        await q.edit_message_text(
            "🔗 *Set Group Invite Link*\n\n"
            "Reply with the full invite link:\n"
            "_e.g._ `https://t.me/+abcXYZ123`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_settings")]]),
        )

    elif data == "set_join_chat_id":
        context.user_data["action"] = AWAITING_SETTING
        context.user_data["setting_key"] = "force_join_chat_id"
        await q.edit_message_text(
            "🛡️ *Set Force-Join Channel ID*\n\n"
            "Reply with the numeric chat ID of the channel/group where you want to verify membership.\n\n"
            "How to get it:\n"
            "1. Add @valkyriegroupmod\\_bot to your marketplace group\n"
            "2. Send `/id` in that group\n"
            "3. Copy the *Chat ID* number (it will be negative, like `-1001234567890`)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="adm_settings")]]),
        )

    elif data == "clear_join_chat_id":
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM bot_settings WHERE key='force_join_chat_id'")
            cur.close()
        await q.answer("✅ Channel ID cleared — verification disabled", show_alert=False)
        # Reload settings page
        group_link = get_setting("group_link", "_(not set)_")
        await q.edit_message_text(
            "⚙️ *Bot Settings*\n\n"
            "🔗 *Group Invite Link:* " + f"`{group_link}`\n"
            "🛡️ *Force-Join Channel ID:* `_(not set — verification disabled)_`\n\n"
            "_Verification is now trust-based (user self-confirms join)._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Set Group Link", callback_data="set_group_link")],
                [InlineKeyboardButton("🛡️ Set Channel ID", callback_data="set_join_chat_id")],
                [InlineKeyboardButton("◀️ Back", callback_data="adm_panel")],
            ])
        )

    elif data == "adm_scripts":
        SCRIPTS_DIR.mkdir(exist_ok=True)
        scripts = sorted(SCRIPTS_DIR.glob("*.py"))
        header = (
            "🐍  *Script Runner*\n"
            f"_{len(scripts)} script{'s' if len(scripts) != 1 else ''} available_\n"
            f"{'─' * 24}\n\n"
        )
        if not scripts:
            header += "_No scripts yet._\n\nUpload a `.py` file to this chat, or tap Write Script to create one inline."
        else:
            header += "\n".join(f"• `{s.name}`" for s in scripts)

        buttons = []
        for s in scripts:
            buttons.append([
                InlineKeyboardButton(f"▶️  {s.name}",         callback_data=f"run:{s.name}"),
                InlineKeyboardButton("🗑️",                    callback_data=f"del_script:{s.name}"),
            ])
        buttons.append([InlineKeyboardButton("✏️  Write Script Inline", callback_data="script_write")])
        buttons.append(back_btn[0])
        await q.edit_message_text(
            header, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif data == "script_write":
        context.user_data["action"] = AWAITING_SCRIPT
        await q.edit_message_text(
            "✏️  *Write a Python Script*\n"
            f"{'─' * 24}\n\n"
            "Send your Python code as a message.\n\n"
            "_Tips:_\n"
            "• `print()` output is returned to you\n"
            "• `DATABASE_URL` and all env vars are available\n"
            "• Runs with a 30s timeout\n"
            "• The script is saved and can be run again later\n\n"
            "Example:\n"
            "```\n"
            "import os, psycopg2\n"
            "conn = psycopg2.connect(os.environ['DATABASE_URL'])\n"
            "cur = conn.cursor()\n"
            "cur.execute('SELECT COUNT(*) FROM users')\n"
            "print('Total users:', cur.fetchone()[0])\n"
            "```",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌  Cancel", callback_data="adm_scripts")
            ]])
        )

    elif data.startswith("del_script:"):
        name = data.split(":", 1)[1]
        path = SCRIPTS_DIR / name
        if path.exists():
            path.unlink()
            await q.answer(f"🗑️ {name} deleted.", show_alert=False)
        # Refresh the scripts list
        SCRIPTS_DIR.mkdir(exist_ok=True)
        scripts = sorted(SCRIPTS_DIR.glob("*.py"))
        header = (
            "🐍  *Script Runner*\n"
            f"_{len(scripts)} script{'s' if len(scripts) != 1 else ''} available_\n"
            f"{'─' * 24}\n\n"
        )
        if not scripts:
            header += "_No scripts yet._\n\nUpload a `.py` file or tap Write Script."
        else:
            header += "\n".join(f"• `{s.name}`" for s in scripts)
        buttons = []
        for s in scripts:
            buttons.append([
                InlineKeyboardButton(f"▶️  {s.name}", callback_data=f"run:{s.name}"),
                InlineKeyboardButton("🗑️",            callback_data=f"del_script:{s.name}"),
            ])
        buttons.append([InlineKeyboardButton("✏️  Write Script Inline", callback_data="script_write")])
        buttons.append(back_btn[0])
        await q.edit_message_text(
            header, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif data.startswith("run:"):
        name = data.split(":", 1)[1]
        path = SCRIPTS_DIR / name
        if not path.exists():
            await q.answer("⚠️ Script not found — it may have been deleted.", show_alert=True)
            return
        await q.edit_message_text(
            f"🐍  *Running* `{name}`\n⏳ Please wait…",
            parse_mode=ParseMode.MARKDOWN
        )
        loop = asyncio.get_running_loop()
        output = await loop.run_in_executor(None, _run_script_sync, path)
        out_display = output[:3600] if len(output) > 3600 else output
        await q.edit_message_text(
            f"🐍  *Output:* `{name}`\n{'─' * 24}\n```\n{out_display}\n```",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("▶️  Run Again",  callback_data=f"run:{name}"),
                    InlineKeyboardButton("🗑️  Delete",     callback_data=f"del_script:{name}"),
                ],
                [InlineKeyboardButton("◀️  Back to Scripts", callback_data="adm_scripts")],
            ]),
        )

    elif data.startswith("confirm_ban:") or data.startswith("confirm_ban_id:"):
        if data.startswith("confirm_ban_id:"):
            ref = data.split(":", 1)[1]
            by_id = True
        else:
            ref = data.split(":", 1)[1]
            by_id = False
        with get_db() as conn:
            cur = conn.cursor()
            if by_id:
                cur.execute(
                    "DELETE FROM users WHERE telegram_id=%s AND role='seller' RETURNING telegram_id, username",
                    (ref,)
                )
            else:
                cur.execute(
                    "DELETE FROM users WHERE (username=%s OR telegram_id::text=%s) AND role='seller' RETURNING telegram_id, username",
                    (ref, ref)
                )
            deleted = cur.fetchone()
            cur.close()
        if deleted:
            await q.edit_message_text(
                f"✅ Seller `{deleted[0]}` (@{deleted[1]}) banned.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")]]),
            )
            try:
                await context.bot.send_message(
                    chat_id=deleted[0],
                    text="⛔ You have been banned from the marketplace by an admin."
                )
            except Exception:
                pass
        else:
            await q.edit_message_text(
                "❌ Seller not found.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")]])
            )

    elif data.startswith("confirm_remove:"):
        ref = data.split(":", 1)[1]
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM users WHERE username=%s OR telegram_id::text=%s RETURNING telegram_id",
                (ref, ref)
            )
            deleted = cur.fetchone()
            cur.close()
        text = f"✅ User `{deleted[0]}` removed." if deleted else "❌ User not found."
        await q.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")]]),
        )


async def _handle_seller_approval(q, context):
    """Shared logic for approve/reject buttons that can appear in admin group or DM."""
    action, uid_str = q.data.split(":", 1)
    uid = int(uid_str)
    approved = action == "approve_seller"

    with get_db() as conn:
        cur = conn.cursor()
        new_status = "approved" if approved else "banned"
        cur.execute(
            "UPDATE users SET status=%s WHERE telegram_id=%s AND role='seller' RETURNING username, full_name",
            (new_status, uid)
        )
        row = cur.fetchone()
        cur.close()

    if not row:
        await q.edit_message_text("❌ Seller not found (may have been removed).")
        return

    name = row[1] or row[0] or str(uid)
    seller_bot_username = os.environ.get("SELLER_BOT_USERNAME", "valkyriesellerbuyer_bot")

    if approved:
        result_text = f"✅ *{name}* approved as a seller!"
        user_msg = (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ *Seller Account Approved!*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "You can now list products and receive buyer requests.\n\n"
            "Tap *Open Seller Menu* below to get started 👇"
        )
        user_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🏪 Open Seller Menu",
                url=f"https://t.me/{seller_bot_username}?start=menu",
            )],
        ])
    else:
        result_text = f"❌ *{name}* rejected."
        user_msg = (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⛔ *Application Not Approved*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Your seller application was not approved by the admin team.\n"
            "You may re-apply by contacting an admin."
        )
        user_markup = None

    await q.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN)
    try:
        await context.bot.send_message(
            chat_id=uid,
            text=user_msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=user_markup,
        )
    except Exception as e:
        logger.warning(f"Could not notify seller {uid}: {e}")


# ── Natural Language Admin Dispatcher ─────────────────────────────────────────
#
#  Intercepts free-text messages in the admin DM / admin group and routes them
#  to the correct admin function using the LLM for intent classification.
#  The LLM returns a single JSON object; we parse it and execute locally.

_NL_SYSTEM = """
You are the admin AI for a Telegram dual-bot marketplace platform.
You receive plain-text commands from the admin and return ONLY a JSON object — no prose, no markdown, no explanation.

Return ONLY this exact JSON structure:
{"intent": "<action>", "params": {}, "reply": "<optional human-readable note>"}

Available intents and their params:
  stats            {}                                         → Platform-wide statistics
  list_sellers     {}                                         → All sellers
  list_buyers      {}                                         → All buyers
  list_requests    {"status": "open|accepted|all"}            → Product requests
  list_approvals   {}                                         → Pending seller approvals
  list_activity    {}                                         → Recent activity log
  list_rankings    {}                                         → Top users by points
  list_lottery     {}                                         → Lottery entrants
  list_referrals   {}                                         → Top referrers
  list_disputes    {}                                         → Open disputes
  list_keywords    {}                                         → Keyword→emoji rules
  search_user      {"ref": "@username_or_numeric_id"}         → Look up a user
  ban_user         {"ref": "@username_or_id", "reason": "…"} → Ban a seller
  warn_user        {"ref": "@username_or_id", "reason": "…"} → Warn a user
  approve_seller   {"ref": "@username_or_id"}                 → Approve pending seller
  reject_seller    {"ref": "@username_or_id"}                 → Reject pending seller
  mute_user        {"ref": "@username_or_id"}                 → Mute notifications for user
  unmute_user      {"ref": "@username_or_id"}                 → Unmute a user
  remove_user      {"ref": "@username_or_id"}                 → Permanently delete user
  broadcast        {"text": "…"}                              → Broadcast to ALL users
  lottery_draw     {}                                         → Draw a random lottery winner
  lottery_clear    {}                                         → Clear all lottery entries
  add_keyword      {"keyword": "word", "emoji": "🌿"}         → Add keyword→emoji rule
  del_keyword      {"keyword": "word"}                        → Remove a keyword rule
  panel            {}                                         → Show admin panel
  answer           {"reply": "…"}                             → Answer question directly

Pick the most specific intent. Use "answer" for general questions.
All params values must be plain strings. Omit optional params if not provided.
"""


def _safe_parse_nl(raw: str) -> dict:
    """Extract JSON from LLM response, tolerating markdown code fences."""
    import json, re
    raw = raw.strip()
    # Strip ```json ... ``` or ``` ... ```
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    # Find first {...}
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {"intent": "answer", "params": {}, "reply": raw[:500]}


async def _nl_admin_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route a free-text admin message to the right function via LLM intent classification."""
    msg   = update.message
    text  = msg.text.strip()
    bot   = context.bot

    await msg.chat.send_action("typing")

    # ── Classify intent ──────────────────────────────────────────────────────
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from llm_chat import chat_once
        raw = await asyncio.get_event_loop().run_in_executor(
            None, lambda: chat_once(text, system_override=_NL_SYSTEM)
        )
        obj = _safe_parse_nl(raw)
    except Exception as e:
        logger.error(f"NL dispatch LLM error: {e}")
        obj = {"intent": "answer", "params": {}, "reply": "⚠️ AI unavailable. Use /panel for the button interface."}

    intent = obj.get("intent", "answer")
    params = obj.get("params") or {}
    hint   = obj.get("reply", "")

    back_btn = [[InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")]]

    async def send(text_out: str, kbd=None):
        await msg.reply_text(
            text_out,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(kbd or back_btn),
        )

    # ── Execute intent ───────────────────────────────────────────────────────

    if intent == "panel":
        await msg.reply_text(panel_text(), parse_mode=ParseMode.MARKDOWN, reply_markup=panel_keyboard())

    elif intent == "stats":
        s, pending, b, tr, ac, rat, avg = get_stats()
        rate_pct = round(ac / tr * 100, 1) if tr else 0
        await send(
            f"📊 *Platform Statistics*\n\n"
            f"🏪 Sellers: *{s}* active · ⏳ *{pending}* pending\n"
            f"🛒 Buyers: *{b}*\n"
            f"📦 Requests: *{tr}* total · ✅ *{ac}* accepted ({rate_pct}%)\n"
            f"⭐ Ratings: *{rat}* · Avg *{avg}/5*"
        )

    elif intent == "list_sellers":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT u.telegram_id, u.username, u.full_name, u.status,
                       ROUND(AVG(r.stars)::numeric,1) as avg_r,
                       COUNT(DISTINCT r.id) as rcnt,
                       COALESCE(string_agg(DISTINCT sp.product_keyword, ', '), 'none') as products
                FROM users u
                LEFT JOIN ratings r ON r.seller_id=u.telegram_id
                LEFT JOIN seller_products sp ON sp.seller_id=u.telegram_id
                WHERE u.role='seller'
                GROUP BY u.telegram_id, u.username, u.full_name, u.status
                ORDER BY avg_r DESC NULLS LAST
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await send("🏪 No sellers registered yet.")
            return
        lines = [f"🏪 *All Sellers ({len(rows)}):*\n"]
        for r in rows:
            name = r["full_name"] or r["username"] or str(r["telegram_id"])
            uname = f"@{r['username']}" if r["username"] else f"ID:`{r['telegram_id']}`"
            avg = float(r["avg_r"]) if r["avg_r"] else 0
            icon = "⏳" if r["status"] == "pending" else ("🚫" if r["status"] == "banned" else "✅")
            lines.append(f"{icon} *{name}* ({uname}) · {stars_str(avg, r['rcnt'] or 0)} · 📦 {r['products']}")
        await send("\n".join(lines)[:4000])

    elif intent == "list_buyers":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT u.telegram_id, u.username, u.full_name,
                       COUNT(pr.id) as req_count
                FROM users u
                LEFT JOIN product_requests pr ON pr.buyer_id=u.telegram_id
                WHERE u.role='buyer'
                GROUP BY u.telegram_id, u.username, u.full_name
                ORDER BY req_count DESC
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await send("🛒 No buyers registered yet.")
            return
        lines = [f"🛒 *All Buyers ({len(rows)}):*\n"]
        for r in rows:
            name = r["full_name"] or r["username"] or str(r["telegram_id"])
            uname = f"@{r['username']}" if r["username"] else f"ID:`{r['telegram_id']}`"
            lines.append(f"• *{name}* ({uname}) — {r['req_count']} requests")
        await send("\n".join(lines)[:4000])

    elif intent == "list_requests":
        status_filter = params.get("status", "all")
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            if status_filter == "open":
                cur.execute("""
                    SELECT pr.id, pr.product_keyword, pr.status, pr.created_at, u.username
                    FROM product_requests pr JOIN users u ON u.telegram_id=pr.buyer_id
                    WHERE pr.status='pending' ORDER BY pr.created_at DESC LIMIT 20
                """)
            elif status_filter == "accepted":
                cur.execute("""
                    SELECT pr.id, pr.product_keyword, pr.status, pr.created_at, u.username
                    FROM product_requests pr JOIN users u ON u.telegram_id=pr.buyer_id
                    WHERE pr.status='accepted' ORDER BY pr.created_at DESC LIMIT 20
                """)
            else:
                cur.execute("""
                    SELECT pr.id, pr.product_keyword, pr.status, pr.created_at, u.username
                    FROM product_requests pr JOIN users u ON u.telegram_id=pr.buyer_id
                    ORDER BY pr.created_at DESC LIMIT 20
                """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await send("📋 No requests found.")
            return
        lines = ["📋 *Recent Requests (last 20):*\n"]
        for r in rows:
            buyer = f"@{r['username']}" if r["username"] else "unknown"
            icon = {"accepted": "✅", "expired": "⏰", "pending": "⏳"}.get(r["status"], "❓")
            dt = r["created_at"].strftime("%m/%d %H:%M")
            lines.append(f"{icon} `#{r['id']}` *{r['product_keyword']}* · {buyer} · {dt}")
        await send("\n".join(lines))

    elif intent == "list_approvals":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT telegram_id, username, full_name, registered_at
                FROM users WHERE role='seller' AND status='pending' ORDER BY registered_at
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await send("✅ No pending seller applications.")
            return
        lines = [f"⏳ *Pending Approvals ({len(rows)}):*\n"]
        buttons = []
        for r in rows:
            name = r["full_name"] or r["username"] or str(r["telegram_id"])
            uname = f"@{r['username']}" if r["username"] else f"ID:`{r['telegram_id']}`"
            dt = r["registered_at"].strftime("%m/%d %H:%M")
            lines.append(f"• *{name}* ({uname}) — applied {dt}")
            buttons.append([
                InlineKeyboardButton(f"✅ {name[:18]}", callback_data=f"approve_seller:{r['telegram_id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_seller:{r['telegram_id']}"),
            ])
        buttons.append([InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")])
        await msg.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif intent == "list_activity":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT event_type, user_id, description, created_at FROM activity_log ORDER BY created_at DESC LIMIT 25")
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await send("📜 No activity recorded yet.")
            return
        icons = {"seller_registered": "🏪", "buyer_registered": "🛒", "request_created": "📦",
                 "request_accepted": "✅", "request_expired": "⏰", "dispute_opened": "🚨", "rating_given": "⭐"}
        lines = ["📜 *Recent Activity (last 25):*\n"]
        for r in rows:
            icon = icons.get(r["event_type"], "•")
            dt = r["created_at"].strftime("%m/%d %H:%M")
            lines.append(f"{icon} `{dt}` {r['description']}")
        await send("\n".join(lines)[:4000])

    elif intent == "list_rankings":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT telegram_id, username, full_name, role, points FROM users WHERE points>0 ORDER BY points DESC LIMIT 20")
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await send("🏆 No activity points recorded yet.")
            return
        medals = ["🥇","🥈","🥉"] + ["🏅"] * 17
        lines = ["🏆 *Activity Leaderboard (Top 20)*\n"]
        for i, r in enumerate(rows):
            name = r["full_name"] or r["username"] or str(r["telegram_id"])
            role_icon = "🏪" if r["role"] == "seller" else "🛒"
            lines.append(f"{medals[i]} {role_icon} *{name}* — {r['points']} pts")
        await send("\n".join(lines))

    elif intent == "list_lottery":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT user_id, username, full_name, entered_at FROM lottery_entries ORDER BY entered_at")
            entries = cur.fetchall()
            cur.close()
        count = len(entries)
        if count == 0:
            await send("🎰 No lottery entries yet.")
            return
        lines = [f"🎰 *Lottery — {count} entries:*\n"]
        for e in entries[:25]:
            name = e["full_name"] or e["username"] or str(e["user_id"])
            lines.append(f"• {name}")
        if count > 25:
            lines.append(f"_...and {count - 25} more_")
        await send(
            "\n".join(lines),
            kbd=[
                [InlineKeyboardButton("🏆 Draw Winner", callback_data="lottery_draw"),
                 InlineKeyboardButton("🗑️ Clear All", callback_data="lottery_clear")],
                [InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")],
            ]
        )

    elif intent == "list_referrals":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT r.telegram_id, r.username, r.full_name, r.points,
                       COUNT(u.telegram_id) as referral_count
                FROM users r JOIN users u ON u.referrer_id=r.telegram_id
                GROUP BY r.telegram_id, r.username, r.full_name, r.points
                ORDER BY referral_count DESC LIMIT 15
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await send("🔗 No referrals recorded yet.")
            return
        lines = ["🔗 *Top Referrers*\n"]
        for r in rows:
            name = r["full_name"] or r["username"] or str(r["telegram_id"])
            uname = f"@{r['username']}" if r["username"] else ""
            lines.append(f"• *{name}* {uname} — {r['referral_count']} referrals · {r['points']} pts")
        await send("\n".join(lines))

    elif intent == "list_disputes":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT d.id, d.reason, d.created_at,
                       b.username as buyer_uname, s.username as seller_uname
                FROM disputes d
                LEFT JOIN users b ON b.telegram_id=d.buyer_id
                LEFT JOIN users s ON s.telegram_id=d.seller_id
                WHERE d.status='open'
                ORDER BY d.created_at DESC LIMIT 20
            """)
            rows = cur.fetchall()
            cur.close()
        if not rows:
            await send("✅ No open disputes.")
            return
        lines = [f"🚨 *Open Disputes ({len(rows)}):*\n"]
        for r in rows:
            buyer = f"@{r['buyer_uname']}" if r["buyer_uname"] else "?"
            seller = f"@{r['seller_uname']}" if r["seller_uname"] else "?"
            dt = r["created_at"].strftime("%m/%d %H:%M")
            lines.append(f"• `#{r['id']}` {buyer} vs {seller} · _{r['reason'][:60]}_ · {dt}")
        await send("\n".join(lines))

    elif intent == "list_keywords":
        kws = load_keywords(force=True)
        if not kws:
            await send("🔤 No keyword rules configured yet.")
            return
        lines = [f"🔤 *Keyword Rules ({len(kws)}):*\n"]
        for kw, emoji in sorted(kws.items()):
            lines.append(f"• `{kw}` → {emoji}")
        await send("\n".join(lines)[:4000])

    elif intent == "search_user":
        ref = str(params.get("ref", "")).lstrip("@").split()[0] if params.get("ref") else ""
        if not ref:
            await send("❓ Which user? Say their @username or ID.")
            return
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT u.*,
                       ROUND(AVG(r.stars)::numeric,1) as avg_rating,
                       COUNT(DISTINCT r.id) as rating_count,
                       COUNT(DISTINCT pr.id) as req_count,
                       COUNT(DISTINCT rr.id) as deals_done,
                       (SELECT COUNT(*) FROM warnings w WHERE w.user_id=u.telegram_id) as warning_count
                FROM users u
                LEFT JOIN ratings r ON r.seller_id=u.telegram_id
                LEFT JOIN product_requests pr ON pr.buyer_id=u.telegram_id
                LEFT JOIN request_responses rr ON rr.seller_id=u.telegram_id
                WHERE u.username=%s OR u.telegram_id::text=%s
                GROUP BY u.telegram_id
            """, (ref, ref))
            user = cur.fetchone()
            cur.close()
        if not user:
            await send(f"❌ User `{ref}` not found.")
            return
        name = user["full_name"] or user["username"] or str(user["telegram_id"])
        uname = f"@{user['username']}" if user["username"] else f"ID: {user['telegram_id']}"
        avg = float(user["avg_rating"]) if user["avg_rating"] else 0
        status_map = {"approved": "✅ Approved", "pending": "⏳ Pending", "banned": "🚫 Banned"}
        muted = "🔕 Muted" if user.get("muted") else "🔔 Active"
        ref_id = user.get("username") or user["telegram_id"]
        await msg.reply_text(
            f"🔍 *User: {name}* ({uname})\n"
            f"🎭 Role: *{user['role']}* · {status_map.get(user['status'], user['status'])}\n"
            f"📅 Joined: {user['registered_at'].strftime('%Y-%m-%d')}\n"
            f"🔔 {muted} · ⭐ {stars_str(avg, int(user['rating_count'] or 0))}\n"
            f"📦 Requests: *{user['req_count']}* · 🤝 Deals: *{user['deals_done']}* · ⚠️ Warnings: *{user['warning_count']}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚠️ Warn", callback_data=f"warn_direct:{user['telegram_id']}"),
                    InlineKeyboardButton("🚫 Ban", callback_data=f"confirm_ban:{ref_id}"),
                    InlineKeyboardButton("❌ Remove", callback_data=f"confirm_remove:{ref_id}"),
                ],
                back_btn[0],
            ])
        )

    elif intent == "ban_user":
        ref = str(params.get("ref", "")).lstrip("@").split()[0] if params.get("ref") else ""
        reason = params.get("reason", "Admin action")
        if not ref:
            await send("❓ Who should I ban? Say their @username or ID.")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET status='banned' WHERE (username=%s OR telegram_id::text=%s) RETURNING telegram_id, username, full_name",
                (ref, ref)
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            await send(f"❌ User `{ref}` not found.")
            return
        tid, uname, fname = row
        name = fname or uname or str(tid)
        try:
            await bot.send_message(chat_id=tid, text=f"⛔ You have been banned from the marketplace.\n\nReason: {reason}")
        except Exception:
            pass
        await send(f"🚫 *{name}* (@{uname or tid}) has been banned.\nReason: _{reason}_")

    elif intent == "warn_user":
        ref = str(params.get("ref", "")).lstrip("@").split()[0] if params.get("ref") else ""
        reason = params.get("reason", "No reason given")
        if not ref:
            await send("❓ Who should I warn? Say their @username or ID.")
            return
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM users WHERE username=%s OR telegram_id::text=%s", (ref, ref))
            user = cur.fetchone()
            if user:
                cur.execute(
                    "INSERT INTO warnings(user_id, admin_id, reason) VALUES(%s,%s,%s)",
                    (user["telegram_id"], update.effective_user.id, reason)
                )
            cur.close()
        if not user:
            await send(f"❌ User `{ref}` not found.")
            return
        name = user["full_name"] or user["username"] or str(user["telegram_id"])
        try:
            await bot.send_message(
                chat_id=user["telegram_id"],
                text=f"⚠️ *Warning from marketplace admin:*\n\n_{reason}_\n\n_Further violations may result in a ban._",
                parse_mode=ParseMode.MARKDOWN,
            )
            notified = "✅ User notified."
        except Exception:
            notified = "⚠️ Could not DM user."
        await send(f"⚠️ Warning sent to *{name}*. {notified}")

    elif intent == "approve_seller":
        ref = str(params.get("ref", "")).lstrip("@").split()[0] if params.get("ref") else ""
        if not ref:
            await send("❓ Which seller? Say their @username or ID.")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET status='approved' WHERE role='seller' AND (username=%s OR telegram_id::text=%s) AND status='pending' RETURNING telegram_id, username, full_name",
                (ref, ref)
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            await send(f"❌ Pending seller `{ref}` not found (already approved/not seller?).")
            return
        tid, uname, fname = row
        name = fname or uname or str(tid)
        try:
            await bot.send_message(
                chat_id=tid,
                text="✅ *Your seller account has been approved!*\n\nUse /addproduct to add your first product.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        await send(f"✅ *{name}* approved as a seller!")

    elif intent == "reject_seller":
        ref = str(params.get("ref", "")).lstrip("@").split()[0] if params.get("ref") else ""
        if not ref:
            await send("❓ Which seller? Say their @username or ID.")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET status='banned' WHERE role='seller' AND (username=%s OR telegram_id::text=%s) RETURNING telegram_id, username, full_name",
                (ref, ref)
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            await send(f"❌ Seller `{ref}` not found.")
            return
        tid, uname, fname = row
        name = fname or uname or str(tid)
        try:
            await bot.send_message(chat_id=tid, text="⛔ Your seller application was not approved by the admin.")
        except Exception:
            pass
        await send(f"❌ *{name}*'s seller application rejected.")

    elif intent == "mute_user":
        ref = str(params.get("ref", "")).lstrip("@").split()[0] if params.get("ref") else ""
        if not ref:
            await send("❓ Who should I mute?")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET muted=TRUE WHERE username=%s OR telegram_id::text=%s RETURNING telegram_id, username",
                (ref, ref)
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            await send(f"❌ User `{ref}` not found.")
            return
        await send(f"🔕 User @{row[1] or row[0]} muted (no more notifications).")

    elif intent == "unmute_user":
        ref = str(params.get("ref", "")).lstrip("@").split()[0] if params.get("ref") else ""
        if not ref:
            await send("❓ Who should I unmute?")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET muted=FALSE WHERE username=%s OR telegram_id::text=%s RETURNING telegram_id, username",
                (ref, ref)
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            await send(f"❌ User `{ref}` not found.")
            return
        await send(f"🔔 User @{row[1] or row[0]} unmuted.")

    elif intent == "remove_user":
        ref = str(params.get("ref", "")).lstrip("@").split()[0] if params.get("ref") else ""
        if not ref:
            await send("❓ Who should I remove?")
            return
        await msg.reply_text(
            f"⚠️ Confirm permanent removal of `{ref}`?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"✅ Remove '{ref}'", callback_data=f"confirm_remove:{ref}"),
                InlineKeyboardButton("❌ Cancel", callback_data="adm_panel"),
            ]])
        )

    elif intent == "broadcast":
        broadcast_text = (params.get("text") or "").strip()
        if not broadcast_text:
            await send("❓ What message should I broadcast?")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT telegram_id FROM users")
            all_users = [r[0] for r in cur.fetchall()]
            cur.close()
        bot_msg = f"📢 *Broadcast from Admin:*\n\n{broadcast_text}"
        sent = failed = 0
        for i in range(0, len(all_users), 25):
            chunk = all_users[i:i + 25]
            results = await asyncio.gather(*[
                bot.send_message(chat_id=uid, text=bot_msg, parse_mode=ParseMode.MARKDOWN)
                for uid in chunk
            ], return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    failed += 1
                else:
                    sent += 1
            if i + 25 < len(all_users):
                await asyncio.sleep(1)
        await send(f"📢 *Broadcast sent!*\n✅ {sent} delivered · ❌ {failed} failed")

    elif intent == "lottery_draw":
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT user_id, username, full_name FROM lottery_entries ORDER BY RANDOM() LIMIT 1")
            winner = cur.fetchone()
            cur.close()
        if not winner:
            await send("🎰 No entries in the lottery yet.")
            return
        name = winner["full_name"] or winner["username"] or str(winner["user_id"])
        uname = f"@{winner['username']}" if winner["username"] else f"ID: `{winner['user_id']}`"
        try:
            await bot.send_message(
                chat_id=winner["user_id"],
                text="🎉 *You Won the Lottery!*\n\nCongratulations! An admin will contact you about your prize.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        await send(
            f"🎉 *Lottery Winner!*\n\n🏆 *{name}* ({uname})\n\n_Winner has been notified._",
            kbd=[
                [InlineKeyboardButton("🗑️ Clear & Start New", callback_data="lottery_clear")],
                back_btn[0],
            ]
        )

    elif intent == "lottery_clear":
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM lottery_entries")
            cur.close()
        await send("✅ Lottery cleared. Users can enter a new round with /join.")

    elif intent == "add_keyword":
        keyword = (params.get("keyword") or "").strip().lower()
        emoji   = (params.get("emoji") or "").strip()
        if not keyword or not emoji:
            await send("❓ Format: `add keyword <word> <emoji>` — e.g. `add keyword hash 🌿`")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO keyword_emojis(keyword, emoji) VALUES(%s,%s) ON CONFLICT(keyword) DO UPDATE SET emoji=EXCLUDED.emoji",
                (keyword, emoji)
            )
            cur.close()
        load_keywords(force=True)
        await send(f"✅ Keyword rule saved: `{keyword}` → {emoji}")

    elif intent == "del_keyword":
        keyword = (params.get("keyword") or "").strip().lower()
        if not keyword:
            await send("❓ Which keyword should I remove?")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM keyword_emojis WHERE keyword=%s", (keyword,))
            cur.close()
        load_keywords(force=True)
        await send(f"✅ Keyword `{keyword}` removed.")

    else:  # intent == "answer" or unknown
        reply = hint or "I didn't understand that. Type /panel for the button interface or describe what you need."
        await send(reply)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    uid = update.effective_user.id if update.effective_user else None
    # Accept messages from: the admin group OR a known admin user in private DM
    if cid not in ADMIN_ID_VARIANTS and uid not in ADMIN_USER_IDS:
        return
    action = context.user_data.pop("action", None)
    if not action:
        # No pending action → hand off to the NL dispatcher
        await _nl_admin_dispatch(update, context)
        return

    text = update.message.text.strip()

    if action == AWAITING_SEARCH:
        ref = text.lstrip("@").split()[0]
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT u.*,
                       ROUND(AVG(r.stars)::numeric,1) as avg_rating,
                       COUNT(DISTINCT r.id) as rating_count,
                       COUNT(DISTINCT pr.id) as req_count,
                       COUNT(DISTINCT rr.id) as deals_done,
                       (SELECT COUNT(*) FROM warnings w WHERE w.user_id=u.telegram_id) as warning_count
                FROM users u
                LEFT JOIN ratings r ON r.seller_id=u.telegram_id
                LEFT JOIN product_requests pr ON pr.buyer_id=u.telegram_id
                LEFT JOIN request_responses rr ON rr.seller_id=u.telegram_id
                WHERE u.username=%s OR u.telegram_id::text=%s
                GROUP BY u.telegram_id
            """, (ref, ref))
            user = cur.fetchone()
            cur.close()
        if not user:
            await update.message.reply_text("❌ User not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")]]))
            return
        name = user["full_name"] or user["username"] or str(user["telegram_id"])
        uname = f"@{user['username']}" if user["username"] else f"ID: {user['telegram_id']}"
        avg = float(user["avg_rating"]) if user["avg_rating"] else 0
        status_map = {"approved": "✅ Approved", "pending": "⏳ Pending", "banned": "🚫 Banned"}
        status = status_map.get(user["status"], user["status"])
        muted = "🔕 Muted" if user.get("muted") else "🔔 Active"
        await update.message.reply_text(
            f"🔍 *User Profile*\n\n"
            f"👤 *{name}* ({uname})\n"
            f"🎭 Role: *{user['role']}* · {status}\n"
            f"📅 Joined: {user['registered_at'].strftime('%Y-%m-%d')}\n"
            f"🔔 Notifications: {muted}\n"
            f"⭐ Rating: {stars_str(avg, int(user['rating_count'] or 0))}\n"
            f"📦 Requests made: *{user['req_count']}*\n"
            f"🤝 Deals done: *{user['deals_done']}*\n"
            f"⚠️ Warnings: *{user['warning_count']}*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚠️ Warn", callback_data=f"warn_direct:{user['telegram_id']}"),
                    InlineKeyboardButton("🚫 Ban", callback_data=f"confirm_ban:{user['username'] or user['telegram_id']}"),
                    InlineKeyboardButton("❌ Remove", callback_data=f"confirm_remove:{user['username'] or user['telegram_id']}"),
                ],
                [InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")],
            ])
        )

    elif action == AWAITING_WARN:
        parts = text.lstrip("@").split(None, 1)
        ref = parts[0]
        reason = parts[1] if len(parts) > 1 else "No reason given"
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM users WHERE username=%s OR telegram_id::text=%s", (ref, ref))
            user = cur.fetchone()
            if user:
                cur.execute(
                    "INSERT INTO warnings(user_id, admin_id, reason) VALUES(%s,%s,%s)",
                    (user["telegram_id"], update.effective_user.id, reason)
                )
            cur.close()
        if not user:
            await update.message.reply_text("❌ User not found.")
            return
        name = user["full_name"] or user["username"] or str(user["telegram_id"])
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text=(
                    f"⚠️ *Official Warning*\n\n"
                    f"You have received a warning from the marketplace admin.\n\n"
                    f"📝 *Reason:* {reason}\n\n"
                    "_Further violations may result in a ban._"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            notified = "✅ User notified."
        except Exception:
            notified = "⚠️ Could not DM user."
        await update.message.reply_text(
            f"⚠️ Warning sent to *{name}*.\n{notified}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")]]),
        )

    elif action == AWAITING_BAN:
        ref = text.lstrip("@").split()[0]
        await update.message.reply_text(
            f"⚠️ Confirm ban of seller *{ref}*?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"✅ Ban '{ref}'", callback_data=f"confirm_ban:{ref}"),
                InlineKeyboardButton("❌ Cancel", callback_data="adm_panel"),
            ]]),
        )

    elif action == AWAITING_REMOVE:
        ref = text.lstrip("@").split()[0]
        await update.message.reply_text(
            f"⚠️ Confirm remove of user *{ref}*?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(f"✅ Remove '{ref}'", callback_data=f"confirm_remove:{ref}"),
                InlineKeyboardButton("❌ Cancel", callback_data="adm_panel"),
            ]]),
        )

    elif action == AWAITING_KEYWORD:
        parts = text.strip().split(None, 1)
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Format: `keyword emoji`\nExample: `hash 🌿`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔤 Keywords", callback_data="adm_keywords")]]),
            )
            return
        keyword, emoji = parts[0].lower(), parts[1].strip()
        try:
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO keyword_emojis(keyword, emoji) VALUES(%s,%s) "
                    "ON CONFLICT(keyword) DO UPDATE SET emoji=EXCLUDED.emoji",
                    (keyword, emoji)
                )
                cur.close()
            load_keywords(force=True)
            await update.message.reply_text(
                f"✅ Rule saved: `{keyword}` → {emoji}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔤 Keywords", callback_data="adm_keywords")]]),
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Failed to save: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")]]),
            )

    elif action == AWAITING_SETTING:
        setting_key = context.user_data.pop("setting_key", None)
        if not setting_key:
            await update.message.reply_text("❌ Unknown setting.")
            return
        value = text.strip()
        if setting_key == "force_join_chat_id":
            # Validate it looks like a numeric ID
            try:
                int(value)
            except ValueError:
                await update.message.reply_text(
                    "❌ Channel ID must be a number (e.g. `-1001234567890`).\nTry again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")]]),
                )
                return
        set_setting(setting_key, value)
        labels = {"group_link": "Group Invite Link", "force_join_chat_id": "Force-Join Channel ID"}
        label = labels.get(setting_key, setting_key)
        await update.message.reply_text(
            f"✅ *{label}* updated:\n`{value}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings")]]),
        )

    elif action == AWAITING_BROADCAST:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT telegram_id FROM users")
            all_users = [r[0] for r in cur.fetchall()]
            cur.close()

        bot_msg = f"📢 *Broadcast from Admin:*\n\n{text}"
        sent = failed = 0
        chunk_size = 25
        for i in range(0, len(all_users), chunk_size):
            chunk = all_users[i:i + chunk_size]
            results = await asyncio.gather(*[
                context.bot.send_message(chat_id=uid, text=bot_msg, parse_mode=ParseMode.MARKDOWN)
                for uid in chunk
            ], return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    failed += 1
                else:
                    sent += 1
            if i + chunk_size < len(all_users):
                await asyncio.sleep(1)

        await update.message.reply_text(
            f"📢 *Broadcast sent!*\n✅ {sent} delivered · ❌ {failed} failed",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Panel", callback_data="adm_panel")]]),
        )

    elif action == AWAITING_SCRIPT:
        # Save the inline code as a timestamped script and run it immediately
        import re as _re, datetime as _dt
        raw_code = text.strip()
        # Strip Markdown code fences if the user copied from somewhere
        raw_code = _re.sub(r"^```(?:python)?\s*", "", raw_code, flags=_re.IGNORECASE)
        raw_code = _re.sub(r"\s*```$", "", raw_code)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        script_name = f"inline_{ts}.py"
        SCRIPTS_DIR.mkdir(exist_ok=True)
        script_path = SCRIPTS_DIR / script_name
        script_path.write_text(raw_code, encoding="utf-8")
        await update.message.reply_text(
            f"🐍  *Saved as* `{script_name}`\n⏳ Running…",
            parse_mode=ParseMode.MARKDOWN,
        )
        loop = asyncio.get_event_loop()
        output = await loop.run_in_executor(None, _run_script_sync, script_path)
        out_display = output[:3600] if len(output) > 3600 else output
        await update.message.reply_text(
            f"🐍  *Output:* `{script_name}`\n{'─' * 24}\n```\n{out_display}\n```",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("▶️  Run Again",      callback_data=f"run:{script_name}"),
                    InlineKeyboardButton("🗑️  Delete",          callback_data=f"del_script:{script_name}"),
                ],
                [InlineKeyboardButton("◀️  Back to Scripts",   callback_data="adm_scripts")],
                [InlineKeyboardButton("✏️  Write Another",     callback_data="script_write")],
            ]),
        )


async def script_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else None
    # Allow from admin group OR from a known admin DM
    is_admin_group = chat_id in ADMIN_ID_VARIANTS
    is_admin_dm = (user_id in ADMIN_USER_IDS) and (update.effective_chat.type == "private")
    if not (is_admin_group or is_admin_dm):
        return
    doc = update.message.document
    if not doc or not doc.file_name.endswith(".py"):
        return
    SCRIPTS_DIR.mkdir(exist_ok=True)
    file = await context.bot.get_file(doc.file_id)
    # Sanitise filename — keep only safe characters
    import re as _re
    safe_name = _re.sub(r"[^\w.\-]", "_", doc.file_name)
    dest = SCRIPTS_DIR / safe_name
    await file.download_to_drive(str(dest))
    await update.message.reply_text(
        f"✅ *{safe_name}* uploaded successfully!\n"
        f"_Tap Run to execute it, or open Scripts panel._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"▶️  Run {safe_name}", callback_data=f"run:{safe_name}")],
            [InlineKeyboardButton("🐍  All Scripts",      callback_data="adm_scripts")],
        ]),
    )


# ── Keyword → Emoji Group Watcher ─────────────────────────────────────────────

async def keyword_filter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Monitors messages in ALL groups the bot is added to.
    If a message contains a configured keyword, it is replaced with the
    corresponding emoji and the corrected version is sent back to the user,
    asking them to repost.
    """
    msg = update.message
    if not msg or not msg.text:
        return
    # Skip the admin group itself
    if msg.chat.id in ADMIN_ID_VARIANTS:
        return
    # Only process group/supergroup messages
    if msg.chat.type not in ("group", "supergroup"):
        return

    keywords = load_keywords()
    if not keywords:
        return

    new_text, changed = apply_keywords(msg.text, keywords)
    if not changed:
        return

    user = msg.from_user
    display_name = user.first_name or user.username or "friend"
    mention = f"@{user.username}" if user.username else display_name

    # Try to delete the original message (requires 'Delete messages' admin perm)
    deleted_original = False
    try:
        await msg.delete()
        deleted_original = True
    except Exception:
        pass

    # IMPORTANT: avoid posting corrective messages into groups (spam risk).
    # Instead, DM the author with the corrected version they can repost.
    dm_text = (
        f"✏️ Hey {display_name}!\n\n"
        f"Din besked i *{msg.chat.title or 'din gruppe'}* indeholdt ord der bliver auto-erstattet.\n\n"
        f"*Korrigeret version:*\n{new_text}\n\n"
        f"_Kopiér og genpost den i gruppen._"
    )
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=dm_text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"keyword_filter: could not DM user {user.id}: {e}")


# ── Group Report Watcher ───────────────────────────────────────────────────────

async def chat_member_updated(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track member join/leave events in any group the bot is in."""
    result = update.chat_member
    if not result:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status
    member = result.new_chat_member.user
    chat = result.chat

    # Skip the bot itself
    if member.is_bot:
        return

    joined_statuses = {ChatMember.LEFT, ChatMember.BANNED}
    active_statuses = {ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER, ChatMember.RESTRICTED}

    # Member JOINED the group
    if old_status in joined_statuses and new_status in active_statuses:
        try:
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO group_joins(user_id, username, full_name, chat_id, chat_title)
                    VALUES(%s,%s,%s,%s,%s)
                """, (
                    member.id,
                    member.username or "",
                    member.full_name or "",
                    chat.id,
                    chat.title or str(chat.id),
                ))
                cur.close()
        except Exception as e:
            logger.warning(f"Failed to log join: {e}")
        return

    # Member LEFT the group
    if old_status in active_statuses and new_status in joined_statuses:
        try:
            with get_db() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Find the most recent join for this user in this chat
                cur.execute("""
                    SELECT id, joined_at FROM group_joins
                    WHERE user_id=%s AND chat_id=%s AND left_at IS NULL
                    ORDER BY joined_at DESC LIMIT 1
                """, (member.id, chat.id))
                join = cur.fetchone()
                if join:
                    now = datetime.now(timezone.utc)
                    joined_at = join["joined_at"]
                    # Make offset-aware if needed
                    if joined_at.tzinfo is None:
                        joined_at = joined_at.replace(tzinfo=timezone.utc)
                    seconds_stayed = (now - joined_at).total_seconds()
                    flagged = seconds_stayed <= REPORT_SUSPECT_WINDOW

                    cur.execute("""
                        UPDATE group_joins SET left_at=NOW(), flagged=%s WHERE id=%s
                    """, (flagged, join["id"]))
                    cur.close()

                    if flagged:
                        name = member.full_name or member.username or str(member.id)
                        uname = f"@{member.username}" if member.username else f"ID: `{member.id}`"
                        mins = int(seconds_stayed // 60)
                        secs = int(seconds_stayed % 60)
                        stayed_str = f"{mins}m {secs}s" if mins else f"{secs}s"
                        try:
                            await context.bot.send_message(
                                chat_id=ADMIN_NOTIFY_CHAT_ID,
                                text=(
                                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                                    "🚩 *Possible Group Reporter*\n"
                                    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"👤 *{name}* ({uname})\n"
                                    f"💬 Group: *{chat.title}*\n"
                                    f"⏱ Stayed only: *{stayed_str}*\n\n"
                                    "_This user joined and left very quickly — a common pattern when reporting a group._"
                                ),
                                parse_mode=ParseMode.MARKDOWN,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send report alert: {e}")
                else:
                    cur.close()
        except Exception as e:
            logger.warning(f"Failed to log leave: {e}")


# ── App setup ──────────────────────────────────────────────────────────────────

async def start_redirect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context

    chat = update.effective_chat
    if not chat or not update.message or not update.effective_user:
        return

    uid = update.effective_user.id
    chat_id = chat.id

    # Avoid noisy replies in arbitrary groups. This bot is meant for:
    # - private DM with the owner/admin
    # - the configured admin group (if set)
    if chat.type in ("group", "supergroup") and chat_id not in ADMIN_ID_VARIANTS:
        return
    if chat.type == "channel":
        return

    if uid in ADMIN_USER_IDS or chat_id in ADMIN_ID_VARIANTS:
        # Admin user — show the control panel directly
        await update.message.reply_text(
            panel_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🏠  Open Panel",  callback_data="adm_panel"),
                    InlineKeyboardButton("❓  Commands",    callback_data="show_help"),
                ]
            ])
        )
    else:
        if chat.type != "private":
            return
        await update.message.reply_text(
            "⚙️  *This is the Valkyrie admin bot.*\n\n"
            "It is not open to the public.\n\n"
            "Looking for the marketplace?\n"
            "→ Open @valkyriesellerbuyer_bot and send /start",
            parse_mode=ParseMode.MARKDOWN,
        )


async def alive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.effective_chat and update.effective_chat.type != "private":
        return
    if update.message:
        await update.message.reply_text("Group Guard Admin Bot is alive.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception in admin bot handler:", exc_info=context.error)


def build_app():
    _ensure_report_tables()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("start", start_redirect))
    app.add_handler(CommandHandler("alive", alive_cmd))
    app.add_handler(CommandHandler("id",    id_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("panel", admin_cmd))
    app.add_handler(CommandHandler("help",  help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    # Admin group filter (both legacy group ID and supergroup variant)
    group_filter = filters.Chat(list(ADMIN_ID_VARIANTS))

    # Private DM filter for known admin user IDs (set ADMIN_USER_IDS env var)
    if ADMIN_USER_IDS:
        admin_dm_filter = filters.Chat(list(ADMIN_USER_IDS)) & filters.ChatType.PRIVATE
        combined_filter = group_filter | admin_dm_filter
    else:
        combined_filter = group_filter

    app.add_handler(MessageHandler(
        filters.Document.FileExtension("py") & combined_filter,
        script_upload,
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & combined_filter,
        text_handler,
    ))
    # Keyword → Emoji watcher — listens in ALL groups (not admin group)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP),
        keyword_filter_handler,
        block=False,
    ))
    # Report watcher — listens in ALL groups (not just admin group)
    app.add_handler(ChatMemberHandler(chat_member_updated, ChatMemberHandler.CHAT_MEMBER))

    # Optional auto-messages: disabled by default (see ADMIN_AUTO_MESSAGES).
    if AUTO_MESSAGES_ENABLED and ADMIN_NOTIFY_CHAT_ID is not None:
        async def job_auto_message(ctx: ContextTypes.DEFAULT_TYPE):
            import random
            msg = random.choice(AUTO_MESSAGES)
            try:
                await ctx.bot.send_message(chat_id=ADMIN_NOTIFY_CHAT_ID, text=msg)
            except Exception as e:
                logger.warning(f"Auto-message failed: {e}")

        app.job_queue.run_repeating(job_auto_message, interval=7200, first=300)
    return app


async def run_async():
    logger.info("@valkyriegroupmod_bot (admin) starting...")
    app = build_app()
    async with app:
        await app.start()
        if OWNER_CHAT_ID is not None:
            try:
                me = await app.bot.get_me()
                username = me.username or "unknown"
                await app.bot.send_message(
                    chat_id=OWNER_CHAT_ID,
                    text=f"Group Guard Admin Bot is alive on Render as @{username}.",
                )
            except Exception as e:
                logger.warning(f"Startup alive ping failed: {e}")
        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        await asyncio.Event().wait()


def main():
    asyncio.run(run_async())


if __name__ == "__main__":
    main()
