"""
Admin REST API — bridges external clients (Signal bot, dashboards, etc.)
to the marketplace database and Telegram Bot API.

Authentication: every request must include  X-API-Key: <BRIDGE_API_KEY>

Base URL  (when running in Replit):  https://<repl-domain>/admin/
All routes below are prefixed with /admin/

Endpoints
─────────
GET  /admin/health
GET  /admin/stats
GET  /admin/users?role=&status=&limit=
GET  /admin/requests?status=&limit=
GET  /admin/activity?limit=
GET  /admin/ranking?limit=
GET  /admin/lottery/entries
POST /admin/lottery/draw
DELETE /admin/lottery
POST /admin/broadcast        { "text": "..." }
POST /admin/ban              { "ref": "@username | user_id" }
POST /admin/approve          { "ref": "@username | user_id" }
POST /admin/warn             { "ref": "@username | user_id", "reason": "..." }
POST /admin/remove           { "ref": "@username | user_id" }
GET  /admin/disputes?status=open
"""

import os
import time
import asyncio
import logging
import psycopg2
import psycopg2.extras
import psycopg2.pool
import requests as http
from contextlib import contextmanager
from functools import wraps
from flask import Flask, request, jsonify

logging.basicConfig(
    format="%(asctime)s [ADMIN-API] %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL.")

BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("VALKYRIEGROUPMOD_BOT_TOKEN")
    or ""
)
if not BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN (or VALKYRIEGROUPMOD_BOT_TOKEN).")

SELLER_TOKEN = (
    os.environ.get("SELLER_BUYER_BOT_TOKEN")
    or os.environ.get("VALKYRIESELLERBUYER_BOT_TOKEN")
    or ""
)
if not SELLER_TOKEN:
    raise RuntimeError("Missing SELLER_BUYER_BOT_TOKEN (or VALKYRIESELLERBUYER_BOT_TOKEN).")
BRIDGE_API_KEY = os.environ.get("BRIDGE_API_KEY", "changeme-set-BRIDGE_API_KEY-secret")

TG_API        = f"https://api.telegram.org/bot{BOT_TOKEN}"
TG_API_SELLER = f"https://api.telegram.org/bot{SELLER_TOKEN}"

app = Flask(__name__)
_pool: psycopg2.pool.SimpleConnectionPool | None = None
_PG_APP_NAME = os.environ.get("PG_APP_NAME", "valkyrie_admin_api")


def _get_pool():
    global _pool
    if _pool is None:
        # Add application_name so Postgres logs show which component is connecting.
        _pool = psycopg2.pool.SimpleConnectionPool(1, 5, DATABASE_URL, application_name=_PG_APP_NAME)
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


# ── Auth middleware ────────────────────────────────────────────────────────────

def require_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if key != BRIDGE_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


# ── Telegram helpers ───────────────────────────────────────────────────────────

def tg_send(chat_id: int, text: str, token: str = None):
    """Send a Telegram message via Bot API. Returns True on success."""
    api = f"https://api.telegram.org/bot{token or BOT_TOKEN}"
    try:
        r = http.post(f"{api}/sendMessage", json={
            "chat_id": chat_id, "text": text, "parse_mode": "Markdown"
        }, timeout=8)
        return r.ok
    except Exception as e:
        logger.warning(f"tg_send failed: {e}")
        return False


