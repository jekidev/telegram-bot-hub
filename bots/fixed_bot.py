import os
from dotenv import load_dotenv
import requests
import time

load_dotenv()
TOKEN = os.getenv("VALKYRIEMENU_BOT_TOKEN")

def get_updates():
    """Get updates from Telegram and respond to commands"""
    if not TOKEN:
        print("❌ Missing token")
        return
    
    print("🚀 Starting FIXED bot...")
    
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
                        
                        # Handle messages
                        if "message" in update and "text" in update["message"]:
                            chat_id = update["message"]["chat"]["id"]
                            text = update["message"]["text"]
                            
                            print(f"📨 Received: {text}")
                            
                            # Respond to commands
                            if text == "/start":
                                response_text = "⚡ BOT IS WORKING! 🎉\n\nCommands:\n/start - Show this message\n/menu - Show menu\n/help - Get help"
                                
                            elif text == "/menu":
                                response_text = "🚀 VALKYRIE MENU\n━━━━━━━━━━━━━━\n• Group Guard - Active\n• Menu Bot - Active\n• Image Bot - Active\n• LLM Bridge - Active\n• Valkyrie LLM - Active\n• Maigret OSINT - Active\n\n━━━━━━━━━━━━━━"
                                
                            elif text == "/help":
                                response_text = "🤖 Help: Use /start, /menu, or /help"
                                
                            else:
                                continue  # Don't respond to other messages
                            
                            # Send response
                            send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                            send_data = {
                                "chat_id": chat_id,
                                "text": response_text
                            }
                            
                            send_response = requests.post(send_url, json=send_data)
                            if send_response.status_code == 200:
                                print(f"✅ Responded to: {text}")
                            else:
                                print(f"❌ Failed to send: {send_response.text}")
                                
            else:
                print(f"❌ Error getting updates: {response.text}")
                
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    get_updates()
