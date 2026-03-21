import threading
import subprocess
import os

# start dashboard

def start_dashboard():
    subprocess.Popen(["python","web/dashboard_server.py"])

# start bot orchestrator

def start_bots():
    subprocess.Popen(["python","main.py"])

if __name__ == "__main__":
    t1 = threading.Thread(target=start_dashboard)
    t2 = threading.Thread(target=start_bots)

    t1.start()
    t2.start()

    t1.join()
    t2.join()
