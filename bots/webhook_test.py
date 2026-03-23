import os
from dotenv import load_dotenv
from flask import Flask, request
import telegram

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")
app = Flask(__name__)

# Initialize bot
bot = telegram.Bot(token=TOKEN)

@app.route('/webhook', methods=['POST'])
def webhook():
    update = telegram.Update.de_json(request.get_json(force=True), bot)
    
    if update.message and update.message.text == '/start':
        chat_id = update.message.chat.id
        bot.send_message(chat_id=chat_id, text="⚡ WEBHOOK BOT WORKS!")
        print("✅ Webhook bot responded!")
    
    return 'OK'

@app.route('/set-webhook', methods=['GET'])
def set_webhook():
    # Set webhook (replace with your Render URL when deployed)
    webhook_url = "https://your-app.onrender.com/webhook"
    bot.set_webhook(url=webhook_url)
    return f"Webhook set to {webhook_url}"

@app.route('/')
def home():
    return "Webhook bot is running!"

if __name__ == '__main__':
    if not TOKEN:
        print("❌ Missing token")
    else:
        print("🚀 Webhook bot starting on port 5000...")
        app.run(host='0.0.0.0', port=5000)
