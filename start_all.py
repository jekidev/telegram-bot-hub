import sys
import time
from bot_manager import BotManager

print("=== Starting all Valkyrie bots ===")
m = BotManager()

results = []
for name in m.bots:
    ok, msg = m.start(name)
    results.append((name, ok, msg))
    status = "✅" if ok else "❌"
    print(f"{status} {name}: {msg}")

print("\n=== Waiting 5 seconds for bots to initialize ===")
time.sleep(5)

print("\n=== Final Status ===")
for b in m.list_bots():
    status = "🟢 RUNNING" if b["running"] else "🔴 STOPPED"
    error = b.get("last_error") or ""
    if error:
        print(f"{b['name']}: {status} - {error}")
    else:
        print(f"{b['name']}: {status}")

print("\n💡 For at bruge bots:")
print("   1. Gå til bot i Telegram DM")
print("   2. Tryk på 'START' knappen nederst")
print("   3. Botten viser knapper/menu")
print("\nTryk Ctrl+C for at stoppe alle bots")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n\n=== Stopping all bots ===")
    for name in m.bots:
        m.stop(name)
    print("All bots stopped.")
