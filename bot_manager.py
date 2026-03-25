import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


ROOT_DIR = Path(__file__).resolve().parent
STOP_TIMEOUT_SECONDS = 10


def _normalize_env_aliases() -> None:
    """
    Backward compatible env var aliases.

    A lot of deploy failures are just env var name typos. We normalize the few
    we have seen in the wild so the bots can still start.
    """

    aliases: dict[str, list[str]] = {
        # Common typo (extra "N" in VALKYRIE...)
        "VALKYRIESELLERBUYER_BOT_TOKEN": ["VALKYRIENSELLERBUYER_BOT_TOKEN"],
    }

    for canonical, alt_keys in aliases.items():
        if os.environ.get(canonical):
            continue
        for alt in alt_keys:
            val = os.environ.get(alt)
            if val:
                os.environ[canonical] = val
                break

ENABLED_PROCESSES = {
    "socks5_bot": {
        "label": "Valkyrie Socks5 Tor Bot",
        "token_env": "VALKYRIESOCKS5_BOT_TOKEN",
        "entry": "bots/socks5_bot.py",
        "required_envs": ["VALKYRIESOCKS5_BOT_TOKEN"],
    },
    "menu_bot": {
        "label": "Menu Bot",
        "token_env": "VALKYRIEMENU_BOT_TOKEN",
    },
    "group_guard_bot": {
        "label": "Group Guard Bot",
        "token_env": "VALKYRIEGROUPMOD_BOT_TOKEN",
        "entry": "bots/admin_bot.py",
        "fallback_entry": "bots/group_guard_bot.py",
        "required_envs": ["VALKYRIEGROUPMOD_BOT_TOKEN", "DATABASE_URL"],
        "fallback_required_envs": ["VALKYRIEGROUPMOD_BOT_TOKEN"],
        "extra_env": {
            "TELEGRAM_BOT_TOKEN": "${VALKYRIEGROUPMOD_BOT_TOKEN}",
        },
    },
    "seller_buyer": {
        "label": "Seller/Buyer Bot",
        "token_env": "VALKYRIESELLERBUYER_BOT_TOKEN",
        "entry": "bots/seller_buyer_bot.py",
        "required_envs": ["VALKYRIESELLERBUYER_BOT_TOKEN", "DATABASE_URL", "BOT_ENCRYPTION_KEY"],
        "extra_env": {
            "SELLER_BUYER_BOT_TOKEN": "${VALKYRIESELLERBUYER_BOT_TOKEN}",
        },
    },
    "image_bot": {
        "label": "Valkyrie ImageGen Bot (Grok)",
        "token_env": "VALKYRIEIMAGE_BOT_TOKEN",
        "entry": "bots/grok_image_bot.py",
        "fallback_entry": "bots/image_bot.py",
        "required_envs": ["VALKYRIEIMAGE_BOT_TOKEN"],
        "fallback_required_envs": ["VALKYRIEIMAGE_BOT_TOKEN"],
    },
    "poster035_bot": {
        "label": "Valkyrie POSTER035 PRO",
        "token_env": "VALKYRIEPOSTER1249_BOT_TOKEN",
        "entry": "bots/llm_bridge_bot.py",
        "required_envs": ["VALKYRIEPOSTER1249_BOT_TOKEN"],
    },
    # Maigret bot removed - was conflicting with mother bot
    # "maigret_bot": {
    #     "label": "Maigret OSINT Bot",
    #     "token_env": "VALKYRIEMOTHER_BOT_TOKEN",
    #     "entry": "bots/maigret_bot.py",
    #     "required_envs": ["VALKYRIEMOTHER_BOT_TOKEN"],
    # },
    "welcome_bot": {
        "label": "The Lounge Bot",
        "token_env": "VALKYRIEWELCOME_BOT_TOKEN",
        "entry": "bots/lounge_bot.py",
        "required_envs": ["VALKYRIEWELCOME_BOT_TOKEN"],
        "extra_env": {
            "LOUNGE_BOT_TOKEN": "${VALKYRIEWELCOME_BOT_TOKEN}",
        },
    },
    "admin_api": {
        "label": "Admin API",
        "entry": "marketplace/admin_api.py",
        "required_envs": [
            "DATABASE_URL",
            "VALKYRIEGROUPMOD_BOT_TOKEN",
            "VALKYRIESELLERBUYER_BOT_TOKEN",
        ],
        "extra_env": {
            "TELEGRAM_BOT_TOKEN": "${VALKYRIEGROUPMOD_BOT_TOKEN}",
            "SELLER_BUYER_BOT_TOKEN": "${VALKYRIESELLERBUYER_BOT_TOKEN}",
            "BRIDGE_API_PORT": "5052",
        },
    },
    "discord_bridge": {
        "label": "Discord Bridge",
        "entry": "marketplace/discord_bridge_simple.py",
        "required_envs": ["DISCORD_BOT_TOKEN"],
        "extra_env": {},
    },
    "typebot_service": {
        "label": "Typebot Docker Services",
        "entry": "bots/runtime/typebot_service.py start",
        "required_envs": [],
        "extra_env": {},
    },
    "typebot_bot": {
        "label": "Typebot Telegram Bot",
        "token_env": "VALKYRIETYPEBOT_BOT_TOKEN",
        "entry": "bots/typebot_bot.py",
        "required_envs": ["VALKYRIETYPEBOT_BOT_TOKEN"],
        "extra_env": {
            "TYPEBOT_VIEWER_URL": "http://localhost:8081",
            "TYPEBOT_API_URL": "http://localhost:3000",
        },
    },
    "crypto_auth_bot": {
        "label": "CryptoAuth Bot (Betalingsadgang)",
        "token_env": "VALKYRIECRYPTOAUTH_BOT_TOKEN",
        "entry": "bots/crypto_auth_bot.py",
        "required_envs": ["VALKYRIECRYPTOAUTH_BOT_TOKEN"],
        "extra_env": {
            "CRYPTOAUTH_ADMIN_ID": "8505253720",
            "CRYPTOAUTH_GROUP_ID": "3837410272",
        },
    },
}


