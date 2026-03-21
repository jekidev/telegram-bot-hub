import os
import psutil
from flask import Flask, jsonify

app = Flask(__name__)

BOTS_DIR = "bots"


def list_bots():
    bots = []
    if os.path.exists(BOTS_DIR):
        for f in os.listdir(BOTS_DIR):
            if f.endswith(".py"):
                bots.append(f)
    return bots


@app.route("/")
def home():
    return jsonify({
        "service": "Telegram Bot Hub",
        "status": "running",
        "bots": list_bots(),
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent
    })


@app.route("/bots")
def bots():
    return jsonify({"running_bots": list_bots()})


@app.route("/health")
def health():
    return "ok"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
