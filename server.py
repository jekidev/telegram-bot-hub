from flask import Flask, jsonify
from bot_manager import BotManager

app = Flask(__name__)
manager = BotManager()

@app.route("/")
def status():
    return jsonify({"status": "Valkyrie Cloud running", "bots": manager.list_bots()})

if __name__ == "__main__":
    manager.start_all()
    app.run(host="0.0.0.0", port=10000)
