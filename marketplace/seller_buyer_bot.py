"""
@valkyriesellerbuyer_bot
Marketplace bot with force-join gate, Telegram Stars payments,
referral system, lottery, activity ranking, and anti-spam.
"""
import os
import asyncio
import base64
import hashlib
import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
import psycopg2.pool
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

logging.basicConfig(
    format="%(asctime)s [SELLER-BUYER] %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
BOT_TOKEN = (
    os.environ.get("SELLER_BUYER_BOT_TOKEN")
    or os.environ.get("VALKYRIESELLERBUYER_BOT_TOKEN")
    or ""
)
if not BOT_TOKEN:
    raise RuntimeError("Missing SELLER_BUYER_BOT_TOKEN (or VALKYRIESELLERBUYER_BOT_TOKEN).")

_raw_admin_group_id = os.environ.get("ADMIN_GROUP_ID", "").strip()
ADMIN_GROUP_ID = (
    -abs(int(_raw_admin_group_id))
    if _raw_admin_group_id.lstrip("-").isdigit()
    else None
)

ENCRYPTION_KEY = os.environ.get("BOT_ENCRYPTION_KEY", "").strip()
if not ENCRYPTION_KEY:
    raise RuntimeError("Missing BOT_ENCRYPTION_KEY.")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL.")

# Set application_name so Postgres logs show which component is connecting.
# Can be overridden per-deploy with PG_APP_NAME.
_PG_APP_NAME = os.environ.get("PG_APP_NAME", "valkyrie_seller_buyer")

_owner_chat_id_raw = os.environ.get("BOT_OWNER_CHAT_ID", "").strip()
OWNER_CHAT_ID = int(_owner_chat_id_raw) if _owner_chat_id_raw.isdigit() else None
ADMIN_NOTIFY_CHAT_ID = ADMIN_GROUP_ID if ADMIN_GROUP_ID is not None else OWNER_CHAT_ID

GROUP_LINK_DEFAULT = "https://t.me/yourgroup"   # Fallback — override via admin panel
FREE_REQUESTS      = 3        # Requests included for free
STARS_PER_REQ      = 10       # Stars charged after free quota

# Optional: numeric chat ID of the channel/group to verify membership.
# Set FORCE_JOIN_CHAT_ID env var, OR configure from the admin panel (stored in bot_settings).
FORCE_JOIN_CHAT_ID = int(os.environ.get("FORCE_JOIN_CHAT_ID", "0")) or None

# Anti-spam: max messages per window
SPAM_MAX_MSGS   = 8
SPAM_WINDOW_SEC = 30
SPAM_MUTE_SEC   = 60

# Command anti-spam: max commands per minute
CMD_MAX_CMDS    = 5
CMD_WINDOW_SEC  = 60

_AES_KEY: bytes = hashlib.sha256(ENCRYPTION_KEY.encode()).digest()
_pool: psycopg2.pool.SimpleConnectionPool | None = None

# In-memory anti-spam trackers {user_id: [timestamps]}
_msg_times: dict = defaultdict(list)
_muted_until: dict = {}
_cmd_times: dict  = defaultdict(list)
_cmd_muted_until: dict = {}

AWAITING_DISPUTE = "dispute"


# ── Pool ───────────────────────────────────────────────────────────────────────

def _get_pool():
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


# ── Crypto ─────────────────────────────────────────────────────────────────────

def encrypt(text: str) -> str:
    cipher = AES.new(_AES_KEY, AES.MODE_CBC)
    ct = cipher.encrypt(pad(text.encode(), AES.block_size))
    return base64.b64encode(cipher.iv).decode() + ":" + base64.b64encode(ct).decode()


def decrypt(token: str) -> str:
    iv_b64, ct_b64 = token.split(":")
    cipher = AES.new(_AES_KEY, AES.MODE_CBC, base64.b64decode(iv_b64))
    return unpad(cipher.decrypt(base64.b64decode(ct_b64)), AES.block_size).decode()


# ── Database ───────────────────────────────────────────────────────────────────

def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id   BIGINT PRIMARY KEY,
                username      TEXT,
                full_name     TEXT,
                role          TEXT CHECK(role IN ('buyer','seller')),
                status        TEXT DEFAULT 'approved' CHECK(status IN ('pending','approved','banned')),
                force_joined  BOOLEAN DEFAULT FALSE,
                muted         BOOLEAN DEFAULT FALSE,
                referrer_id   BIGINT,
                requests_used INT DEFAULT 0,
                points        INT DEFAULT 0,
                registered_at TIMESTAMP DEFAULT NOW()
            )
        """)
        for col, defn in [
            ("status",        "TEXT DEFAULT 'approved'"),
            ("force_joined",  "BOOLEAN DEFAULT FALSE"),
            ("muted",         "BOOLEAN DEFAULT FALSE"),
            ("referrer_id",   "BIGINT"),
            ("requests_used", "INT DEFAULT 0"),
            ("points",        "INT DEFAULT 0"),
        ]:
            cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS seller_products (
                id              SERIAL PRIMARY KEY,
                seller_id       BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                product_keyword TEXT NOT NULL,
                price_range     TEXT,
                UNIQUE(seller_id, product_keyword)
            )
        """)
        cur.execute("ALTER TABLE seller_products ADD COLUMN IF NOT EXISTS price_range TEXT")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS product_requests (
                id                SERIAL PRIMARY KEY,
                buyer_id          BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                product_keyword   TEXT NOT NULL,
                encrypted_message TEXT NOT NULL,
                status            TEXT DEFAULT 'pending',
                created_at        TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS request_responses (
                id          SERIAL PRIMARY KEY,
                request_id  INT REFERENCES product_requests(id) ON DELETE CASCADE,
                seller_id   BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                accepted_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(request_id, seller_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id         SERIAL PRIMARY KEY,
                buyer_id   BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                seller_id  BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                stars      INT CHECK(stars BETWEEN 1 AND 5),
                rated_at   TIMESTAMP DEFAULT NOW(),
                UNIQUE(buyer_id, seller_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS disputes (
                id         SERIAL PRIMARY KEY,
                buyer_id   BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                seller_id  BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                request_id INT REFERENCES product_requests(id) ON DELETE CASCADE,
                reason     TEXT,
                status     TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id       SERIAL PRIMARY KEY,
                user_id  BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
                admin_id BIGINT,
                reason   TEXT,
                warned_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id          SERIAL PRIMARY KEY,
                event_type  TEXT NOT NULL,
                user_id     BIGINT,
                description TEXT,
                created_at  TIMESTAMP DEFAULT NOW()
            )
        """)
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lottery_entries (
                    id         SERIAL PRIMARY KEY,
                    user_id    BIGINT NOT NULL UNIQUE,
                    username   TEXT,
                    full_name  TEXT,
                    entered_at TIMESTAMP DEFAULT NOW()
                )
            """)
        except Exception:
            conn.rollback()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.close()
    logger.info("DB ready.")


def get_setting(key: str, default: str = "") -> str:
    """Read a value from bot_settings table, fall back to default."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM bot_settings WHERE key=%s", (key,))
            row = cur.fetchone()
            cur.close()
        return row[0] if row else default
    except Exception:
        return default


def log_activity(event_type: str, user_id, description: str):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO activity_log(event_type,user_id,description) VALUES(%s,%s,%s)",
                (event_type, user_id, description)
            )
            cur.close()
    except Exception as e:
        logger.warning(f"Activity log failed: {e}")


def add_points(user_id: int, pts: int):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE users SET points=points+%s WHERE telegram_id=%s",
                (pts, user_id)
            )
            cur.close()
    except Exception as e:
        logger.warning(f"Points update failed: {e}")


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_user(tid):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE telegram_id=%s", (tid,))
        u = cur.fetchone()
        cur.close()
    return u


def upsert_user(tid, username, full_name, role, status="approved", referrer_id=None):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (telegram_id, username, full_name, role, status, referrer_id)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (telegram_id) DO UPDATE
            SET role=EXCLUDED.role, username=EXCLUDED.username,
                full_name=EXCLUDED.full_name, status=EXCLUDED.status
        """, (tid, username, full_name, role, status, referrer_id))
        cur.close()


def mark_joined(tid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET force_joined=TRUE WHERE telegram_id=%s", (tid,))
        if cur.rowcount == 0:
            cur.execute(
                "INSERT INTO users(telegram_id,force_joined) VALUES(%s,TRUE) ON CONFLICT DO NOTHING",
                (tid,)
            )
        cur.close()


def get_or_create_force_joined(tid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT force_joined FROM users WHERE telegram_id=%s", (tid,))
        row = cur.fetchone()
        cur.close()
    return bool(row and row[0])


def increment_requests_used(tid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET requests_used=requests_used+1 WHERE telegram_id=%s",
            (tid,)
        )
        cur.close()


def add_product(seller_id, product, price_range=None):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO seller_products(seller_id,product_keyword,price_range)
            VALUES(%s,%s,%s) ON CONFLICT(seller_id,product_keyword)
            DO UPDATE SET price_range=EXCLUDED.price_range
        """, (seller_id, product.lower().strip(), price_range))
        cur.close()


def remove_product(seller_id, product):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM seller_products WHERE seller_id=%s AND product_keyword=%s",
            (seller_id, product.lower().strip())
        )
        cur.close()


def get_products(seller_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT product_keyword, price_range FROM seller_products WHERE seller_id=%s",
            (seller_id,)
        )
        rows = cur.fetchall()
        cur.close()
    return rows


def sellers_for_product(keyword):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.telegram_id, u.username, u.full_name, u.muted, sp.price_range
            FROM seller_products sp JOIN users u ON u.telegram_id=sp.seller_id
            WHERE sp.product_keyword=%s AND u.status='approved' AND u.muted=FALSE
        """, (keyword.lower().strip(),))
        rows = cur.fetchall()
        cur.close()
    return rows


def create_request(buyer_id, keyword, enc):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO product_requests(buyer_id,product_keyword,encrypted_message) VALUES(%s,%s,%s) RETURNING id",
            (buyer_id, keyword.lower().strip(), enc)
        )
        rid = cur.fetchone()[0]
        cur.close()
    return rid


def get_request_and_verify_seller(rid, seller_id):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT pr.*,
                   EXISTS(SELECT 1 FROM seller_products sp
                          WHERE sp.seller_id=%s AND sp.product_keyword=pr.product_keyword) AS seller_owns
            FROM product_requests pr WHERE pr.id=%s
        """, (seller_id, rid))
        r = cur.fetchone()
        cur.close()
    return r


def get_buyer_requests(buyer_id):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT pr.id, pr.product_keyword, pr.status, pr.created_at,
                   u.username as seller_username, u.full_name as seller_name
            FROM product_requests pr
            LEFT JOIN request_responses rr ON rr.request_id=pr.id
            LEFT JOIN users u ON u.telegram_id=rr.seller_id
            WHERE pr.buyer_id=%s ORDER BY pr.created_at DESC LIMIT 10
        """, (buyer_id,))
        rows = cur.fetchall()
        cur.close()
    return rows


def accept_request(rid, seller_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO request_responses(request_id,seller_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (rid, seller_id)
        )
        cur.execute("UPDATE product_requests SET status='accepted' WHERE id=%s", (rid,))
        cur.close()


def get_rating(seller_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT ROUND(AVG(stars)::numeric,1), COUNT(*) FROM ratings WHERE seller_id=%s",
            (seller_id,)
        )
        r = cur.fetchone()
        cur.close()
    return float(r[0] or 0), int(r[1] or 0)


def save_rating(buyer_id, seller_id, stars):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO ratings(buyer_id,seller_id,stars) VALUES(%s,%s,%s)
                ON CONFLICT(buyer_id,seller_id) DO UPDATE SET stars=EXCLUDED.stars, rated_at=NOW()
            """, (buyer_id, seller_id, stars))
            cur.close()
        return True
    except Exception as e:
        logger.error(e)
        return False


def find_seller_by_ref(ref):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM users WHERE (username=%s OR telegram_id::text=%s) AND role='seller'",
            (ref, ref)
        )
        s = cur.fetchone()
        cur.close()
    return s


def get_seller_profile(ref):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.*,
                   ROUND(AVG(r.stars)::numeric,1) as avg_rating,
                   COUNT(DISTINCT r.id) as rating_count,
                   COUNT(DISTINCT rr.id) as deals_done,
                   COALESCE(string_agg(DISTINCT sp.product_keyword
                       || COALESCE(' (' || sp.price_range || ')',''), ', '), 'none') as products
            FROM users u
            LEFT JOIN ratings r ON r.seller_id=u.telegram_id
            LEFT JOIN request_responses rr ON rr.seller_id=u.telegram_id
            LEFT JOIN seller_products sp ON sp.seller_id=u.telegram_id
            WHERE (u.username=%s OR u.telegram_id::text=%s) AND u.role='seller'
            GROUP BY u.telegram_id
        """, (ref, ref))
        row = cur.fetchone()
        cur.close()
    return row


def open_dispute(buyer_id, seller_id, request_id, reason):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO disputes(buyer_id,seller_id,request_id,reason) VALUES(%s,%s,%s,%s) RETURNING id",
            (buyer_id, seller_id, request_id, reason)
        )
        did = cur.fetchone()[0]
        cur.close()
    return did


