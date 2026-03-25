import sys
import time
from bot_manager import BotManager

print("=== Starting all bots ===")
m = BotManager()

# Stop any existing bots first
for name in m.bots:
    m.stop(name)
    print(f"Stopped: {name}")

print("\n--- Starting fresh ---")
m.start_all()

print("\n=== Status after 5 seconds ===")
time.sleep(5)
for b in m.list_bots():
    status = "RUNNING" if b["running"] else "STOPPED"
    print(f"{b['name']}: {status}")

print("\nPress Ctrl+C to stop all bots")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nStopping all bots...")
    for name in m.bots:
        m.stop(name)
    print("All bots stopped.")
    sys.exit(0)
