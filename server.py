from flask import Flask, jsonify
from bot_manager import BotManager
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
manager = BotManager()

@app.route("/")
def status():
    return jsonify({"status": "Valkyrie Cloud running", "bots": manager.list_bots()})

@app.route("/health")
def health():
    return "OK"

if __name__ == "__main__":
    print("Starting Valkyrie Cloud...")
    manager.start_all()
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)
