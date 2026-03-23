"""
Discord → Telegram Admin Bridge
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Runs a Discord bot that mirrors every admin command to the
marketplace REST API, letting you control all Telegram groups
from a Discord server.

Required secrets (Replit → Secrets):
  DISCORD_BOT_TOKEN      — your Discord bot token
  BRIDGE_API_KEY         — same key used by admin_api.py

Optional secrets:
  DISCORD_ADMIN_CHANNEL  — channel ID(s) the bot will accept
                           commands in (comma-separated).
                           Leave blank → any channel works.
  BRIDGE_API_URL         — defaults to http://localhost:5050

Setup
─────
1. Go to https://discord.com/developers/applications
2. Create a new application → Bot → copy the token → add to secrets as DISCORD_BOT_TOKEN
3. Bot permissions needed:  Send Messages, Embed Links, Read Message History
4. Invite URL: https://discord.com/api/oauth2/authorize?client_id=<APP_ID>&permissions=67584&scope=bot
5. Set DISCORD_ADMIN_CHANNEL to the ID of the private admin channel (right-click → Copy ID)
6. python3 bot/discord_bridge.py   (or it starts automatically from bot.py)

Available commands (prefix !)
──────────────────────────────
!help               show all commands
!stats              marketplace statistics
!users              list all users
!sellers            approved sellers
!pending            sellers awaiting approval
!requests           recent product requests
!activity           activity log
!rank               points leaderboard
!lottery            show lottery entries
!lottery draw       randomly pick a winner
!lottery clear      clear all entries
!broadcast <msg>    send message to ALL marketplace users
!ban @user|ID       ban & remove a user
!approve @user|ID   approve a pending seller
!warn @user|ID <r>  issue an official warning
!disputes           open disputes list
"""

import asyncio
import logging
import os
import sys

import discord
import requests