@dataclass
class ManagedProcess:
    name: str
    label: str
    primary_path: Path
    fallback_path: Path | None = None
    active_path: Path | None = None
    token_env: str | None = None
    required_envs: tuple[str, ...] = ()
    fallback_required_envs: tuple[str, ...] = ()
    extra_env: dict[str, str] = field(default_factory=dict)
    process: subprocess.Popen | None = None
    started_at: float | None = None
    last_error: str | None = None
    last_exit_code: int | None = None


class BotManager:
    def __init__(self):
        _normalize_env_aliases()
        self._lock = threading.Lock()
        self.bots = {}
        self.load_bots()

    def _resolve_path(self, name: str, config: dict) -> Path:
        entry = config.get("entry") or f"bots/{name}.py"
        return (ROOT_DIR / entry).resolve()

    def load_bots(self):
        loaded_bots = {}

        for name, config in ENABLED_PROCESSES.items():
            primary_path = self._resolve_path(name, config)
            fallback_entry = config.get("fallback_entry")
            fallback_path = (ROOT_DIR / fallback_entry).resolve() if fallback_entry else None
            token_env = config.get("token_env")
            required_envs = tuple(config.get("required_envs") or ([token_env] if token_env else []))
            if fallback_path:
                fallback_required_envs = tuple(
                    config.get("fallback_required_envs")
                    or ([token_env] if token_env else [])
                )
            else:
                # No fallback variant: treat "fallback" requirements the same as full.
                fallback_required_envs = required_envs
            extra_env = dict(config.get("extra_env") or {})

            bot = ManagedProcess(
                name=name,
                label=config["label"],
                primary_path=primary_path,
                fallback_path=fallback_path,
                active_path=primary_path,
                token_env=token_env,
                required_envs=required_envs,
                fallback_required_envs=fallback_required_envs,
                extra_env=extra_env,
            )

            if not primary_path.exists():
                bot.last_error = f"Entry file not found: {primary_path}"

            loaded_bots[name] = bot

        with self._lock:
            self.bots = loaded_bots

    def _process_status(self, bot):
        if bot.process is None:
            return False

        exit_code = bot.process.poll()
        if exit_code is None:
            return True

        bot.last_exit_code = exit_code
        bot.process = None
        if exit_code != 0 and not bot.last_error:
            bot.last_error = f"Bot exited with code {exit_code}"
        return False

    def _missing_env(self, required_envs: tuple[str, ...]) -> str | None:
        for key in required_envs:
            if not os.environ.get(key):
                return key
        return None

    def _select_variant(self, bot: ManagedProcess) -> tuple[Path, tuple[str, ...], str]:
        """
        Decide whether to run the primary (full) bot or the fallback (basic) bot.

        This keeps "basic" features available even when DB/keys are not configured,
        while automatically switching to the full original bots as soon as the
        required env vars exist.
        """

        full_missing = self._missing_env(bot.required_envs)
        if full_missing is None:
            return bot.primary_path, bot.required_envs, "full"

        if bot.fallback_path and bot.fallback_path.exists():
            basic_missing = self._missing_env(bot.fallback_required_envs)
            if basic_missing is None:
                return bot.fallback_path, bot.fallback_required_envs, "basic"

        return bot.primary_path, bot.required_envs, "full"

    def _expand_extra_env(self, extra_env: dict[str, str], env: dict[str, str]) -> dict[str, str]:
        pattern = re.compile(r"\$\{([^}]+)\}")

        def expand(value: str) -> str:
            def repl(match: re.Match) -> str:
                return env.get(match.group(1), "")

            return pattern.sub(repl, value)

        return {key: expand(value) for key, value in extra_env.items()}

    def start(self, name):
        _normalize_env_aliases()
        with self._lock:
            bot = self.bots.get(name)
            if bot is None:
                return False, "Unknown bot"

            path, required_envs, mode = self._select_variant(bot)
            bot.active_path = path

            if not path.exists():
                bot.last_error = f"Entry file not found: {path}"
                return False, bot.last_error

            missing = self._missing_env(required_envs)
            if missing:
                bot.last_error = f"Missing environment variable: {missing}"
                return False, bot.last_error

            if self._process_status(bot):
                return True, "Bot already running"

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env.update(self._expand_extra_env(bot.extra_env, env))

            bot.process = subprocess.Popen(
                [sys.executable, str(path)],
                cwd=str(ROOT_DIR),
                env=env,
            )
            bot.started_at = time.time()
            bot.last_error = None
            bot.last_exit_code = None

            return True, f"Bot started ({mode})"

    def start_all(self):
        for name in ENABLED_PROCESSES:
            ok, message = self.start(name)
            print(f"{name}: {message}")
            if not ok:
                continue

    def list_bots(self):
        with self._lock:
            bots = []
            for name in sorted(self.bots):
                bot = self.bots[name]
                running = self._process_status(bot)
                # Consider it "configured" if either full-mode OR basic-mode can start.
                configured = (
                    self._missing_env(bot.required_envs) is None
                    or self._missing_env(bot.fallback_required_envs) is None
                )
                bots.append(
                    {
                        "name": bot.name,
                        "label": bot.label,
                        "token_env": bot.token_env,
                        "configured": configured,
                        "required_envs": list(bot.required_envs),
                        "fallback_required_envs": list(bot.fallback_required_envs),
                        "entry": str(bot.active_path or bot.primary_path),
                        "running": running,
                        "pid": bot.process.pid if bot.process else None,
                        "last_exit_code": bot.last_exit_code,
                        "last_error": bot.last_error,
                        "started_at": bot.started_at,
                    }
                )

            return bots

    def stop(self, name):
        with self._lock:
            bot = self.bots.get(name)
            if bot is None:
                return False, "Unknown bot"

            if bot.process is None:
                return True, "Bot already stopped"

            if bot.process.poll() is None:
                bot.process.terminate()
                try:
                    bot.process.wait(timeout=STOP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    bot.process.kill()
                    bot.process.wait(timeout=STOP_TIMEOUT_SECONDS)

            bot.last_exit_code = bot.process.returncode
            bot.process = None
            return True, "Bot stopped"

    def restart(self, name):
        stopped, stop_message = self.stop(name)
        if not stopped:
            return False, stop_message
        return self.start(name)