def expire_old_requests():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE product_requests SET status='expired'
            WHERE status='pending' AND created_at < %s
            RETURNING id, buyer_id, product_keyword
        """, (cutoff,))
        expired = cur.fetchall()
        cur.close()
    return expired


def get_top_users(limit=10):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT telegram_id, username, full_name, role, points
            FROM users WHERE points > 0
            ORDER BY points DESC LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
    return rows


def enter_lottery(user_id, username, full_name):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO lottery_entries(user_id, username, full_name)
            VALUES(%s,%s,%s) ON CONFLICT(user_id) DO NOTHING
            RETURNING id
        """, (user_id, username or "", full_name or ""))
        r = cur.fetchone()
        cur.close()
    return r is not None  # False if already entered


def get_referral_count(user_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id=%s", (user_id,))
        r = cur.fetchone()
        cur.close()
    return int(r[0] or 0)


def stars_str(avg, count):
    if not count:
        return "☆☆☆☆☆ _(no ratings yet)_"
    filled = round(avg); empty = 5 - filled
    return "★" * filled + "☆" * empty + f" ({avg}/5 · {count} reviews)"


# ── Anti-spam ──────────────────────────────────────────────────────────────────

def is_spamming(user_id: int) -> bool:
    """Rate-limit free-text messages."""
    now = time.time()
    if user_id in _muted_until and now < _muted_until[user_id]:
        return True
    times = _msg_times[user_id]
    times[:] = [t for t in times if now - t < SPAM_WINDOW_SEC]
    times.append(now)
    if len(times) > SPAM_MAX_MSGS:
        _muted_until[user_id] = now + SPAM_MUTE_SEC
        return True
    return False


def is_cmd_spamming(user_id: int) -> bool:
    """Rate-limit command usage (5 commands per 60 seconds)."""
    now = time.time()
    if user_id in _cmd_muted_until and now < _cmd_muted_until[user_id]:
        return True
    times = _cmd_times[user_id]
    times[:] = [t for t in times if now - t < CMD_WINDOW_SEC]
    times.append(now)
    if len(times) > CMD_MAX_CMDS:
        _cmd_muted_until[user_id] = now + SPAM_MUTE_SEC
        return True
    return False


# ── Force-join gate ────────────────────────────────────────────────────────────

def join_keyboard():
    link = get_setting("group_link", GROUP_LINK_DEFAULT)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Join Our Group", url=link)],
        [InlineKeyboardButton("✅ I've Joined — Verify", callback_data="check_join")],
    ])


