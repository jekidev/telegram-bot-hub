import os
import subprocess
import time

class BotManager:
    def __init__(self):
        self.bots = {}
        self.processes = {}

    def load_bots(self):
        # Run debug bot to see what's wrong
        bot_files = [
            ("debug_bot", "VALKYRIEMENU_BOT_TOKEN"),
        ]
        
        for bot_name, token_env in bot_files:
            token = os.getenv(token_env)
            if token and token != "PASTE_TOKEN_HERE":
                self.bots[bot_name] = token_env
                print(f"Loaded bot: {bot_name}")
            else:
                print(f"Skipping {bot_name} - missing token {token_env}")

    def start_all(self):
        self.load_bots()
        
        for bot_name, token_env in self.bots.items():
            try:
                # Start each bot as a separate process
                cmd = ["python", f"bots/{bot_name}.py"]
                process = subprocess.Popen(cmd, cwd=os.getcwd())
                self.processes[bot_name] = process
                print(f"Started {bot_name} (PID: {process.pid})")
                time.sleep(2)  # Stagger starts to avoid conflicts
            except Exception as e:
                print(f"Failed to start {bot_name}: {e}")
        
        # Monitor processes
        def monitor():
            while True:
                time.sleep(15)
                for name, proc in self.processes.items():
                    if proc.poll() is not None:
                        print(f"Bot {name} crashed, restarting...")
                        cmd = ["python", f"bots/{name}.py"]
                        self.processes[name] = subprocess.Popen(cmd, cwd=os.getcwd())
                        print(f"Restarted {name}")
                        time.sleep(2)
        
        # Start monitoring in background
        import threading
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

    def list_bots(self):
        return list(self.bots.keys())
