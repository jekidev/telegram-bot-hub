import os
import subprocess
import time

BOTS_DIR = "bots"
processes = {}


def discover_bots():
    bots = []
    if not os.path.exists(BOTS_DIR):
        return bots

    for root, dirs, files in os.walk(BOTS_DIR):
        for f in files:
            if f.endswith(".py"):
                bots.append(os.path.join(root, f))

    return bots


def start_bot(path):
    print(f"Starting bot: {path}")
    p = subprocess.Popen(["python", path])
    processes[path] = p


def start_all():
    for bot in discover_bots():
        if bot not in processes:
            start_bot(bot)


def monitor():
    while True:
        for path, proc in list(processes.items()):
            if proc.poll() is not None:
                print(f"Restarting crashed bot: {path}")
                start_bot(path)
        time.sleep(10)


if __name__ == "__main__":
    start_all()
    monitor()