def tg_send_all(text: str) -> dict:
    """Broadcast text to all registered users via seller-buyer bot token."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT telegram_id FROM users")
        ids = [r[0] for r in cur.fetchall()]
        cur.close()
    sent = failed = 0
    for uid in ids:
        ok = tg_send(uid, text, token=SELLER_TOKEN)
        if ok:
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "total": len(ids)}


def resolve_user(ref: str):
    """Return user row by @username or numeric ID."""
    ref = ref.lstrip("@").strip()
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM users WHERE username=%s OR telegram_id::text=%s LIMIT 1",
            (ref, ref)
        )
        u = cur.fetchone()
        cur.close()
    return u


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/admin/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/admin/status")
def public_status():
    """Public endpoint — safe summary stats for the status dashboard."""
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE role='seller' AND status='approved') AS sellers,
                    COUNT(*) FILTER (WHERE role='buyer')                        AS buyers,
                    COUNT(*)                                                    AS total_users
                FROM users
            """)
            row = cur.fetchone()
            sellers, buyers, total_users = (row[0] or 0), (row[1] or 0), (row[2] or 0)

            cur.execute("""
                SELECT
                    COUNT(*)                                  AS total,
                    COUNT(*) FILTER (WHERE status='pending')  AS pending,
                    COUNT(*) FILTER (WHERE status='accepted') AS accepted
                FROM product_requests
            """)
            row2 = cur.fetchone()
            total_reqs, pending_reqs, accepted_reqs = (row2[0] or 0), (row2[1] or 0), (row2[2] or 0)

            cur.execute("SELECT COUNT(*) FROM lottery_entries")
            lottery = cur.fetchone()[0] or 0

            cur.execute("SELECT ROUND(AVG(stars)::numeric,2) FROM ratings")
            avg_stars = cur.fetchone()[0] or 0

            cur.close()
        db_ok = True
    except Exception:
        sellers = buyers = total_users = total_reqs = pending_reqs = accepted_reqs = lottery = 0
        avg_stars = 0
        db_ok = False

    import time
    return jsonify({
        "api": True,
        "db": db_ok,
        "timestamp": int(time.time()),
        "stats": {
            "total_users": int(total_users),
            "sellers": int(sellers),
            "buyers": int(buyers),
            "total_requests": int(total_reqs),
            "pending_requests": int(pending_reqs),
            "accepted_requests": int(accepted_reqs),
            "lottery_entries": int(lottery),
            "avg_rating": float(avg_stars),
        },
    })


