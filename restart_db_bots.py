from bot_manager import BotManager
import time

m = BotManager()

# Restart bots that need database
bots_to_restart = ['seller_buyer', 'admin_api', 'group_guard_bot']

for name in bots_to_restart:
    print(f'Restarting {name}...')
    m.stop(name)
    time.sleep(1)
    ok, msg = m.start(name)
    print(f'{name}: {msg}')

print('\n=== All bots status ===')
for b in m.list_bots():
    status = 'RUNNING' if b['running'] else 'STOPPED'
    print(f"{b['name']}: {status}")
