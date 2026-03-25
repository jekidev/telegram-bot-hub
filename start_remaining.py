from bot_manager import BotManager
import time

m = BotManager()

# Start remaining bots
bots_to_start = ['menu_bot', 'poster035_bot', 'welcome_bot', 'socks5_bot']

for name in bots_to_start:
    print(f'Starting {name}...')
    ok, msg = m.start(name)
    print(f'{name}: {msg}')
    time.sleep(1)

print('\n=== All bots status ===')
for b in m.list_bots():
    status = 'RUNNING' if b['running'] else 'STOPPED'
    print(f"{b['name']}: {status}")
