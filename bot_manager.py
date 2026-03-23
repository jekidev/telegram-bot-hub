import os
import importlib
import threading

class BotManager:
    def __init__(self):
        self.bots = {}
        self.threads = {}

    def load_bots(self):
        base = "bots"
        if not os.path.isdir(base):
            print("Bots directory not found")
            return

        bot_files = [
            "group_guard_bot",
            "menu_bot", 
            "image_bot",
            "llm_bridge_bot",
            "valkyrie_llm_bot", 
            "maigret_bot"
        ]
        
        for bot_name in bot_files:
            try:
                module = importlib.import_module(f"bots.{bot_name}")
                if hasattr(module, 'start'):
                    self.bots[bot_name] = module
                    print(f"Loaded bot: {bot_name}")
                else:
                    print(f"Bot {bot_name} missing start() function")
            except Exception as e:
                print(f"Failed loading {bot_name}: {e}")

    def start_all(self):
        self.load_bots()
        for name, bot_module in self.bots.items():
            try:
                # Start each bot in a separate thread
                thread = threading.Thread(target=bot_module.start, daemon=True)
                thread.start()
                self.threads[name] = thread
                print(f"Started {name}")
            except Exception as e:
                print(f"Failed to start {name}: {e}")

    def list_bots(self):
        return list(self.bots.keys())