def force_join_active() -> bool:
    """Returns True only if a real force-join channel is configured."""
    if FORCE_JOIN_CHAT_ID:
        return True
    raw = get_setting("force_join_chat_id", "")
    try:
        return bool(int(raw.strip())) if raw.strip() else False
    except ValueError:
        return False


async def require_join(update: Update) -> bool:
    """Returns True if user has confirmed joining, otherwise sends the gate message."""
    uid = update.effective_user.id
    # If no force-join channel is configured, auto-grant access
    if not force_join_active():
        mark_joined(uid)
        return True
    if get_or_create_force_joined(uid):
        return True
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔐 *Join Required*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "You must join our community group before using this bot.\n\n"
        "1️⃣ Click *Join Our Group* below\n"
        "2️⃣ Click *I've Joined* to confirm\n",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=join_keyboard(),
    )
    return False


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id

    # Determine which chat ID to verify against (env var takes priority, then DB)
    verify_chat_id = FORCE_JOIN_CHAT_ID
    if not verify_chat_id:
        raw = get_setting("force_join_chat_id", "")
        try:
            verify_chat_id = int(raw) if raw.strip() else None
        except ValueError:
            verify_chat_id = None

    if verify_chat_id:
        # Actually check via Telegram API whether user is in the group/channel
        try:
            member = await context.bot.get_chat_member(verify_chat_id, uid)
            if member.status in ("left", "kicked", "banned"):
                await q.answer(
                    "❌ You haven't joined yet! Please click 'Join Our Group' first.",
                    show_alert=True,
                )
                return
        except Exception as e:
            logger.warning(f"Membership check failed (chat {verify_chat_id}): {e}")
            # If we can't verify (bot not in channel, etc.), fall through and grant access
            # so a misconfiguration doesn't permanently lock everyone out

    await q.answer()
    mark_joined(uid)
    add_points(uid, 5)

    user = get_user(uid)
    if user and user.get("role") and user["status"] == "approved":
        kb = _seller_kb() if user["role"] == "seller" else _buyer_kb()
        role_label = "Seller" if user["role"] == "seller" else "Buyer"
        await q.edit_message_text(
            f"✅ *Access granted!*\n\nWelcome back, {role_label}! Tap a button below 👇",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
    else:
        await q.edit_message_text(
            "✅ *Access granted!*\n\nWelcome to the marketplace. Tap /start to register.",
            parse_mode=ParseMode.MARKDOWN,
        )


# ── Scheduled jobs ─────────────────────────────────────────────────────────────

async def job_expire_requests(context: ContextTypes.DEFAULT_TYPE):
    expired = expire_old_requests()
    for req_id, buyer_id, keyword in expired:
        try:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=(
                    f"⏰ *Request `#{req_id}` Expired*\n\n"
                    f"📦 Product: *{keyword}*\n\n"
                    "No seller accepted within 48 hours. Submit a new request anytime."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
    if expired:
        logger.info(f"Expired {len(expired)} old requests")


# ── Handlers ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    logger.info(f"/start received from user {u.id} (@{u.username})")

    # Referral extraction from /start ref_USERID
    referrer_id = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                referrer_id = int(arg[4:])
                if referrer_id == u.id:
                    referrer_id = None
            except ValueError:
                pass

    user = get_user(u.id)

    # Force-join gate first (only if a channel is actually configured)
    if force_join_active() and not (user and user.get("force_joined")):
        # If a brand-new user, create a minimal record so we can track their referral
        if not user and referrer_id:
            upsert_user(u.id, u.username or "", u.full_name or "", "buyer",
                        status="approved", referrer_id=referrer_id)
        await update.message.reply_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔐 *Join Required*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "You must join our community group before using this bot.\n\n"
            "1️⃣ Click *Join Our Group* below\n"
            "2️⃣ Click *I've Joined* to confirm",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=join_keyboard(),
        )
        return

    # Auto-grant join if gate is not active
    if not force_join_active() and not (user and user.get("force_joined")):
        mark_joined(u.id)

    if user and user.get("role"):
        if user["status"] == "pending":
            await update.message.reply_text(
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "⏳ *Pending Approval*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Your seller account is awaiting admin review.\n"
                "You'll be notified as soon as it's approved.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        if user["role"] == "seller":
            await update.message.reply_text(
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🏪 *Welcome back, Seller!*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Tap a button below 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_seller_kb(),
            )
        else:
            await update.message.reply_text(
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🛒 *Welcome back, Buyer!*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Tap a button below 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_buyer_kb(),
            )
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛒 Buyer", callback_data="role_buyer"),
        InlineKeyboardButton("🏪 Seller", callback_data="role_seller"),
    ]])
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛍️  *MARKETPLACE BOT*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Are you a *Buyer* looking for products, or a *Seller* offering them?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )
    return


