import os
from dotenv import load_dotenv
import requests
import time

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")

def get_updates():
    """Get updates from Telegram and respond to /start"""
    if not TOKEN:
        print("❌ Missing token")
        return
    
    print("🚀 Starting final bot...")
    
    offset = 0
    while True:
        try:
            # Get updates
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset={offset}&timeout=30"
            response = requests.get(url, timeout=35)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("ok") and data.get("result"):
                    for update in data["result"]:
                        offset = update["update_id"] + 1
                        
                        # Handle /start command
                        if "message" in update and "text" in update["message"]:
                            if update["message"]["text"] == "/start":
                                chat_id = update["message"]["chat"]["id"]
                                
                                # Send response
                                send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                                send_data = {
                                    "chat_id": chat_id,
                                    "text": "⚡ FINAL BOT IS WORKING! 🎉"
                                }
                                
                                send_response = requests.post(send_url, json=send_data)
                                if send_response.status_code == 200:
                                    print("✅ Bot responded to /start!")
                                else:
                                    print(f"❌ Failed to send message: {send_response.text}")
                                
            else:
                print(f"❌ Error getting updates: {response.text}")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    get_updates()
