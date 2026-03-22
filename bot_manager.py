import os, importlib

class BotManager:
    def __init__(self):
        self.bots = {}

    def load_bots(self):
        base = "bots"
        if not os.path.isdir(base):
            return

        for name in os.listdir(base):
            try:
                module = importlib.import_module(f"bots.{name}.bot")
                self.bots[name] = module
            except Exception as e:
                print("Failed loading", name, e)

    def start_all(self):
        self.load_bots()
        for name, bot in self.bots.items():
            try:
                bot.start()
                print("Started", name)
            except Exception as e:
                print("Bot failed", name, e)

    def list_bots(self):
        return list(self.bots.keys())