def _buyer_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Request Product",  callback_data="menu:request"),
            InlineKeyboardButton("📋 My Requests",      callback_data="menu:myrequests"),
        ],
        [
            InlineKeyboardButton("👤 Seller Profile",   callback_data="menu:profile"),
            InlineKeyboardButton("⭐ Rate Seller",       callback_data="menu:rate"),
        ],
        [
            InlineKeyboardButton("🎰 Lottery",          callback_data="menu:lottery"),
            InlineKeyboardButton("🏆 Leaderboard",      callback_data="menu:rank"),
        ],
        [InlineKeyboardButton("🔗 Referral Link",       callback_data="menu:referral")],
        [InlineKeyboardButton("❓ Help",                callback_data="menu:help")],
    ])


def _seller_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Product",      callback_data="menu:addproduct"),
            InlineKeyboardButton("📦 My Products",      callback_data="menu:myproducts"),
        ],
        [
            InlineKeyboardButton("⭐ My Rating",        callback_data="menu:myrating"),
            InlineKeyboardButton("🔕 Mute Alerts",      callback_data="menu:mute"),
        ],
        [
            InlineKeyboardButton("🎰 Lottery",          callback_data="menu:lottery"),
            InlineKeyboardButton("🏆 Leaderboard",      callback_data="menu:rank"),
        ],
        [InlineKeyboardButton("🔗 Referral Link",       callback_data="menu:referral")],
        [InlineKeyboardButton("❓ Help",                callback_data="menu:help")],
    ])


