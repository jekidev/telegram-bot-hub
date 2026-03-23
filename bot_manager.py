import os
import importlib
import threading

class BotManager:

    def __init__(self):

        self.bots = {}
        self.bot_threads = {}

    def load_bots(self):

        bot_folder = "bots"

        for file in os.listdir(bot_folder):

            if not file.endswith(".py"):
                continue

            name = file.replace(".py","")

            try:

                module = importlib.import_module(f"bots.{name}")

                self.bots[name] = module

                print("Loaded bot:", name)

            except Exception as e:

                print("Failed loading bot:", name, e)


    def start(self, name):

        if name not in self.bots:
            return

        module = self.bots[name]

        if hasattr(module,"main"):

            t = threading.Thread(target=module.main)
            t.start()

            self.bot_threads[name] = t

            print("Started bot:", name)


    def start_all(self):

        self.load_bots()

        for name in self.bots:

            self.start(name)


    def list_bots(self):

        return list(self.bots.keys())


    def stop(self,name):

        print("Stop not implemented yet")


    def restart(self,name):

        self.stop(name)
        self.start(name)