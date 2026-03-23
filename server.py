from flask import Flask, jsonify, send_from_directory
from bot_manager import BotManager
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="dashboard")
manager = BotManager()

@app.route("/")
def status():
    return jsonify({
        "status": "Valkyrie Cloud running",
        "bots": manager.list_bots()
    })

@app.route("/health")
def health():
    return "OK"

@app.route("/api/bots")
def api_bots():
    return jsonify(manager.list_bots())

@app.route("/api/start/<bot>")
def start_bot(bot):
    manager.start(bot)
    return jsonify({"started": bot})

@app.route("/api/stop/<bot>")
def stop_bot(bot):
    manager.stop(bot)
    return jsonify({"stopped": bot})

@app.route("/api/restart/<bot>")
def restart_bot(bot):
    manager.restart(bot)
    return jsonify({"restarted": bot})

@app.route("/dashboard")
def dashboard():
    return send_from_directory("dashboard", "index.html")

@app.route("/dashboard/<path:path>")
def dashboard_files(path):
    return send_from_directory("dashboard", path)

if __name__ == "__main__":
    print("⚡ Starting Valkyrie Cloud...")
    manager.start_all()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)