@app.get("/admin/stats")
@require_api_key
def stats():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE role='seller' AND status='approved') AS sellers,
                COUNT(*) FILTER (WHERE role='seller' AND status='pending')  AS pending_sellers,
                COUNT(*) FILTER (WHERE role='buyer')                        AS buyers,
                COUNT(*)                                                    AS total_users
            FROM users
        """)
        s, ps, b, total = cur.fetchone()
        cur.execute("""
            SELECT
                COUNT(*)                                  AS total_requests,
                COUNT(*) FILTER (WHERE status='accepted') AS accepted,
                COUNT(*) FILTER (WHERE status='pending')  AS pending,
                COUNT(*) FILTER (WHERE status='expired')  AS expired
            FROM product_requests
        """)
        tr, ac, pend, exp = cur.fetchone()
        cur.execute("SELECT COUNT(*), ROUND(AVG(stars)::numeric,2) FROM ratings")
        rat_cnt, avg_stars = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM lottery_entries")
        lottery_entries = cur.fetchone()[0]
        cur.close()
    return jsonify({
        "users": {"total": total, "sellers": s, "sellers_pending": ps, "buyers": b},
        "requests": {"total": tr, "accepted": ac, "pending": pend, "expired": exp},
        "ratings": {"count": rat_cnt, "avg": float(avg_stars or 0)},
        "lottery_entries": lottery_entries,
    })


@app.get("/admin/users")
@require_api_key
def users():
    role   = request.args.get("role")
    status = request.args.get("status")
    limit  = min(int(request.args.get("limit", 50)), 200)
    conds  = []
    vals   = []
    if role:   conds.append("role=%s");   vals.append(role)
    if status: conds.append("status=%s"); vals.append(status)
    where  = ("WHERE " + " AND ".join(conds)) if conds else ""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            f"SELECT telegram_id,username,full_name,role,status,points,registered_at FROM users {where} ORDER BY registered_at DESC LIMIT %s",
            vals + [limit]
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    for r in rows:
        if r.get("registered_at"):
            r["registered_at"] = r["registered_at"].isoformat()
    return jsonify(rows)


@app.get("/admin/requests")
@require_api_key
def requests_list():
    status = request.args.get("status")
    limit  = min(int(request.args.get("limit", 50)), 200)
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cond  = "AND pr.status=%s" if status else ""
        vals  = [status, limit] if status else [limit]
        cur.execute(f"""
            SELECT pr.id, pr.product_keyword, pr.status, pr.created_at,
                   u.username as buyer_username, u.full_name as buyer_name
            FROM product_requests pr JOIN users u ON u.telegram_id=pr.buyer_id
            WHERE 1=1 {cond}
            ORDER BY pr.created_at DESC LIMIT %s
        """, vals)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return jsonify(rows)


@app.get("/admin/activity")
@require_api_key
def activity():
    limit = min(int(request.args.get("limit", 50)), 500)
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT event_type,user_id,description,created_at FROM activity_log ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
    return jsonify(rows)


@app.get("/admin/ranking")
@require_api_key
def ranking():
    limit = min(int(request.args.get("limit", 20)), 100)
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT telegram_id,username,full_name,role,points FROM users WHERE points>0 ORDER BY points DESC LIMIT %s",
            (limit,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    return jsonify(rows)


@app.get("/admin/disputes")
@require_api_key
def disputes():
    status = request.args.get("status", "open")
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM disputes WHERE status=%s ORDER BY created_at DESC LIMIT 50",
            (status,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    for r in rows:
        for k in ("created_at",):
            if r.get(k): r[k] = r[k].isoformat()
    return jsonify(rows)


# ── Lottery ────────────────────────────────────────────────────────────────────

@app.get("/admin/lottery/entries")
@require_api_key
def lottery_entries():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT user_id,username,full_name,entered_at FROM lottery_entries ORDER BY entered_at")
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
    for r in rows:
        if r.get("entered_at"): r["entered_at"] = r["entered_at"].isoformat()
    return jsonify(rows)


@app.post("/admin/lottery/draw")
@require_api_key
def lottery_draw():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT user_id,username,full_name FROM lottery_entries ORDER BY RANDOM() LIMIT 1")
        winner = cur.fetchone()
        cur.close()
    if not winner:
        return jsonify({"error": "No entries"}), 400
    name  = winner["full_name"] or winner["username"] or str(winner["user_id"])
    uname = f"@{winner['username']}" if winner["username"] else f"ID:{winner['user_id']}"
    tg_send(winner["user_id"],
            "🎉 *Congratulations — you won the lottery!* An admin will contact you about your prize.",
            token=SELLER_TOKEN)
    return jsonify({"winner": {"name": name, "username": uname, "id": winner["user_id"]}})


@app.delete("/admin/lottery")
@require_api_key
def lottery_clear():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM lottery_entries")
        deleted = cur.rowcount
        cur.close()
    return jsonify({"cleared": deleted})


# ── Actions ────────────────────────────────────────────────────────────────────

@app.post("/admin/broadcast")
@require_api_key
def broadcast():
    body = request.json or {}
    text = body.get("text", "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    result = tg_send_all(f"📢 *Admin Broadcast:*\n\n{text}")
    return jsonify(result)


@app.post("/admin/ban")
@require_api_key
def ban():
    body = request.json or {}
    ref  = body.get("ref", "").strip()
    if not ref:
        return jsonify({"error": "ref is required"}), 400
    user = resolve_user(ref)
    if not user:
        return jsonify({"error": "User not found"}), 404
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE telegram_id=%s", (user["telegram_id"],))
        cur.close()
    tg_send(user["telegram_id"],
            "⛔ You have been banned from the marketplace by an admin.",
            token=SELLER_TOKEN)
    return jsonify({"banned": user["telegram_id"], "username": user.get("username")})


@app.post("/admin/approve")
@require_api_key
def approve():
    body = request.json or {}
    ref  = body.get("ref", "").strip()
    if not ref:
        return jsonify({"error": "ref is required"}), 400
    user = resolve_user(ref)
    if not user:
        return jsonify({"error": "User not found"}), 404
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET status='approved' WHERE telegram_id=%s AND role='seller'", (user["telegram_id"],))
        updated = cur.rowcount
        cur.close()
    if not updated:
        return jsonify({"error": "User is not a pending seller"}), 400
    tg_send(user["telegram_id"],
            "✅ *Seller account approved!* Use /addproduct to list your products.",
            token=SELLER_TOKEN)
    return jsonify({"approved": user["telegram_id"]})


@app.post("/admin/warn")
@require_api_key
def warn():
    body   = request.json or {}
    ref    = body.get("ref", "").strip()
    reason = body.get("reason", "Violation of marketplace rules").strip()
    if not ref:
        return jsonify({"error": "ref is required"}), 400
    user = resolve_user(ref)
    if not user:
        return jsonify({"error": "User not found"}), 404
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO warnings(user_id,reason) VALUES(%s,%s)",
            (user["telegram_id"], reason)
        )
        cur.close()
    tg_send(user["telegram_id"],
            f"⚠️ *Official Warning*\n\nReason: {reason}\n\n_Further violations may result in a ban._",
            token=SELLER_TOKEN)
    return jsonify({"warned": user["telegram_id"], "reason": reason})


@app.delete("/admin/users/<ref>")
@require_api_key
def remove_user(ref):
    user = resolve_user(ref)
    if not user:
        return jsonify({"error": "User not found"}), 404
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE telegram_id=%s", (user["telegram_id"],))
        cur.close()
    return jsonify({"removed": user["telegram_id"]})


# ── Natural language chat endpoint ─────────────────────────────────────────────
#
#  POST /chat
#  Body: { "message": "...", "session_id": "optional-string", "user_id": 123 }
#  No API key required — public endpoint (rate-limited by IP via simple in-memory window)
#  Returns: { "reply": "...", "provider": "Groq" }
#
#  POST /admin/chat   (same but requires X-API-Key, used for admin NL commands)
#  Body: { "message": "...", "user_id": 123 }

import threading as _threading
_chat_rl: dict = {}   # ip → [timestamps]
_chat_rl_lock = _threading.Lock()

def _chat_rate_ok(ip: str, limit: int = 20, window: int = 60) -> bool:
    now = time.time()
    with _chat_rl_lock:
        ts = _chat_rl.get(ip, [])
        ts = [t for t in ts if now - t < window]
        if len(ts) >= limit:
            return False
        ts.append(now)
        _chat_rl[ip] = ts
    return True



@app.post("/chat")
def public_chat():
    """Public natural language chat — no API key, rate limited."""
    ip = request.remote_addr or "unknown"
    if not _chat_rate_ok(ip):
        return jsonify({"error": "Rate limit exceeded. Max 20 messages per minute."}), 429

    body       = request.json or {}
    message    = (body.get("message") or "").strip()
    session_id = str(body.get("session_id") or body.get("user_id") or ip)

    if not message:
        return jsonify({"error": "message is required"}), 400
    if len(message) > 2000:
        return jsonify({"error": "message too long (max 2000 chars)"}), 400

    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(__file__))
    from llm_chat import chat as llm_chat
    reply = llm_chat(session_id, message)
    return jsonify({"reply": reply, "session_id": session_id})


@app.post("/admin/chat")
@require_api_key
def admin_chat():
    """Admin natural language chat — requires API key, full context access."""
    body       = request.json or {}
    message    = (body.get("message") or "").strip()
    session_id = str(body.get("session_id") or body.get("user_id") or "admin")
    user_ref   = (body.get("user_ref") or "").strip()

    if not message:
        return jsonify({"error": "message is required"}), 400

    system = (
        "You are Valkyrie Admin AI. You help marketplace admins manage users, "
        "interpret reports, draft broadcasts, and answer questions about the platform. "
        "Be direct and concise. You have access to all admin functions via the REST API."
    )

    # Optionally inject user context if user_ref provided
    if user_ref:
        user = resolve_user(user_ref)
        if user:
            system += (
                f" Context: currently discussing user @{user.get('username','?')} "
                f"(ID {user['telegram_id']}), role={user.get('role')}, "
                f"status={user.get('status')}, points={user.get('points',0)}."
            )

    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(__file__))
    from llm_chat import chat as llm_chat
    reply = llm_chat(session_id, message, system_override=system)
    return jsonify({"reply": reply, "session_id": session_id})


# ── Run ────────────────────────────────────────────────────────────────────────

def run():
    port = int(os.environ.get("BRIDGE_API_PORT", 5050))
    logger.info(f"Admin API starting on port {port}")
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    run()
