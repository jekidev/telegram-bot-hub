import os

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect

from bot_manager import BotManager

load_dotenv()

app = Flask(__name__, static_folder="dashboard", static_url_path="")
manager = BotManager()


@app.route("/")
def dashboard():
    return app.send_static_file("index.html")


@app.route("/dashboard")
def legacy_dashboard():
    return redirect("/")


@app.get("/api/bots")
def api_bots():
    return jsonify(
        {
            "status": "Valkyrie Cloud running",
            "bots": manager.list_bots(),
        }
    )


@app.post("/api/start/<bot_name>")
def start_bot(bot_name):
    ok, message = manager.start(bot_name)
    status_code = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "bot": bot_name}), status_code


@app.post("/api/stop/<bot_name>")
def stop_bot(bot_name):
    ok, message = manager.stop(bot_name)
    status_code = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "bot": bot_name}), status_code


@app.post("/api/restart/<bot_name>")
def restart_bot(bot_name):
    ok, message = manager.restart(bot_name)
    status_code = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "bot": bot_name}), status_code


@app.route("/health")
def health():
    return jsonify({"status": "ok", "bots": manager.list_bots()})


if __name__ == "__main__":
    print("Starting Valkyrie Cloud")
    manager.start_all()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