async def role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    role = "buyer" if q.data == "role_buyer" else "seller"

    # Preserve existing referrer_id if already in DB
    existing = get_user(u.id)
    referrer_id = existing.get("referrer_id") if existing else None

    if role == "seller":
        upsert_user(u.id, u.username or "", u.full_name or u.first_name or "", role,
                    status="pending", referrer_id=referrer_id)
        log_activity("seller_registered", u.id, f"{u.full_name} applied as seller")
        try:
            await context.bot.send_message(
                chat_id=ADMIN_NOTIFY_CHAT_ID,
                text=(
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "🆕 *New Seller Application*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 *{u.full_name}*\n"
                    f"🔗 @{u.username or 'N/A'}\n"
                    f"🆔 `{u.id}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_seller:{u.id}"),
                    InlineKeyboardButton("❌ Reject",  callback_data=f"reject_seller:{u.id}"),
                ]]),
            )
        except Exception as e:
            logger.warning(f"Admin notify failed: {e}")
        await q.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🏪 *Application Submitted!*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏳ Pending admin approval. You'll be notified shortly.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        upsert_user(u.id, u.username or "", u.full_name or u.first_name or "", role,
                    referrer_id=referrer_id)
        add_points(u.id, 10)
        log_activity("buyer_registered", u.id, f"{u.full_name} registered as buyer")
        # Credit referrer
        if referrer_id:
            add_points(referrer_id, 20)
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎉 Someone joined using your referral link! +20 points.",
                )
            except Exception:
                pass
        await q.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛒 *You're now a Buyer!*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"First *{FREE_REQUESTS} requests are free*, then *{STARS_PER_REQ}⭐* each.\n\n"
            "Tap a button below to get started 👇",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_buyer_kb(),
        )
    return


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start to register first.")
        return
    if user["status"] == "pending":
        await update.message.reply_text("⏳ Your account is pending approval.")
        return

    common = (
        "\n/join — Enter the lottery 🎰\n"
        "/rank — Activity leaderboard 🏆\n"
        "/referral — Your referral link 🔗\n"
    )

    if user["role"] == "seller":
        text = (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🏪 *SELLER COMMANDS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "/addproduct `<product> [price]` — Add a product\n"
            "/removeproduct `<product>` — Remove a product\n"
            "/myproducts — List your products\n"
            "/myrating — Your star rating\n"
            "/accept `<id>` — Accept & decrypt a buyer request\n"
            "/mute · /unmute — Pause / resume notifications\n"
            + common
        )
    else:
        text = (
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛒 *BUYER COMMANDS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "/request `<product> - <message>` — Request a product\n"
            f"  _First {FREE_REQUESTS} requests are free, then {STARS_PER_REQ}⭐ each_\n"
            "/myrequests — Your request history\n"
            "/profile `<@seller>` — View a seller's profile\n"
            "/rate `<@seller> <1-5>` — Rate a seller\n"
            + common
        )
    kb = _seller_kb() if user["role"] == "seller" else _buyer_kb()
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def addproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    if is_cmd_spamming(update.effective_user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment before sending more commands.")
        return
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "seller":
        await update.message.reply_text("❌ Only sellers can use this.")
        return
    if user["status"] != "approved":
        await update.message.reply_text("⏳ Your account is pending approval.")
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/addproduct <name> [price]`\n_e.g. `/addproduct shoes 20-50`_",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    args = context.args
    price = None
    if len(args) >= 2 and any(c.isdigit() for c in args[-1]):
        price = args[-1]
        p = " ".join(args[:-1]).lower().strip()
    else:
        p = " ".join(args).lower().strip()
    add_product(update.effective_user.id, p, price)
    add_points(update.effective_user.id, 2)
    price_str = f" · 💰 {price}" if price else ""
    await update.message.reply_text(
        f"✅ *{p}*{price_str} added to your listings.", parse_mode=ParseMode.MARKDOWN
    )


async def removeproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "seller":
        await update.message.reply_text("❌ Only sellers can use this.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removeproduct <name>`", parse_mode=ParseMode.MARKDOWN)
        return
    p = " ".join(context.args).lower().strip()
    remove_product(update.effective_user.id, p)
    await update.message.reply_text(f"✅ *{p}* removed.", parse_mode=ParseMode.MARKDOWN)


async def myproducts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "seller":
        await update.message.reply_text("❌ Only sellers can use this.")
        return
    prods = get_products(update.effective_user.id)
    if not prods:
        await update.message.reply_text(
            "No products yet. Use `/addproduct <name> [price]`.", parse_mode=ParseMode.MARKDOWN
        )
    else:
        lines = [f"• *{kw}*" + (f"  💰 {pr}" if pr else "") for kw, pr in prods]
        await update.message.reply_text(
            "📦 *Your Products:*\n\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )


async def myrequests_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "buyer":
        await update.message.reply_text("❌ Only buyers can use this.")
        return
    reqs = get_buyer_requests(update.effective_user.id)
    if not reqs:
        await update.message.reply_text("You haven't made any requests yet.")
        return
    lines = ["📋 *Your Recent Requests:*\n"]
    for r in reqs:
        icon = {"accepted": "✅", "expired": "⏰", "pending": "⏳"}.get(r["status"], "❓")
        dt = r["created_at"].strftime("%m/%d %H:%M")
        seller = f" — @{r['seller_username']}" if r.get("seller_username") else ""
        lines.append(f"{icon} `#{r['id']}` *{r['product_keyword']}* · {dt}{seller}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/profile <@seller>`", parse_mode=ParseMode.MARKDOWN)
        return
    ref = context.args[0].lstrip("@")
    seller = get_seller_profile(ref)
    if not seller:
        await update.message.reply_text("❌ Seller not found.")
        return
    name = seller["full_name"] or seller["username"] or str(seller["telegram_id"])
    uname = f"@{seller['username']}" if seller["username"] else f"ID: {seller['telegram_id']}"
    avg = float(seller["avg_rating"]) if seller["avg_rating"] else 0
    cnt = int(seller["rating_count"] or 0)
    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━━━━━\n🏪 *Seller Profile*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 *{name}* ({uname})\n"
        f"⭐ {stars_str(avg, cnt)}\n"
        f"🤝 Deals: *{seller['deals_done'] or 0}*\n"
        f"🏆 Points: *{seller['points']}*\n"
        f"📦 Products: _{seller['products']}_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def rank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    top = get_top_users(10)
    if not top:
        await update.message.reply_text("No activity yet. Start using the bot to earn points!")
        return
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines = ["🏆 *Activity Leaderboard*\n"]
    for i, u in enumerate(top):
        name = u["full_name"] or u["username"] or str(u["telegram_id"])
        role_icon = "🏪" if u["role"] == "seller" else "🛒"
        lines.append(f"{medals[i]} {role_icon} *{name}* — {u['points']} pts")
    # Show caller's own rank
    my = get_user(update.effective_user.id)
    if my:
        lines.append(f"\n_Your points: *{my['points']}*_")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def referral_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    uid = update.effective_user.id
    count = get_referral_count(uid)
    bot_info = await context.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
    await update.message.reply_text(
        f"🔗 *Your Referral Link*\n\n"
        f"`{link}`\n\n"
        f"👥 People referred: *{count}*\n"
        f"💡 Each referral earns you *+20 points*!",
        parse_mode=ParseMode.MARKDOWN,
    )


async def join_lottery_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start to register first.")
        return
    u = update.effective_user
    new_entry = enter_lottery(u.id, u.username or "", u.full_name or "")
    if new_entry:
        add_points(u.id, 5)
        await update.message.reply_text(
            "🎰 *You're in the lottery!*\n\n"
            "The admin will draw a winner soon.\n"
            "_+5 points added to your account._",
            parse_mode=ParseMode.MARKDOWN,
        )
        log_activity("lottery_entry", u.id, f"{u.full_name} entered the lottery")
    else:
        await update.message.reply_text("✅ You're already in the current lottery draw.")


async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "seller":
        await update.message.reply_text("❌ Only sellers can use this.")
        return
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET muted=TRUE WHERE telegram_id=%s", (update.effective_user.id,))
        cur.close()
    await update.message.reply_text("🔕 Notifications muted. Use /unmute to resume.")


async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "seller":
        await update.message.reply_text("❌ Only sellers can use this.")
        return
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET muted=FALSE WHERE telegram_id=%s", (update.effective_user.id,))
        cur.close()
    await update.message.reply_text("🔔 Notifications resumed.")


async def request_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    if is_cmd_spamming(update.effective_user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment before sending more commands.")
        return
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "buyer":
        await update.message.reply_text("❌ Only buyers can use this.")
        return

    full = " ".join(context.args) if context.args else ""
    if "-" not in full:
        await update.message.reply_text(
            "Usage: `/request <product> - <message>`\nExample: `/request electronics - need a laptop`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    keyword, message = full.split("-", 1)
    keyword = keyword.strip().lower()
    message = message.strip()
    if not keyword or not message:
        await update.message.reply_text("Please provide both a product and a message.")
        return

    # Stars paywall after free quota
    used = user.get("requests_used", 0) or 0
    if used >= FREE_REQUESTS:
        # Store pending request so it can be processed after payment
        context.user_data["pending_request"] = {"keyword": keyword, "message": message}
        await context.bot.send_invoice(
            chat_id=update.effective_user.id,
            title="Marketplace Request",
            description=f"Send a request for: {keyword}",
            payload="marketplace_request",
            provider_token="",      # Empty = Telegram Stars
            currency="XTR",
            prices=[LabeledPrice(label="Marketplace Request", amount=STARS_PER_REQ)],
        )
        return

    await _process_request(update, context, keyword, message)


async def _process_request(update: Update, context: ContextTypes.DEFAULT_TYPE, keyword: str, message: str):
    u = update.effective_user
    sellers = sellers_for_product(keyword)
    if not sellers:
        await update.message.reply_text(
            f"❌ No approved sellers for *{keyword}*.", parse_mode=ParseMode.MARKDOWN
        )
        return

    enc = encrypt(message)
    rid = create_request(u.id, keyword, enc)
    increment_requests_used(u.id)
    add_points(u.id, 3)

    buyer_name = u.full_name or u.username or str(u.id)
    buyer_ref  = f"@{u.username}" if u.username else f"ID:{u.id}"

    notify_text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔔 *NEW REQUEST* `#{rid}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Product: *{keyword}*\n"
        f"👤 Buyer: {buyer_name} ({buyer_ref})\n\n"
        f"🔐 *Encrypted (AES-256):*\n`{enc}`\n\n"
        f"➡️ `/accept {rid}` to reveal."
    )

    async def _notify(s):
        try:
            await context.bot.send_message(
                chat_id=s["telegram_id"], text=notify_text, parse_mode=ParseMode.MARKDOWN
            )
            return True
        except Exception as e:
            logger.warning(f"DM failed to {s['telegram_id']}: {e}")
            return False

    results = await asyncio.gather(*[_notify(s) for s in sellers])
    sent = sum(results)
    log_activity("request_created", u.id, f"Request #{rid} for {keyword}")

    try:
        await context.bot.send_message(
            chat_id=ADMIN_NOTIFY_CHAT_ID,
            text=f"📦 *Request `#{rid}`* | *{keyword}* | {buyer_ref} | {sent}/{len(sellers)} notified",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass

    await update.message.reply_text(
        f"✅ *Request sent!*\n\n"
        f"📦 *{keyword}*\n"
        f"🆔 Request ID: `#{rid}`\n"
        f"👥 Sellers notified: *{sent}*\n\n"
        f"_Encrypted & expires in 48h if no seller responds._",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Stars payment handlers ─────────────────────────────────────────────────────

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = update.message.successful_payment.invoice_payload
    if payload == "marketplace_request":
        pending = context.user_data.pop("pending_request", None)
        if pending:
            add_points(update.effective_user.id, 5)  # bonus for paying
            await _process_request(update, context, pending["keyword"], pending["message"])
        else:
            await update.message.reply_text(
                "⭐ Payment received! Please re-send your /request command."
            )


# ── Accept / dispute / rating ──────────────────────────────────────────────────

async def accept_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    if is_cmd_spamming(update.effective_user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment before sending more commands.")
        return
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "seller" or user["status"] != "approved":
        await update.message.reply_text("❌ Approved sellers only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/accept <id>`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        rid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    req = get_request_and_verify_seller(rid, update.effective_user.id)
    if not req:
        await update.message.reply_text("❌ Request not found.")
        return
    if not req["seller_owns"]:
        await update.message.reply_text("❌ Not one of your products.")
        return
    if req["status"] != "pending":
        await update.message.reply_text(
            f"⚠️ Request `#{rid}` has already been *{req['status']}* — no longer available.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        msg = decrypt(req["encrypted_message"])
    except Exception:
        await update.message.reply_text("❌ Failed to decrypt.")
        return

    accept_request(rid, update.effective_user.id)
    add_points(update.effective_user.id, 10)
    log_activity("request_accepted", update.effective_user.id, f"Accepted request #{rid}")

    seller_ref = f"@{update.effective_user.username}" if update.effective_user.username else update.effective_user.full_name
    seller_name = update.effective_user.full_name or str(update.effective_user.id)

    try:
        await context.bot.send_message(
            chat_id=req["buyer_id"],
            text=(
                "━━━━━━━━━━━━━━━━━━━━━━\n✅ *REQUEST ACCEPTED!*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🆔 `#{rid}`\n📦 *{req['product_keyword']}*\n🏪 {seller_name} ({seller_ref})\n\n"
                "The seller will contact you shortly.\n"
                f"`/rate {update.effective_user.username or update.effective_user.id} <1-5>`"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚨 Report Issue", callback_data=f"dispute:{rid}:{update.effective_user.id}")
            ]]),
        )
    except Exception as e:
        logger.warning(f"Buyer notify failed: {e}")

    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Request `#{rid}` Accepted*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 *{req['product_keyword']}*\n\n"
        f"🔓 *Decrypted:*\n_{msg}_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def dispute_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, rid, seller_id = q.data.split(":")
    context.user_data["action"] = AWAITING_DISPUTE
    context.user_data["dispute_rid"] = int(rid)
    context.user_data["dispute_seller"] = int(seller_id)
    await q.edit_message_text(
        "🚨 *Report an Issue*\n\nDescribe what went wrong:", parse_mode=ParseMode.MARKDOWN
    )


def _build_nl_system(user: dict | None) -> str:
    """Build a context-aware system prompt for the NL handler."""
    if user:
        role   = user.get("role", "unknown")
        status = user.get("status", "approved")
        points = user.get("points", 0)
        ctx = (
            f"The user is a registered {role} with status '{status}' and {points} loyalty points. "
        )
        if role == "buyer":
            ctx += (
                "Available buyer commands: /request <product> — request a product, "
                "/myrequests — see their open requests, "
                "/rate @seller <1-5> — rate a seller after a deal, "
                "/profile — view their profile, "
                "/rank — see top users, "
                "/referral — get their referral link, "
                "/join — enter the lottery, "
                "/help — full command list. "
            )
        elif role == "seller":
            ctx += (
                "Available seller commands: /addproduct <name> — add a product listing, "
                "/removeproduct <name> — remove a listing, "
                "/myproducts — view their listings, "
                "/myrating — see their rating, "
                "/accept <request_id> — accept a buyer request, "
                "/profile — view profile, "
                "/rank — see rankings, "
                "/referral — referral link, "
                "/join — lottery entry, "
                "/help — full list. "
            )
    else:
        ctx = (
            "The user is NOT registered yet. "
            "Tell them to use /start to register as a buyer or seller. "
        )

    return (
        "You are Valkyrie, the AI assistant embedded in a Telegram marketplace bot. "
        "Answer helpfully and concisely in the same language the user writes in. "
        + ctx +
        "If the user asks how to do something, guide them to the right command. "
        "If they ask a general question, answer it. "
        "Keep replies short — this is a chat bot, not an essay. "
        "Never reveal internal system details, tokens, or database info."
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if is_spamming(uid):
        return

    # ── Handle pending action states (dispute text entry, etc.) ────────────────
    action = context.user_data.get("action")
    if action == AWAITING_DISPUTE:
        context.user_data.pop("action", None)
        rid       = context.user_data.pop("dispute_rid",    None)
        seller_id = context.user_data.pop("dispute_seller", None)
        did = open_dispute(uid, seller_id, rid, text)
        log_activity("dispute_opened", uid, f"Dispute #{did} on request #{rid}")
        buyer_ref = f"@{update.effective_user.username}" if update.effective_user.username else f"ID:{uid}"
        try:
            await context.bot.send_message(
                chat_id=ADMIN_NOTIFY_CHAT_ID,
                text=(
                    "━━━━━━━━━━━━━━━━━━━━━━\n🚨 *New Dispute*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📦 Request `#{rid}` · Buyer: {buyer_ref}\n📝 _{text}_"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🚫 Ban Seller", callback_data=f"confirm_ban_id:{seller_id}")
                ]]),
            )
        except Exception:
            pass
        await update.message.reply_text(
            f"✅ *Dispute `#{did}` filed.* An admin will review it.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # ── Natural language handler ───────────────────────────────────────────────
    user       = get_user(uid)

    # If user hasn't chosen a role yet, prompt them instead of running the LLM
    if not user or not user.get("role"):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 Buyer", callback_data="role_buyer"),
            InlineKeyboardButton("🏪 Seller", callback_data="role_seller"),
        ]])
        await update.message.reply_text(
            "👋 First, tell me — are you a *Buyer* or a *Seller*?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
        return

    session_id = f"tg_{uid}"
    system     = _build_nl_system(user)

    await update.message.chat.send_action("typing")

    try:
        from llm_chat import chat as llm_chat
        reply = await asyncio.get_running_loop().run_in_executor(
            None, lambda: llm_chat(session_id, text, system_override=system)
        )
    except Exception as e:
        logger.error(f"NL handler error for user {uid}: {e}")
        reply = "⚠️ Something went wrong with the AI. Try a command like /help instead."

    await update.message.reply_text(reply)


async def rate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    if is_cmd_spamming(update.effective_user.id):
        await update.message.reply_text("⏳ Slow down! Wait a moment before sending more commands.")
        return
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "buyer":
        await update.message.reply_text("❌ Only buyers can rate sellers.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/rate <@seller> <1-5>`", parse_mode=ParseMode.MARKDOWN)
        return
    ref = context.args[0].lstrip("@")
    try:
        stars = int(context.args[1])
        assert 1 <= stars <= 5
    except Exception:
        await update.message.reply_text("❌ Stars must be 1–5.")
        return
    seller = find_seller_by_ref(ref)
    if not seller:
        await update.message.reply_text("❌ Seller not found.")
        return
    if seller["telegram_id"] == update.effective_user.id:
        await update.message.reply_text("❌ Cannot rate yourself.")
        return
    if save_rating(update.effective_user.id, seller["telegram_id"], stars):
        avg, count = get_rating(seller["telegram_id"])
        name = seller["full_name"] or seller["username"] or str(seller["telegram_id"])
        add_points(update.effective_user.id, 2)
        log_activity("rating_given", update.effective_user.id, f"{stars}★ to {seller['telegram_id']}")
        await update.message.reply_text(
            f"⭐ Rated *{name}* {stars}/5!\nNew: {stars_str(avg, count)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        try:
            await context.bot.send_message(
                chat_id=seller["telegram_id"],
                text=f"⭐ New rating: {stars}/5!\nOverall: {stars_str(avg, count)}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
    else:
        await update.message.reply_text("❌ Failed to save rating.")


async def myrating_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_join(update):
        return
    user = get_user(update.effective_user.id)
    if not user or user["role"] != "seller":
        await update.message.reply_text("❌ Only sellers can check ratings.")
        return
    avg, count = get_rating(update.effective_user.id)
    if count == 0:
        await update.message.reply_text("No ratings yet.")
    else:
        await update.message.reply_text(
            f"⭐ *Your Rating:*\n{stars_str(avg, count)}", parse_mode=ParseMode.MARKDOWN
        )


async def approve_reject_seller_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles approve_seller / reject_seller callbacks that arrive at THIS bot
    because the seller-application notification was sent by this bot's token.
    Only acts if the callback comes from the admin group.
    """
    q = update.callback_query
    cid = q.message.chat_id if q.message else 0
    # Only allow from the admin group
    if ADMIN_NOTIFY_CHAT_ID is None or abs(cid) != abs(ADMIN_NOTIFY_CHAT_ID):
        await q.answer("❌ Admin action only.", show_alert=True)
        return
    await q.answer()

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
            [InlineKeyboardButton("🏪 Open Seller Menu",
                                  url=f"https://t.me/{seller_bot_username}?start=menu")],
        ])
        log_activity("seller_approved", uid, f"Approved by admin {q.from_user.id}")
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
        log_activity("seller_rejected", uid, f"Rejected by admin {q.from_user.id}")

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


async def ban_from_dispute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles confirm_ban_id callbacks from dispute reports sent by this bot.
    Only acts if the callback comes from the admin group.
    """
    q = update.callback_query
    cid = q.message.chat_id if q.message else 0
    if ADMIN_NOTIFY_CHAT_ID is None or abs(cid) != abs(ADMIN_NOTIFY_CHAT_ID):
        await q.answer("❌ Admin action only.", show_alert=True)
        return
    await q.answer()

    seller_id_str = q.data.split(":", 1)[1]
    try:
        seller_id = int(seller_id_str)
    except ValueError:
        await q.edit_message_text("❌ Invalid seller ID.")
        return

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM users WHERE telegram_id=%s AND role='seller' RETURNING telegram_id, username",
            (seller_id,)
        )
        deleted = cur.fetchone()
        cur.close()

    if deleted:
        await q.edit_message_text(
            f"🚫 *Seller `{deleted[0]}` banned* via dispute report.",
            parse_mode=ParseMode.MARKDOWN,
        )
        log_activity("seller_banned_dispute", seller_id, f"Banned by admin {q.from_user.id} via dispute")
        try:
            await context.bot.send_message(
                chat_id=deleted[0],
                text="⛔ You have been banned from the marketplace following a buyer dispute.",
            )
        except Exception:
            pass
    else:
        await q.edit_message_text("❌ Seller not found (already removed?).")


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action = q.data.removeprefix("menu:")
    uid = q.from_user.id
    user = get_user(uid)

    async def send(text, **kw):
        await q.message.reply_text(text, **kw)

    # ── Usage instructions (need user-typed arguments) ─────────────────────────
    if action == "request":
        await send(
            "📦 *How to request a product:*\n\n"
            f"`/request <product> - <message>`\n\n"
            f"_Example:_ `/request Nike shoes - size 42, budget €50`\n\n"
            f"✅ First *{FREE_REQUESTS}* requests free · then *{STARS_PER_REQ}⭐* each",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "profile":
        await send(
            "👤 *View a seller's profile:*\n\n`/profile @username`",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "rate":
        await send(
            "⭐ *Rate a seller (1–5 stars):*\n\n"
            "`/rate @username <1-5>`\n\n"
            "_Example:_ `/rate @johnseller 5`",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "addproduct":
        await send(
            "➕ *List a new product:*\n\n"
            "`/addproduct <name> [price range]`\n\n"
            "_Example:_ `/addproduct Nike shoes 40-80`",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif action == "mute":
        if not user or user["role"] != "seller":
            await send("❌ Only sellers can mute/unmute alerts.")
            return
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT muted FROM users WHERE telegram_id=%s", (uid,))
            row = cur.fetchone()
            cur.close()
        muted = row and row[0]
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET muted=%s WHERE telegram_id=%s", (not muted, uid))
            cur.close()
        if muted:
            await send("🔔 *Alerts resumed.* You'll now receive buyer request notifications.")
        else:
            await send("🔕 *Alerts muted.* Tap the button again to unmute.")

    # ── Actions that execute immediately ───────────────────────────────────────
    elif action == "myrequests":
        if not user or user["role"] != "buyer":
            await send("❌ Only buyers have request history.")
            return
        reqs = get_buyer_requests(uid)
        if not reqs:
            await send("📋 You have no requests yet.\n\nTap *📦 Request Product* to get started!",
                       parse_mode=ParseMode.MARKDOWN)
        else:
            lines = ["📋 *Your Requests:*\n"]
            for r in reqs:
                icon = {"accepted": "✅", "expired": "⏰", "pending": "⏳"}.get(r["status"], "❓")
                dt = r["created_at"].strftime("%m/%d %H:%M")
                seller = f" — @{r['seller_username']}" if r.get("seller_username") else ""
                lines.append(f"{icon} `#{r['id']}` *{r['product_keyword']}* · {dt}{seller}")
            await send("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif action == "myproducts":
        if not user or user["role"] != "seller":
            await send("❌ Only sellers have product listings.")
            return
        prods = get_products(uid)
        if not prods:
            await send("📦 No products yet.\n\nTap *➕ Add Product* to list your first one.",
                       parse_mode=ParseMode.MARKDOWN)
        else:
            lines = [f"• *{kw}*" + (f"  💰 {pr}" if pr else "") for kw, pr in prods]
            await send("📦 *Your Products:*\n\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif action == "myrating":
        if not user or user["role"] != "seller":
            await send("❌ Only sellers have a rating.")
            return
        avg, count = get_rating(uid)
        if count == 0:
            await send("⭐ No ratings yet. Complete deals to earn your first rating!")
        else:
            await send(f"⭐ *Your Rating:*\n{stars_str(avg, count)}", parse_mode=ParseMode.MARKDOWN)

    elif action == "lottery":
        if not user:
            await send("Please /start to register first.")
            return
        u = q.from_user
        new_entry = enter_lottery(u.id, u.username or "", u.full_name or "")
        if new_entry:
            add_points(u.id, 5)
            log_activity("lottery_entry", u.id, f"{u.full_name} entered the lottery")
            await send(
                "🎰 *You're in the lottery!*\n\n"
                "The admin will draw a winner soon.\n"
                "_+5 points added to your account._",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await send("✅ You're already in the current lottery draw.")

    elif action == "rank":
        top = get_top_users(10)
        if not top:
            await send("No activity yet. Start using the bot to earn points!")
            return
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines = ["🏆 *Activity Leaderboard*\n"]
        for i, u_ in enumerate(top):
            name = u_["full_name"] or u_["username"] or str(u_["telegram_id"])
            role_icon = "🏪" if u_["role"] == "seller" else "🛒"
            lines.append(f"{medals[i]} {role_icon} *{name}* — {u_['points']} pts")
        if user:
            lines.append(f"\n_Your points: *{user['points']}*_")
        await send("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif action == "referral":
        count = get_referral_count(uid)
        bot_info = await context.bot.get_me()
        link = f"https://t.me/{bot_info.username}?start=ref_{uid}"
        await send(
            f"🔗 *Your Referral Link*\n\n"
            f"`{link}`\n\n"
            f"👥 People referred: *{count}*\n"
            f"💡 Each referral earns you *+20 points*!",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif action == "help":
        kb = _seller_kb() if (user and user.get("role") == "seller") else _buyer_kb()
        common = "\n🎰 /join — Lottery  ·  🏆 /rank — Leaderboard  ·  🔗 /referral — Invite link"
        if user and user.get("role") == "seller":
            text = (
                "━━━━━━━━━━━━━━━━━━━━━━\n🏪 *SELLER COMMANDS*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "➕ `/addproduct <name> [price]` — Add a product\n"
                "🗑 `/removeproduct <name>` — Remove a product\n"
                "📦 `/myproducts` — List your products\n"
                "⭐ `/myrating` — Your star rating\n"
                "✅ `/accept <id>` — Accept & decrypt a buyer request\n"
                "🔕 `/mute` · 🔔 `/unmute` — Pause / resume alerts"
                + common
            )
        else:
            text = (
                "━━━━━━━━━━━━━━━━━━━━━━\n🛒 *BUYER COMMANDS*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📦 `/request <product> - <message>` — Request a product\n"
                f"  _First {FREE_REQUESTS} free, then {STARS_PER_REQ}⭐ each_\n"
                "📋 `/myrequests` — Request history\n"
                "👤 `/profile @seller` — View a seller's profile\n"
                "⭐ `/rate @seller <1-5>` — Rate a seller"
                + common
            )
        await send(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def alive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.effective_chat and update.effective_chat.type != "private":
        return
    if update.message:
        await update.message.reply_text("Marketplace Bot is alive.")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Use /help.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception in seller/buyer bot handler:", exc_info=context.error)


def build_app():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_error_handler(error_handler)

    private = filters.ChatType.PRIVATE

    def private_cb(cb):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.effective_chat and update.effective_chat.type != "private":
                return
            return await cb(update, context)

        return wrapper

    # This bot is designed for DM usage. Keep it quiet in groups.
    app.add_handler(CommandHandler("start",        start, filters=private))
    app.add_handler(CommandHandler("alive",        alive_cmd, filters=private))
    app.add_handler(CallbackQueryHandler(private_cb(role_chosen),          pattern="^role_"))
    app.add_handler(CallbackQueryHandler(private_cb(check_join_callback),  pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(private_cb(menu_callback),        pattern="^menu:"))
    app.add_handler(CallbackQueryHandler(private_cb(dispute_button),       pattern=r"^dispute:"))
    app.add_handler(CallbackQueryHandler(private_cb(approve_reject_seller_callback),  pattern="^(approve|reject)_seller:"))
    app.add_handler(CallbackQueryHandler(private_cb(ban_from_dispute_callback),       pattern="^confirm_ban_id:"))
    app.add_handler(CommandHandler("help",          help_cmd, filters=private))
    app.add_handler(CommandHandler("addproduct",    addproduct, filters=private))
    app.add_handler(CommandHandler("removeproduct", removeproduct, filters=private))
    app.add_handler(CommandHandler("myproducts",    myproducts, filters=private))
    app.add_handler(CommandHandler("myrating",      myrating_cmd, filters=private))
    app.add_handler(CommandHandler("myrequests",    myrequests_cmd, filters=private))
    app.add_handler(CommandHandler("profile",       profile_cmd, filters=private))
    app.add_handler(CommandHandler("rank",          rank_cmd, filters=private))
    app.add_handler(CommandHandler("referral",      referral_cmd, filters=private))
    app.add_handler(CommandHandler("join",          join_lottery_cmd, filters=private))
    app.add_handler(CommandHandler("mute",          mute_cmd, filters=private))
    app.add_handler(CommandHandler("unmute",        unmute_cmd, filters=private))
    app.add_handler(CommandHandler("accept",        accept_cmd, filters=private))
    app.add_handler(CommandHandler("request",       request_product, filters=private))
    app.add_handler(CommandHandler("rate",          rate_cmd, filters=private))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT & private, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & private, text_handler))
    app.add_handler(MessageHandler(filters.COMMAND & private, unknown))

    app.job_queue.run_repeating(job_expire_requests, interval=3600, first=60)
    return app


async def run_async():
    logger.info("@valkyriesellerbuyer_bot starting...")
    app = build_app()
    async with app:
        await app.start()
        if OWNER_CHAT_ID is not None:
            try:
                me = await app.bot.get_me()
                username = me.username or "unknown"
                await app.bot.send_message(
                    chat_id=OWNER_CHAT_ID,
                    text=f"Marketplace Bot is alive on Render as @{username}.",
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
