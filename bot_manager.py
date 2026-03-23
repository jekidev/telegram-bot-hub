import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
BOTS_DIR = ROOT_DIR / "bots"
STOP_TIMEOUT_SECONDS = 10

ENABLED_BOTS = {
    "menu_bot": {
        "label": "Menu Bot",
        "token_env": "VALKYRIEMENU_BOT_TOKEN",
    },
    "group_guard_bot": {
        "label": "Group Guard Bot",
        "token_env": "VALKYRIEGROUPMOD_BOT_TOKEN",
    },
    "image_bot": {
        "label": "Image Bot",
        "token_env": "VALKYRIESELLERBUYER_BOT_TOKEN",
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
        "label": "Welcome Bot",
        "token_env": "VALKYRIEWELCOME_BOT_TOKEN",
    },
}


@dataclass
class ManagedBot:
    name: str
    label: str
    token_env: str
    path: Path
    process: subprocess.Popen | None = None
    started_at: float | None = None
    last_error: str | None = None
    last_exit_code: int | None = None


class BotManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.bots = {}
        self.load_bots()

    def load_bots(self):
        loaded_bots = {}

        for name, config in ENABLED_BOTS.items():
            path = BOTS_DIR / f"{name}.py"
            bot = ManagedBot(
                name=name,
                label=config["label"],
                token_env=config["token_env"],
                path=path,
            )

            if not path.exists():
                bot.last_error = f"Bot file not found: {path.name}"

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

    def start(self, name):
        with self._lock:
            bot = self.bots.get(name)
            if bot is None:
                return False, "Unknown bot"

            if not bot.path.exists():
                bot.last_error = f"Bot file not found: {bot.path.name}"
                return False, bot.last_error

            if not os.environ.get(bot.token_env):
                bot.last_error = f"Missing environment variable: {bot.token_env}"
                return False, bot.last_error

            if self._process_status(bot):
                return True, "Bot already running"

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"

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
        for name in ENABLED_BOTS:
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
                bots.append(
                    {
                        "name": bot.name,
                        "label": bot.label,
                        "token_env": bot.token_env,
                        "configured": bool(os.environ.get(bot.token_env)),
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