logging.basicConfig(
    format="%(asctime)s [DISCORD] %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

API_URL   = os.environ.get("BRIDGE_API_URL", "http://localhost:5050")
API_KEY   = os.environ.get("BRIDGE_API_KEY", "changeme-set-BRIDGE_API_KEY-secret")
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

_raw_channels  = os.environ.get("DISCORD_ADMIN_CHANNEL", "")
ADMIN_CHANNELS = {int(c.strip()) for c in _raw_channels.split(",") if c.strip()}

HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# ── API helpers ────────────────────────────────────────────────────────────────

def api_get(path: str, **params):
    r = requests.get(f"{API_URL}{path}", headers=HEADERS, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def api_post(path: str, body: dict = None):
    r = requests.post(f"{API_URL}{path}", headers=HEADERS, json=body or {}, timeout=10)
    r.raise_for_status()
    return r.json()


def api_delete(path: str):
    r = requests.delete(f"{API_URL}{path}", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


# ── Discord bot ────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)


def is_authorised(message: discord.Message) -> bool:
    if not ADMIN_CHANNELS:
        return True
    return message.channel.id in ADMIN_CHANNELS


async def send_chunks(message: discord.Message, text: str):
    """Discord has a 2000-char limit; split if needed."""
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 1990:
            await message.channel.send(f"```\n{chunk}\n```")
            chunk = line
        else:
            chunk = (chunk + "\n" + line).strip()
    if chunk:
        await message.channel.send(f"```\n{chunk}\n```")


def handle_command(parts: list[str], session_id: str = "discord-default") -> str:
    from llm_chat import chat as llm_chat, clear_history as llm_clear
    cmd = parts[0].lower() if parts else ""

    if cmd == "/help":
        return (
            "━━ Telegram Admin Commands ━━\n"
            "/stats              — marketplace stats\n"
            "/users              — all users\n"
            "/sellers            — approved sellers\n"
            "/pending            — pending seller approvals\n"
            "/requests           — recent requests\n"
            "/activity           — activity log\n"
            "/rank               — leaderboard\n"
            "/lottery            — lottery entries\n"
            "/lottery draw       — draw winner\n"
            "/lottery clear      — clear entries\n"
            "/broadcast <msg>    — broadcast to all users\n"
            "/ban @user|ID       — ban user\n"
            "/approve @user|ID   — approve seller\n"
            "/warn @user|ID <r>  — warn user\n"
            "/disputes           — open disputes\n"
            "/chat <message>     — chat with AI assistant\n"
            "/chat clear         — clear your chat history"
        )

    if cmd == "/stats":
        d = api_get("/admin/stats")
        u = d["users"]; rq = d["requests"]; rt = d["ratings"]
        return (
            f"📊 Marketplace Stats\n"
            f"──────────────────────\n"
            f"Users     : {u['total']}  (buyers {u['buyers']}, sellers {u['sellers']}, pending {u['sellers_pending']})\n"
            f"Requests  : {rq['total']}  (accepted {rq['accepted']}, pending {rq['pending']})\n"
            f"Ratings   : {rt['count']}  avg {rt['avg']}/5\n"
            f"Lottery   : {d['lottery_entries']} entries"
        )

    if cmd == "/users":
        rows = api_get("/admin/users", limit=50)
        if not rows:
            return "No users found."
        lines = [f"👥 All Users ({len(rows)}):"]
        for u in rows[:40]:
            name  = u.get("full_name") or u.get("username") or str(u["telegram_id"])
            uname = f"@{u['username']}" if u.get("username") else ""
            lines.append(f"• {name} {uname} [{u.get('role','?')}] {u.get('status','')} {u.get('points',0)}pts")
        if len(rows) > 40:
            lines.append(f"...and {len(rows)-40} more")
        return "\n".join(lines)

    if cmd == "/sellers":
        rows = api_get("/admin/users", role="seller", status="approved", limit=50)
        if not rows:
            return "No approved sellers."
        lines = [f"🛒 Sellers ({len(rows)}):"]
        for u in rows:
            name = u.get("full_name") or u.get("username") or str(u["telegram_id"])
            lines.append(f"• {name}  (@{u.get('username','?')})  {u.get('points',0)}pts")
        return "\n".join(lines)

    if cmd == "/pending":
        rows = api_get("/admin/users", role="seller", status="pending", limit=50)
        if not rows:
            return "✅ No pending seller approvals."
        lines = [f"⏳ Pending Sellers ({len(rows)}):"]
        for u in rows:
            name = u.get("full_name") or u.get("username") or str(u["telegram_id"])
            lines.append(f"• {name}  (ID: {u['telegram_id']})\n  → /approve {u['telegram_id']}")
        return "\n".join(lines)

    if cmd == "/requests":
        rows = api_get("/admin/requests", limit=20)
        if not rows:
            return "No requests."
        lines = [f"📦 Recent Requests ({len(rows)}):"]
        for r in rows:
            lines.append(f"• #{r['id']} {r['product_keyword']} [{r['status']}] — {r.get('buyer_username','?')}")
        return "\n".join(lines)

    if cmd == "/activity":
        rows = api_get("/admin/activity", limit=20)
        if not rows:
            return "No activity."
        lines = [f"📜 Recent Activity ({len(rows)}):"]
        for r in rows:
            lines.append(f"• {r['event_type']}: {r['description']}")
        return "\n".join(lines)

    if cmd == "/rank":
        rows = api_get("/admin/ranking", limit=10)
        if not rows:
            return "🏆 No ranking data yet."
        medals = ["🥇","🥈","🥉"] + ["🏅"]*7
        lines  = ["🏆 Leaderboard:"]
        for i, u in enumerate(rows):
            name = u.get("full_name") or u.get("username") or str(u["telegram_id"])
            lines.append(f"{medals[i]} {name} — {u['points']} pts")
        return "\n".join(lines)

    if cmd == "/lottery":
        sub = parts[1].lower() if len(parts) > 1 else ""
        if sub == "draw":
            d = api_post("/admin/lottery/draw")
            w = d["winner"]
            return f"🎉 Lottery Winner: {w['name']} ({w['username']})\nThey have been notified on Telegram."
        if sub == "clear":
            d = api_delete("/admin/lottery")
            return f"🗑️ Lottery cleared — {d['cleared']} entries removed."
        rows = api_get("/admin/lottery/entries")
        if not rows:
            return "🎰 No lottery entries yet."
        names = [r.get("full_name") or r.get("username") or str(r["user_id"]) for r in rows]
        return f"🎰 Lottery Entries ({len(names)}):\n" + "\n".join(f"• {n}" for n in names[:40])

    if cmd == "/broadcast":
        msg = " ".join(parts[1:]).strip()
        if not msg:
            return "Usage: /broadcast <your message>"
        d = api_post("/admin/broadcast", {"text": msg})
        return f"📢 Broadcast sent!\n✅ {d['sent']} delivered  ❌ {d['failed']} failed"

    if cmd == "/ban":
        ref = parts[1] if len(parts) > 1 else ""
        if not ref:
            return "Usage: /ban @username or /ban <user_id>"
        d = api_post("/admin/ban", {"ref": ref})
        return f"🚫 Banned {d.get('username') or d.get('banned')} and notified them on Telegram."

    if cmd == "/approve":
        ref = parts[1] if len(parts) > 1 else ""
        if not ref:
            return "Usage: /approve @username or /approve <user_id>"
        api_post("/admin/approve", {"ref": ref})
        return f"✅ Seller {ref} approved and notified on Telegram."

    if cmd == "/warn":
        if len(parts) < 2:
            return "Usage: /warn @user <reason>"
        ref    = parts[1]
        reason = " ".join(parts[2:]) if len(parts) > 2 else "Violation of marketplace rules"
        api_post("/admin/warn", {"ref": ref, "reason": reason})
        return f"⚠️ Warning sent to {ref}: {reason}"

    if cmd == "/disputes":
        rows = api_get("/admin/disputes")
        if not rows:
            return "✅ No open disputes."
        lines = [f"🚨 Open Disputes ({len(rows)}):"]
        for d in rows:
            lines.append(f"• #{d['id']} Request #{d['request_id']} — {d['reason'][:60]}")
        return "\n".join(lines)

    if cmd == "/chat":
        sub = parts[1] if len(parts) > 1 else ""
        if sub.lower() == "clear":
            llm_clear(session_id)
            return "🗑️ Chat history cleared."
        message = " ".join(parts[1:]).strip()
        if not message:
            return "Usage: /chat <your message>\n       /chat clear  — reset conversation"
        return llm_chat(session_id=session_id, message=message)

    return f"Unknown command: {cmd}\nType /help for available commands."


@bot.event
async def on_ready():
    logger.info(f"Discord bridge logged in as {bot.user} (ID: {bot.user.id})")
    if ADMIN_CHANNELS:
        logger.info(f"Restricted to channels: {ADMIN_CHANNELS}")
    else:
        logger.info("No channel restriction — responding in any channel.")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if not message.content.startswith("/"):
        return
    if not is_authorised(message):
        return

    parts = message.content.strip().split()
    session_id = f"discord-{message.author.id}"
    logger.info(f"Discord command from {message.author}: {message.content!r}")

    # /chat responses should NOT be wrapped in a code block
    is_chat = parts[0].lower() == "/chat" if parts else False

    async with message.channel.typing():
        try:
            reply = await asyncio.get_event_loop().run_in_executor(
                None, handle_command, parts, session_id
            )
        except requests.HTTPError as e:
            body = {}
            try:
                body = e.response.json()
            except Exception:
                pass
            reply = f"❌ API Error {e.response.status_code}: {body.get('error', str(e))}"
        except Exception as e:
            reply = f"❌ Error: {e}"

    if is_chat:
        # Chat replies sent as plain text (readable, not code block)
        for i in range(0, len(reply), 1990):
            await message.channel.send(reply[i:i+1990])
    else:
        await send_chunks(message, reply)


async def run_async():
    if not BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN is not set — Discord bridge will not start.")
        return
    await bot.start(BOT_TOKEN)


def run():
    if not BOT_TOKEN:
        logger.warning("DISCORD_BOT_TOKEN not set, skipping Discord bridge.")
        return
    asyncio.run(run_async())


if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: Set DISCORD_BOT_TOKEN in your environment.")
        sys.exit(1)
    run()
