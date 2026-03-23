import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
STOP_TIMEOUT_SECONDS = 10

ENABLED_PROCESSES = {
    "menu_bot": {
        "label": "Menu Bot",
        "token_env": "VALKYRIEMENU_BOT_TOKEN",
    },
    "group_guard_bot": {
        "label": "Group Guard Admin Bot",
        "token_env": "VALKYRIEGROUPMOD_BOT_TOKEN",
        "entry": "marketplace/admin_bot.py",
        "required_envs": ["VALKYRIEGROUPMOD_BOT_TOKEN", "DATABASE_URL"],
        "extra_env": {
            "TELEGRAM_BOT_TOKEN": "${VALKYRIEGROUPMOD_BOT_TOKEN}",
        },
    },
    "image_bot": {
        "label": "Marketplace (Seller/Buyer) Bot",
        "token_env": "VALKYRIESELLERBUYER_BOT_TOKEN",
        "entry": "marketplace/seller_buyer_bot.py",
        "required_envs": [
            "VALKYRIESELLERBUYER_BOT_TOKEN",
            "DATABASE_URL",
            "BOT_ENCRYPTION_KEY",
        ],
        "extra_env": {
            "SELLER_BUYER_BOT_TOKEN": "${VALKYRIESELLERBUYER_BOT_TOKEN}",
        },
    },
    "llm_bridge_bot": {
        "label": "LLM Bridge Bot",
        "token_env": "VALKYRIEPOSTER1249_BOT_TOKEN",
    },
    "maigret_bot": {
        "label": "Maigret Bot",
        "token_env": "VALKYRIEMOTHER_BOT_TOKEN",
    },
    "welcome_bot": {
        "label": "The Lounge Bot",
        "token_env": "VALKYRIEWELCOME_BOT_TOKEN",
        "entry": "lounge/lounge_bot.py",
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
            "BRIDGE_API_KEY",
            "VALKYRIEGROUPMOD_BOT_TOKEN",
            "VALKYRIESELLERBUYER_BOT_TOKEN",
        ],
        "extra_env": {
            "TELEGRAM_BOT_TOKEN": "${VALKYRIEGROUPMOD_BOT_TOKEN}",
            "SELLER_BUYER_BOT_TOKEN": "${VALKYRIESELLERBUYER_BOT_TOKEN}",
            "BRIDGE_API_PORT": "5050",
        },
    },
    "discord_bridge": {
        "label": "Discord Bridge",
        "entry": "marketplace/discord_bridge.py",
        "required_envs": ["DISCORD_BOT_TOKEN", "BRIDGE_API_KEY"],
        "extra_env": {
            "BRIDGE_API_URL": "http://127.0.0.1:5050",
        },
    },
}


@dataclass
class ManagedProcess:
    name: str
    label: str
    path: Path
    token_env: str | None = None
    required_envs: tuple[str, ...] = ()
    extra_env: dict[str, str] = field(default_factory=dict)
    process: subprocess.Popen | None = None
    started_at: float | None = None
    last_error: str | None = None
    last_exit_code: int | None = None


class BotManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.bots = {}
        self.load_bots()

    def _resolve_path(self, name: str, config: dict) -> Path:
        entry = config.get("entry") or f"bots/{name}.py"
        return (ROOT_DIR / entry).resolve()

    def load_bots(self):
        loaded_bots = {}

        for name, config in ENABLED_PROCESSES.items():
            path = self._resolve_path(name, config)
            token_env = config.get("token_env")
            required_envs = tuple(config.get("required_envs") or ([token_env] if token_env else []))
            extra_env = dict(config.get("extra_env") or {})

            bot = ManagedProcess(
                name=name,
                label=config["label"],
                path=path,
                token_env=token_env,
                required_envs=required_envs,
                extra_env=extra_env,
            )

            if not path.exists():
                bot.last_error = f"Entry file not found: {path}"

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

    def _missing_env(self, bot: ManagedProcess) -> str | None:
        for key in bot.required_envs:
            if not os.environ.get(key):
                return key
        return None

    def _expand_extra_env(self, extra_env: dict[str, str], env: dict[str, str]) -> dict[str, str]:
        pattern = re.compile(r"\$\{([^}]+)\}")

        def expand(value: str) -> str:
            def repl(match: re.Match) -> str:
                return env.get(match.group(1), "")

            return pattern.sub(repl, value)

        return {key: expand(value) for key, value in extra_env.items()}

    def start(self, name):
        with self._lock:
            bot = self.bots.get(name)
            if bot is None:
                return False, "Unknown bot"

            if not bot.path.exists():
                bot.last_error = f"Entry file not found: {bot.path}"
                return False, bot.last_error

            missing = self._missing_env(bot)
            if missing:
                bot.last_error = f"Missing environment variable: {missing}"
                return False, bot.last_error

            if self._process_status(bot):
                return True, "Bot already running"

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env.update(self._expand_extra_env(bot.extra_env, env))

            bot.process = subprocess.Popen(
                [sys.executable, str(bot.path)],
                cwd=str(ROOT_DIR),
                env=env,
            )
            bot.started_at = time.time()
            bot.last_error = None
            bot.last_exit_code = None

            return True, "Bot started"

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
                configured = self._missing_env(bot) is None
                bots.append(
                    {
                        "name": bot.name,
                        "label": bot.label,
                        "token_env": bot.token_env,
                        "configured": configured,
                        "required_envs": list(bot.required_envs),
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
