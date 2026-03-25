from bot_manager import BotManager
import time

m = BotManager()
print("=== Bot Status ===")
for b in m.list_bots():
    status = "RUNNING" if b["running"] else "STOPPED"
    error = b.get("last_error") or "None"
    print(f"{b['name']}: {status} (error: {error})")
